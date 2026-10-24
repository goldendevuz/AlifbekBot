"""User quota, subscription tier, and credit management service."""
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from app.database import get_connection
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class QuotaService:
    @staticmethod
    def ensure_user(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> Dict[str, Any]:
        """Ensure user exists in users table and update activity timestamp."""
        conn = get_connection()
        try:
            now = int(time.time())
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not user:
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, first_name, role, tier, credits_balance, unlimited_quota, is_blocked, created_at, last_active_at)
                    VALUES (?, ?, ?, 'user', 'free', 20000, 0, 0, ?, ?)
                    """,
                    (user_id, username, first_name, now, now),
                )
                conn.commit()
                return {
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "role": "user",
                    "tier": "free",
                    "credits_balance": 20000,
                    "unlimited_quota": False,
                    "is_blocked": False,
                    "created_at": now,
                    "last_active_at": now,
                }
            else:
                conn.execute(
                    "UPDATE users SET last_active_at = ?, username = COALESCE(?, username), first_name = COALESCE(?, first_name) WHERE user_id = ?",
                    (now, username, first_name, user_id),
                )
                conn.commit()
                return dict(user)
        finally:
            conn.close()

    @staticmethod
    def list_users(
        search: Optional[str] = None,
        tier: Optional[str] = None,
        role: Optional[str] = None,
        is_blocked: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List users with multi-criteria filtering and telemetry stats."""
        conn = get_connection()
        try:
            query = "SELECT u.*, COUNT(e.ts) as conversions_count, COALESCE(SUM(e.chars), 0) as total_chars_processed FROM users u LEFT JOIN events e ON u.user_id = e.user_id WHERE 1=1"
            count_query = "SELECT COUNT(*) FROM users u WHERE 1=1"
            params: List[Any] = []
            count_params: List[Any] = []

            if search:
                pattern = f"%{search}%"
                clause = " AND (u.username LIKE ? OR u.first_name LIKE ? OR CAST(u.user_id AS TEXT) LIKE ?)"
                query += clause
                count_query += clause
                params.extend([pattern, pattern, pattern])
                count_params.extend([pattern, pattern, pattern])

            if tier:
                query += " AND u.tier = ?"
                count_query += " AND u.tier = ?"
                params.append(tier)
                count_params.append(tier)

            if role:
                query += " AND u.role = ?"
                count_query += " AND u.role = ?"
                params.append(role)
                count_params.append(role)

            if is_blocked is not None:
                val = 1 if is_blocked else 0
                query += " AND u.is_blocked = ?"
                count_query += " AND u.is_blocked = ?"
                params.append(val)
                count_params.append(val)

            total_count = conn.execute(count_query, count_params).fetchone()[0]

            query += " GROUP BY u.user_id ORDER BY u.last_active_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            users = []
            for r in rows:
                u = dict(r)
                u["unlimited_quota"] = bool(u.get("unlimited_quota", 0))
                u["is_blocked"] = bool(u.get("is_blocked", 0))
                users.append(u)

            return users, total_count
        finally:
            conn.close()

    @staticmethod
    def adjust_credits(
        user_id: int,
        delta: int,
        action_type: str = "add",
        actor: str = "superadmin",
        reason: str = "Manual admin adjustment",
    ) -> Dict[str, Any]:
        """Adjust credits balance with automatic audit logging and rollback payload."""
        conn = get_connection()
        try:
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not user:
                raise ValueError("User not found")

            old_balance = user["credits_balance"]
            old_unlimited = bool(user["unlimited_quota"])

            new_unlimited = old_unlimited
            if action_type == "unlimited":
                new_balance = old_balance
                new_unlimited = True
            elif action_type == "add":
                new_balance = max(0, old_balance + delta)
                new_unlimited = False
            elif action_type == "subtract":
                new_balance = max(0, old_balance - delta)
                new_unlimited = False
            elif action_type == "set":
                new_balance = max(0, delta)
                new_unlimited = False
            else:
                raise ValueError(f"Unknown action_type: {action_type}")

            conn.execute(
                "UPDATE users SET credits_balance = ?, unlimited_quota = ? WHERE user_id = ?",
                (new_balance, 1 if new_unlimited else 0, user_id),
            )
            conn.commit()

            # Record audit trail with rollback payload
            AuditService.record_action(
                actor=actor,
                action="credit_adjust",
                target_type="user",
                target_id=str(user_id),
                details={
                    "old_balance": old_balance,
                    "new_balance": new_balance,
                    "action_type": action_type,
                    "delta": delta,
                    "reason": reason,
                },
                rollback_payload={
                    "credits_balance": old_balance,
                    "unlimited_quota": 1 if old_unlimited else 0,
                },
            )

            return {
                "user_id": user_id,
                "old_balance": old_balance,
                "new_balance": new_balance,
                "unlimited_quota": new_unlimited,
                "message": "Credits successfully adjusted",
            }
        finally:
            conn.close()

    @staticmethod
    def set_tier(
        user_id: int,
        tier: str,
        actor: str = "superadmin",
        reason: str = "Tier update",
    ) -> Dict[str, Any]:
        """Assign a new subscription tier with automatic quota synchronization."""
        conn = get_connection()
        try:
            tier_row = conn.execute("SELECT * FROM tiers WHERE id = ?", (tier,)).fetchone()
            if not tier_row:
                raise ValueError(f"Tier '{tier}' does not exist")

            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not user:
                raise ValueError("User not found")

            old_tier = user["tier"]
            old_balance = user["credits_balance"]
            old_unlimited = bool(user["unlimited_quota"])

            # Sync quota based on tier defaults
            new_balance = max(old_balance, tier_row["daily_char_limit"])
            new_unlimited = True if tier == "business" else False

            conn.execute(
                "UPDATE users SET tier = ?, credits_balance = ?, unlimited_quota = ? WHERE user_id = ?",
                (tier, new_balance, 1 if new_unlimited else 0, user_id),
            )
            conn.commit()

            AuditService.record_action(
                actor=actor,
                action="tier_change",
                target_type="user",
                target_id=str(user_id),
                details={
                    "old_tier": old_tier,
                    "new_tier": tier,
                    "reason": reason,
                },
                rollback_payload={
                    "tier": old_tier,
                    "credits_balance": old_balance,
                    "unlimited_quota": 1 if old_unlimited else 0,
                },
            )

            return {
                "user_id": user_id,
                "old_tier": old_tier,
                "new_tier": tier,
                "credits_balance": new_balance,
                "unlimited_quota": new_unlimited,
                "message": f"User upgraded to {tier_row['name']}",
            }
        finally:
            conn.close()

    @staticmethod
    def toggle_status(
        user_id: int,
        is_blocked: bool,
        actor: str = "superadmin",
        reason: str = "Status toggle",
    ) -> Dict[str, Any]:
        """Block or unblock user access."""
        conn = get_connection()
        try:
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not user:
                raise ValueError("User not found")

            old_blocked = bool(user["is_blocked"])
            conn.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (1 if is_blocked else 0, user_id))
            conn.commit()

            AuditService.record_action(
                actor=actor,
                action="status_toggle",
                target_type="user",
                target_id=str(user_id),
                details={
                    "old_status": "blocked" if old_blocked else "active",
                    "new_status": "blocked" if is_blocked else "active",
                    "reason": reason,
                },
                rollback_payload={
                    "is_blocked": 1 if old_blocked else 0,
                },
            )

            return {
                "user_id": user_id,
                "is_blocked": is_blocked,
                "message": f"User has been {'blocked' if is_blocked else 'unblocked'}",
            }
        finally:
            conn.close()

    @staticmethod
    def get_tiers() -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM tiers ORDER BY price_uzs ASC").fetchall()
            tiers = []
            for r in rows:
                t = dict(r)
                t["features"] = json.loads(t["features"]) if t.get("features") else []
                tiers.append(t)
            return tiers
        finally:
            conn.close()
