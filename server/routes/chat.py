"""server/routes/chat.py — Chat route using Brain V2 pipeline."""
from fastapi import APIRouter, Depends
from utils.security import verify_token, rate_limit
from core.brain_v2 import brain

router = APIRouter(prefix="/stark", tags=["chat"])

@router.post("/chat", dependencies=[Depends(verify_token), Depends(rate_limit)])
def chat(body: dict):
    msg = body.get("message", "").strip()
    if not msg:
        return {"error": "No message provided"}
    return brain.process_dict(msg)
