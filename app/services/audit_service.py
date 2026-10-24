"""Audit trail and 1-Click Rollback engine for administrative operations."""
import json
import logging
import time
from typing import Any, Dict, List, Optional
from app.database import get_connection

logger = logging.getLogger(__name__)


class AuditService:
    @staticmethod
    def record_action(
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        details: Dict[str, Any],
        rollback_payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Log an administrative action with optional rollback delta."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO audit_logs (actor, action, target_type, target_id, details, rollback_payload, is_rolled_back, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    actor,
                    action,
                    target_type,
                    str(target_id),
                    json.dumps(details) if details else None,
                    json.dumps(rollback_payload) if rollback_payload else None,
                    int(time.time()),
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    @staticmethod
    def get_logs(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, actor, action, target_type, target_id, details, rollback_payload, is_rolled_back, created_at
                FROM audit_logs
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            result = []
            for r in rows:
                result.append({
                    "id": r["id"],
                    "actor": r["actor"],
                    "action": r["action"],
                    "target_type": r["target_type"],
                    "target_id": r["target_id"],
                    "details": json.loads(r["details"]) if r["details"] else {},
                    "rollback_payload": json.loads(r["rollback_payload"]) if r["rollback_payload"] else None,
                    "is_rolled_back": bool(r["is_rolled_back"]),
                    "created_at": r["created_at"],
                })
            return result
        finally:
            conn.close()

    @staticmethod
    def rollback(audit_id: int, rollback_actor: str = "superadmin") -> Dict[str, Any]:
        """Execute 1-click rollback on a specific audited transaction."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM audit_logs WHERE id = ?", (audit_id,)
            ).fetchone()
            if not row:
                raise ValueError("Audit log record not found")

            if row["is_rolled_back"]:
                raise ValueError("This action has already been rolled back")

            if not row["rollback_payload"]:
                raise ValueError("No rollback delta payload available for this action")

            payload = json.loads(row["rollback_payload"])
            target_type = row["target_type"]
            target_id = row["target_id"]

            if target_type == "user":
                user_id = int(target_id)
                # Apply rollback attributes for user
                updates = []
                params = []
                for key in ["credits_balance", "tier", "unlimited_quota", "is_blocked"]:
                    if key in payload:
                        updates.append(f"{key} = ?")
                        params.append(payload[key])

                if updates:
                    params.append(user_id)
                    conn.execute(
                        f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
                        params,
                    )

            elif target_type == "curriculum_module":
                if payload.get("operation") == "restore":
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO curriculum_modules (id, title, description, level, order_num, is_published)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            payload["id"],
                            payload["title"],
                            payload["description"],
                            payload["level"],
                            payload["order_num"],
                            payload["is_published"],
                        ),
                    )

            elif target_type == "curriculum_lesson":
                if payload.get("operation") == "restore":
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO curriculum_lessons 
                        (id, module_id, title, letter_char, phonetic_guide, audio_url, cyrillic_equiv, old_latin_equiv, rules_content, quiz_data, order_num)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            payload["id"],
                            payload["module_id"],
                            payload["title"],
                            payload.get("letter_char"),
                            payload.get("phonetic_guide"),
                            payload.get("audio_url"),
                            payload.get("cyrillic_equiv"),
                            payload.get("old_latin_equiv"),
                            payload.get("rules_content"),
                            json.dumps(payload.get("quiz_data")) if payload.get("quiz_data") else None,
                            payload.get("order_num", 1),
                        ),
                    )

            # Mark log as rolled back
            conn.execute("UPDATE audit_logs SET is_rolled_back = 1 WHERE id = ?", (audit_id,))
            conn.commit()

            # Record a new audit log entry documenting this rollback
            AuditService.record_action(
                actor=rollback_actor,
                action="rollback_executed",
                target_type="audit_log",
                target_id=str(audit_id),
                details={
                    "original_action": row["action"],
                    "reverted_payload": payload,
                },
            )

            return {
                "success": True,
                "message": f"Action #{audit_id} successfully rolled back",
                "reverted_data": payload,
            }
        finally:
            conn.close()
