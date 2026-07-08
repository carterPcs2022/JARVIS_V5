from fastapi import APIRouter, Depends
from utils.security import verify_token
from core.memory import memory_stats, get_short_term, clear_short_term, get_all_facts, get_profile

router = APIRouter(prefix="/stark/memory", tags=["memory"])

@router.get("/stats", dependencies=[Depends(verify_token)])
def stats():
    return memory_stats()

@router.get("/recent", dependencies=[Depends(verify_token)])
def recent(n: int = 10):
    return get_short_term(n)

@router.get("/facts", dependencies=[Depends(verify_token)])
def facts(n: int = 200):
    """Added for FRIDAY's training sync (services/friday_training.py on
    her side) — read-only, same auth as every other memory endpoint here."""
    return {"facts": get_all_facts(n)}

@router.get("/profile", dependencies=[Depends(verify_token)])
def profile():
    return get_profile()

@router.delete("/short-term", dependencies=[Depends(verify_token)])
def clear():
    clear_short_term()
    return {"status": "short-term memory cleared"}
