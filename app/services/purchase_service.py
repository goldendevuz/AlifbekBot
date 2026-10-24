"""Purchase request service for handling tariff orders and approvals."""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.database import get_connection
from app.services.audit_service import AuditService
from app.services.quota_service import QuotaService

logger = logging.getLogger(__name__)


class PurchaseService:
    @staticmethod
    def create_request(
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        tier_id: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new tariff purchase request."""
        conn = get_connection()
        try:
            tier_row = conn.execute("SELECT * FROM tiers WHERE id = ?", (tier_id,)).fetchone()
            if not tier_row:
                raise ValueError(f"Tarif topilmadi: {tier_id}")

            tier_name = tier_row["name"]
            price_uzs = tier_row["price_uzs"]
            now = int(time.time())

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO purchase_requests 
                (user_id, username, first_name, tier_id, tier_name, price_uzs, status, handled_by, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?, ?)
                """,
                (user_id, username, first_name, tier_id, tier_name, price_uzs, notes, now, now),
            )
            req_id = cursor.lastrowid
            conn.commit()

            return {
                "id": req_id,
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "tier_id": tier_id,
                "tier_name": tier_name,
                "price_uzs": price_uzs,
                "status": "pending",
                "handled_by": None,
                "notes": notes,
                "created_at": now,
                "updated_at": now,
                "daily_char_limit": tier_row["daily_char_limit"],
            }
        finally:
            conn.close()

    @staticmethod
    def get_request(request_id: int) -> Optional[Dict[str, Any]]:
        """Fetch purchase request by its ID."""
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT p.*, t.daily_char_limit, t.features, u.credits_balance, u.tier as current_tier
                FROM purchase_requests p
                LEFT JOIN tiers t ON p.tier_id = t.id
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE p.id = ?
                """,
                (request_id,),
            ).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    @staticmethod
    def list_requests(
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List purchase requests with optional status filtering."""
        conn = get_connection()
        try:
            query = "SELECT * FROM purchase_requests WHERE 1=1"
            count_query = "SELECT COUNT(*) FROM purchase_requests WHERE 1=1"
            params: List[Any] = []
            count_params: List[Any] = []

            if status:
                query += " AND status = ?"
                count_query += " AND status = ?"
                params.append(status)
                count_params.append(status)

            total = conn.execute(count_query, count_params).fetchone()[0]

            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows], total
        finally:
            conn.close()

    @staticmethod
    def approve_request(request_id: int, actor: str = "admin") -> Dict[str, Any]:
        """Approve purchase request, update status, and assign user tier."""
        conn = get_connection()
        try:
            req = conn.execute("SELECT * FROM purchase_requests WHERE id = ?", (request_id,)).fetchone()
            if not req:
                raise ValueError(f"So'rov #{request_id} topilmadi")

            if req["status"] == "approved":
                raise ValueError(f"So'rov #{request_id} allaqachon tasdiqlangan")

            now = int(time.time())
            conn.execute(
                "UPDATE purchase_requests SET status = 'approved', handled_by = ?, updated_at = ? WHERE id = ?",
                (actor, now, request_id),
            )
            conn.commit()

            # Automatically upgrade user tier and quota
            QuotaService.set_tier(
                user_id=req["user_id"],
                tier=req["tier_id"],
                actor=actor,
                reason=f"Purchase request #{request_id} approved",
            )

            AuditService.record_action(
                actor=actor,
                action="purchase_approve",
                target_type="purchase_request",
                target_id=str(request_id),
                details={
                    "user_id": req["user_id"],
                    "tier_id": req["tier_id"],
                    "price_uzs": req["price_uzs"],
                },
            )

            updated = conn.execute(
                """
                SELECT p.*, t.daily_char_limit 
                FROM purchase_requests p 
                LEFT JOIN tiers t ON p.tier_id = t.id 
                WHERE p.id = ?
                """,
                (request_id,),
            ).fetchone()
            return dict(updated)
        finally:
            conn.close()

    @staticmethod
    def reject_request(request_id: int, actor: str = "admin", reason: str = "Rad etildi") -> Dict[str, Any]:
        """Reject purchase request."""
        conn = get_connection()
        try:
            req = conn.execute("SELECT * FROM purchase_requests WHERE id = ?", (request_id,)).fetchone()
            if not req:
                raise ValueError(f"So'rov #{request_id} topilmadi")

            if req["status"] == "rejected":
                raise ValueError(f"So'rov #{request_id} allaqachon rad etilgan")

            now = int(time.time())
            conn.execute(
                "UPDATE purchase_requests SET status = 'rejected', handled_by = ?, notes = ?, updated_at = ? WHERE id = ?",
                (actor, reason, now, request_id),
            )
            conn.commit()

            AuditService.record_action(
                actor=actor,
                action="purchase_reject",
                target_type="purchase_request",
                target_id=str(request_id),
                details={
                    "user_id": req["user_id"],
                    "tier_id": req["tier_id"],
                    "reason": reason,
                },
            )

            updated = conn.execute("SELECT * FROM purchase_requests WHERE id = ?", (request_id,)).fetchone()
            return dict(updated)
        finally:
            conn.close()
