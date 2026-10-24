"""Administrative REST API routes for Alifbo Admin Suite."""
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from app.api.auth import AdminUser, LoginRequest, generate_token, get_current_admin, require_role, ADMIN_PASSWORD
from app.database import get_connection
from app.models import (
    AuditLogItem,
    BroadcastRequest,
    LessonItem,
    MetricOverview,
    ModuleItem,
    PurchaseActionRequest,
    QuotaAdjustRequest,
    RollbackRequest,
    TicketUpdateRequest,
    UserStatusToggleRequest,
    UserTierUpdateRequest,
)
from app.services.audit_service import AuditService
from app.services.broadcast_service import BroadcastService
from app.services.concierge_service import ConciergeService
from app.services.curriculum_service import CurriculumService
from app.services.purchase_service import PurchaseService
from app.services.quota_service import QuotaService

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/auth/login")
async def login(req: LoginRequest, response: Response):
    """Authenticate administrator and return signed session token."""
    expected_password = os.getenv("ADMIN_PASSWORD", "alifbo2026")
    if req.password != expected_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Noto'g'ri admin paroli",
        )

    role = "superadmin" if req.username in ["admin", "superadmin"] else "moderator"
    token = generate_token(username=req.username, role=role)
    response.set_cookie(
        key="alifbo_admin_token",
        value=token,
        httponly=True,
        max_age=7 * 86400,
        samesite="lax",
    )
    return {
        "success": True,
        "token": token,
        "username": req.username,
        "role": role,
    }


@router.get("/auth/me")
async def get_me(admin: AdminUser = Depends(get_current_admin)):
    return {"username": admin.username, "role": admin.role}


@router.get("/metrics")
async def get_metrics(admin: AdminUser = Depends(get_current_admin)):
    """Executive Dashboard Real-Time Metrics."""
    conn = get_connection()
    try:
        now = int(time.time())
        one_day_ago = now - 86400
        seven_days_ago = now - 7 * 86400

        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        # In case users table is just growing, include distinct users from events too
        total_event_users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM events").fetchone()[0]
        total_unique_users = max(total_users, total_event_users)

        daily_active = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE ts > ?", (one_day_ago,)
        ).fetchone()[0]

        total_conversions = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        total_chars = conn.execute("SELECT COALESCE(SUM(chars), 0) FROM events").fetchone()[0]

        # Tier breakdown
        tier_counts = {"free": 0, "student": 0, "pro": 0, "business": 0}
        tier_rows = conn.execute("SELECT tier, COUNT(*) as cnt FROM users GROUP BY tier").fetchall()
        for r in tier_rows:
            if r["tier"] in tier_counts:
                tier_counts[r["tier"]] = r["cnt"]

        # Calculate estimated monthly recurring revenue (MRR) based on real tiers
        mrr = (
            tier_counts["free"] * 0
            + tier_counts["student"] * 12000
            + tier_counts["pro"] * 25000
            + tier_counts["business"] * 75000
        )

        pending_tickets = conn.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE status = 'open'"
        ).fetchone()[0]

        pending_orders = conn.execute(
            "SELECT COUNT(*) FROM purchase_requests WHERE status = 'pending'"
        ).fetchone()[0]

        # Recent conversion activity for real-time chart (last 7 days grouped by date)
        chart_data = []
        for i in range(6, -1, -1):
            day_start = now - (i + 1) * 86400
            day_end = now - i * 86400
            day_count = conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts >= ? AND ts < ?", (day_start, day_end)
            ).fetchone()[0]
            day_label = time.strftime("%d-%b", time.localtime(day_end))
            chart_data.append({"date": day_label, "conversions": day_count})

        return {
            "total_users": total_unique_users,
            "daily_active_learners": daily_active,
            "total_conversions": total_conversions,
            "total_chars_converted": total_chars,
            "active_subscriptions": tier_counts,
            "monthly_revenue_uzs": mrr,
            "pending_support_tickets": pending_tickets,
            "pending_purchase_orders": pending_orders,
            "system_status": "operational",
            "activity_chart": chart_data,
        }
    finally:
        conn.close()


@router.get("/users")
async def list_users(
    search: Optional[str] = None,
    tier: Optional[str] = None,
    role: Optional[str] = None,
    is_blocked: Optional[bool] = None,
    limit: int = Query(50, le=100),
    offset: int = 0,
    admin: AdminUser = Depends(get_current_admin),
):
    users, total = QuotaService.list_users(
        search=search, tier=tier, role=role, is_blocked=is_blocked, limit=limit, offset=offset
    )
    return {"users": users, "total": total, "limit": limit, "offset": offset}


@router.post("/users/quota")
async def adjust_quota(
    req: QuotaAdjustRequest,
    admin: AdminUser = Depends(require_role(["superadmin", "moderator"])),
):
    """Adjust user characters quota with quick chips or custom balance."""
    try:
        res = QuotaService.adjust_credits(
            user_id=req.user_id,
            delta=req.delta,
            action_type=req.action_type,
            actor=admin.username,
            reason=req.reason or "Admin adjustment",
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/users/tier")
async def update_tier(
    req: UserTierUpdateRequest,
    admin: AdminUser = Depends(require_role(["superadmin", "moderator"])),
):
    """Upgrade or downgrade user tier with quota synchronization."""
    try:
        res = QuotaService.set_tier(
            user_id=req.user_id,
            tier=req.tier,
            actor=admin.username,
            reason=req.reason or "Admin tier modification",
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/users/status")
async def toggle_status(
    req: UserStatusToggleRequest,
    admin: AdminUser = Depends(require_role(["superadmin", "moderator"])),
):
    """Toggle user active / blocked status."""
    try:
        res = QuotaService.toggle_status(
            user_id=req.user_id,
            is_blocked=req.is_blocked,
            actor=admin.username,
            reason=req.reason or "Status changed by admin",
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/curriculum")
async def get_curriculum(admin: AdminUser = Depends(get_current_admin)):
    """Fetch complete curriculum modules and letter lessons."""
    modules = CurriculumService.get_curriculum()
    return {"modules": modules}


@router.post("/curriculum/module")
async def save_module(
    req: Dict[str, Any],
    admin: AdminUser = Depends(require_role(["superadmin", "moderator"])),
):
    res = CurriculumService.save_module(
        module_id=req["id"],
        title=req["title"],
        description=req.get("description", ""),
        level=req.get("level", "beginner"),
        order_num=int(req.get("order_num", 1)),
        is_published=bool(req.get("is_published", True)),
        actor=admin.username,
    )
    return res


@router.post("/curriculum/lesson")
async def save_lesson(
    req: Dict[str, Any],
    admin: AdminUser = Depends(require_role(["superadmin", "moderator"])),
):
    res = CurriculumService.save_lesson(
        lesson_id=req["id"],
        module_id=req["module_id"],
        title=req["title"],
        letter_char=req.get("letter_char"),
        phonetic_guide=req.get("phonetic_guide"),
        audio_url=req.get("audio_url"),
        cyrillic_equiv=req.get("cyrillic_equiv"),
        old_latin_equiv=req.get("old_latin_equiv"),
        rules_content=req.get("rules_content"),
        quiz_data=req.get("quiz_data"),
        order_num=int(req.get("order_num", 1)),
        actor=admin.username,
    )
    return res


@router.delete("/curriculum/lesson/{lesson_id}")
async def delete_lesson(
    lesson_id: str,
    admin: AdminUser = Depends(require_role(["superadmin"])),
):
    ok = CurriculumService.delete_lesson(lesson_id=lesson_id, actor=admin.username)
    if not ok:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return {"success": True, "message": "Lesson deleted (audit logged)"}


@router.get("/audit")
async def get_audit_logs(
    limit: int = Query(50, le=100),
    offset: int = 0,
    admin: AdminUser = Depends(get_current_admin),
):
    logs = AuditService.get_logs(limit=limit, offset=offset)
    return {"logs": logs}


@router.post("/audit/rollback")
async def rollback_action(
    req: RollbackRequest,
    admin: AdminUser = Depends(require_role(["superadmin"])),
):
    """Execute 1-Click Rollback on audited operation."""
    try:
        res = AuditService.rollback(audit_id=req.audit_id, rollback_actor=admin.username)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tickets")
async def list_tickets(
    status_filter: Optional[str] = "all",
    admin: AdminUser = Depends(get_current_admin),
):
    tickets = ConciergeService.get_tickets(status_filter=status_filter)
    return {"tickets": tickets}


@router.post("/tickets/update")
async def update_ticket(
    req: TicketUpdateRequest,
    admin: AdminUser = Depends(get_current_admin),
):
    ok = ConciergeService.update_ticket(
        ticket_id=req.ticket_id,
        status=req.status,
        assigned_to=req.assigned_to or admin.username,
    )
    return {"success": ok, "message": f"Ticket #{req.ticket_id} status updated to {req.status}"}


@router.post("/broadcast")
async def send_broadcast(
    req: BroadcastRequest,
    admin: AdminUser = Depends(require_role(["superadmin", "moderator"])),
):
    # Retrieve bot instance if imported
    from bot import bot as active_bot
    res = await BroadcastService.dispatch_broadcast(
        title=req.title,
        content=req.content,
        target_tier=req.target_tier,
        simulate=req.simulate,
        actor=admin.username,
        bot_instance=active_bot,
    )
    return res


@router.get("/tiers")
async def get_tiers():
    """Public list of Alifbo tiers and features."""
    tiers = QuotaService.get_tiers()
    return {"tiers": tiers}


@router.get("/orders")
async def list_orders(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    admin: AdminUser = Depends(get_current_admin),
):
    """List purchase requests with optional status filter."""
    orders, total = PurchaseService.list_requests(status=status, limit=limit, offset=offset)
    return {"orders": orders, "total": total, "limit": limit, "offset": offset}


@router.post("/orders/{order_id}/approve")
async def approve_order(
    order_id: int,
    admin: AdminUser = Depends(require_role(["superadmin", "moderator"])),
):
    """Approve a purchase request and update user tier."""
    try:
        res = PurchaseService.approve_request(order_id, actor=admin.username)
        # Notify user on Telegram asynchronously
        from bot import bot as active_bot
        try:
            await active_bot.send_message(
                chat_id=res["user_id"],
                text=(
                    f"🎉 <b>Tabriklaymiz! Sizning xarid so'rovingiz tasdiqlandi!</b>\n\n"
                    f"🆔 Buyurtma: <b>#ORD-{order_id}</b>\n"
                    f"📦 Yangi tarif: <b>{res.get('tier_name', 'Faol')}</b>\n"
                    f"Endi siz kengaytirilgan limitlar va barcha imkoniyatlardan to'liq foydalanishingiz mumkin!\n\n"
                    f"Alifbo platformasidan foydalanganingiz uchun rahmat! /start"
                ),
            )
        except Exception:
            pass
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/orders/{order_id}/reject")
async def reject_order(
    order_id: int,
    req: PurchaseActionRequest,
    admin: AdminUser = Depends(require_role(["superadmin", "moderator"])),
):
    """Reject a purchase request."""
    try:
        res = PurchaseService.reject_request(order_id, actor=admin.username, reason=req.reason or "Rad etildi")
        from bot import bot as active_bot
        try:
            await active_bot.send_message(
                chat_id=res["user_id"],
                text=(
                    f"ℹ️ <b>Buyurtma holati</b>\n\n"
                    f"Sizning <b>#ORD-{order_id}</b> raqamli xarid so'rovingiz rad etildi.\n"
                    f"Sabab: <i>{req.reason or 'Ma’muriyat tomonidan rad etildi'}</i>\n\n"
                    f"Batafsil ma'lumot yoki boshqa to'lov turi uchun: /support"
                ),
            )
        except Exception:
            pass
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

