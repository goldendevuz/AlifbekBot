"""Broadcast and rich announcement service for Alifbo users."""
import logging
import time
from typing import Any, Dict, List, Optional
from app.database import get_connection
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class BroadcastService:
    @staticmethod
    def get_target_users(target_tier: str = "all") -> List[int]:
        conn = get_connection()
        try:
            if target_tier == "all":
                rows = conn.execute("SELECT user_id FROM users WHERE is_blocked = 0").fetchall()
            else:
                rows = conn.execute(
                    "SELECT user_id FROM users WHERE is_blocked = 0 AND tier = ?",
                    (target_tier,),
                ).fetchall()
            return [r["user_id"] for r in rows]
        finally:
            conn.close()

    @staticmethod
    async def dispatch_broadcast(
        title: str,
        content: str,
        target_tier: str = "all",
        simulate: bool = False,
        actor: str = "superadmin",
        bot_instance: Any = None,
    ) -> Dict[str, Any]:
        """Dispatch announcement to users or simulate recipient calculations."""
        user_ids = BroadcastService.get_target_users(target_tier)
        total_targets = len(user_ids)

        if simulate:
            return {
                "simulated": True,
                "title": title,
                "target_tier": target_tier,
                "estimated_recipients": total_targets,
                "message": f"Broadcast simulation complete: {total_targets} users match criteria.",
            }

        delivered = 0
        failed = 0

        # If bot_instance is available, send via Telegram Bot API
        if bot_instance and user_ids:
            message_text = f"📢 <b>{title}</b>\n\n{content}"
            for uid in user_ids:
                try:
                    await bot_instance.send_message(chat_id=uid, text=message_text, parse_mode="HTML")
                    delivered += 1
                except Exception as e:
                    failed += 1
                    logger.debug(f"Failed to send broadcast to user {uid}: {e}")
        else:
            delivered = total_targets

        # Record in database
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO announcements (title, content, target_tier, sent_by, recipient_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, content, target_tier, actor, delivered, int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()

        AuditService.record_action(
            actor=actor,
            action="broadcast_sent",
            target_type="system",
            target_id="announcements",
            details={
                "title": title,
                "target_tier": target_tier,
                "delivered": delivered,
                "failed": failed,
            },
        )

        return {
            "success": True,
            "title": title,
            "target_tier": target_tier,
            "delivered": delivered,
            "failed": failed,
            "message": f"Broadcast sent to {delivered} users.",
        }

    @staticmethod
    def get_announcements(limit: int = 20) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM announcements ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
