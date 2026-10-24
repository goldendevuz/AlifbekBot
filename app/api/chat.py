"""Live chat concierge endpoints for Web and In-App visitors."""
from fastapi import APIRouter, HTTPException
from app.models import ChatMessageRequest, ChatMessageResponse
from app.services.concierge_service import ConciergeService

router = APIRouter(prefix="/api/chat", tags=["concierge"])


@router.post("/message", response_model=ChatMessageResponse)
async def send_chat_message(req: ChatMessageRequest):
    """Process incoming query via Alifbo AI Support Concierge with persistent memory."""
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Xabar bo'sh bo'lishi mumkin emas")

    res = await ConciergeService.generate_response(
        session_id=req.session_id,
        message=req.message.strip(),
        user_id=req.user_id,
        channel=req.channel,
    )
    return ChatMessageResponse(**res)


@router.get("/history/{session_id}")
async def get_history(session_id: str):
    """Retrieve dialogue turns for an active session."""
    history = ConciergeService.get_dialogue_history(session_id=session_id, limit=30)
    return {"session_id": session_id, "messages": history}
