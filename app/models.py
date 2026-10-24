"""Pydantic data models for Alifbo Admin Suite & Support Concierge."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# User & Quota Models
class UserSummary(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    role: str = "user"
    tier: str = "free"
    credits_balance: int = 20000
    unlimited_quota: bool = False
    is_blocked: bool = False
    created_at: int
    last_active_at: Optional[int] = None
    conversions_count: int = 0
    total_chars_processed: int = 0


class QuotaAdjustRequest(BaseModel):
    user_id: int
    delta: int = Field(..., description="Amount of characters to add or subtract, or special value")
    action_type: str = Field("add", description="'add', 'subtract', 'set', 'unlimited'")
    reason: Optional[str] = "Manual admin adjustment"


class UserTierUpdateRequest(BaseModel):
    user_id: int
    tier: str = Field(..., description="'free', 'student', 'pro', 'business'")
    reason: Optional[str] = "Admin tier upgrade/downgrade"


class UserStatusToggleRequest(BaseModel):
    user_id: int
    is_blocked: bool
    reason: Optional[str] = "Status modified by administrator"


# Curriculum & Content Models
class LessonItem(BaseModel):
    id: str
    module_id: str
    title: str
    letter_char: Optional[str] = None
    phonetic_guide: Optional[str] = None
    audio_url: Optional[str] = None
    cyrillic_equiv: Optional[str] = None
    old_latin_equiv: Optional[str] = None
    rules_content: Optional[str] = None
    quiz_data: Optional[Dict[str, Any]] = None
    order_num: int = 1


class ModuleItem(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    level: str = "beginner"
    order_num: int = 1
    is_published: bool = True
    lessons: List[LessonItem] = []


# Support Concierge Models
class ChatMessageRequest(BaseModel):
    session_id: str
    message: str
    user_id: Optional[int] = None
    channel: str = "web"  # 'web' or 'telegram'


class ChatMessageResponse(BaseModel):
    response: str
    session_id: str
    is_escalated: bool = False
    ticket_id: Optional[int] = None
    escalation_reason: Optional[str] = None


class TicketUpdateRequest(BaseModel):
    ticket_id: int
    status: str = Field(..., description="'open', 'in_progress', 'resolved', 'closed'")
    assigned_to: Optional[str] = None
    notes: Optional[str] = None


# Audit Trail & Rollback Models
class AuditLogItem(BaseModel):
    id: int
    actor: str
    action: str
    target_type: str
    target_id: str
    details: Optional[Dict[str, Any]] = None
    rollback_payload: Optional[Dict[str, Any]] = None
    is_rolled_back: bool = False
    created_at: int


class RollbackRequest(BaseModel):
    audit_id: int
    reason: Optional[str] = "1-Click Administrator Rollback"


# Announcement & Broadcast Models
class BroadcastRequest(BaseModel):
    title: str
    content: str
    target_tier: str = "all"  # 'all', 'free', 'student', 'pro', 'business'
    simulate: bool = False


# Dashboard Executive Metrics
class MetricOverview(BaseModel):
    total_users: int
    daily_active_learners: int
    total_conversions: int
    total_chars_converted: int
    active_subscriptions: Dict[str, int]
    monthly_revenue_uzs: int
    pending_support_tickets: int
    system_status: str = "operational"


# Purchase Requests Models
class PurchaseRequestItem(BaseModel):
    id: int
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    tier_id: str
    tier_name: str
    price_uzs: int
    status: str = "pending"
    handled_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: int
    updated_at: int


class PurchaseActionRequest(BaseModel):
    reason: Optional[str] = None
