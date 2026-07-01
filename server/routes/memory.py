from fastapi import APIRouter, Depends
from utils.security import verify_token
from core.memory import memory_stats, get_short_term, clear_short_term

router = APIRouter(prefix="/stark/memory", tags=["memory"])

@router.get("/stats", dependencies=[Depends(verify_token)])
def stats():
    return memory_stats()

@router.get("/recent", dependencies=[Depends(verify_token)])
def recent(n: int = 10):
    return get_short_term(n)

@router.delete("/short-term", dependencies=[Depends(verify_token)])
def clear():
    clear_short_term()
    return {"status": "short-term memory cleared"}
