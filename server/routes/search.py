"""Deep search and crypto benchmark endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from utils.security import verify_token

router = APIRouter(prefix="/stark", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    deep: bool = True
    fetch_pages: bool = True
    max_results: int = 6


class EncryptRequest(BaseModel):
    data: str           # plaintext
    passphrase: str
    algorithm: str = "aes-256-gcm"


@router.post("/search")
async def deep_search(req: SearchRequest, _=Depends(verify_token)):
    from core.deep_search import deep_search as do_search
    result = do_search(req.query, fetch_pages=req.fetch_pages, max_results=req.max_results)
    return {
        "query":      result.query,
        "answer":     result.answer,
        "citations":  result.citations,
        "timing_ms":  {"search": result.search_ms, "fetch": result.fetch_ms, "synth": result.synth_ms, "total": result.total_ms},
        "sources":    list(set(result.sources)),
    }


@router.get("/crypto/benchmark")
async def crypto_benchmark(_=Depends(verify_token)):
    from core.crypto import benchmark
    return benchmark(1.0)


@router.post("/crypto/encrypt")
async def encrypt_data(req: EncryptRequest, _=Depends(verify_token)):
    import base64
    from core.crypto import seal
    blob = seal(req.data.encode(), req.passphrase, algorithm=req.algorithm)
    return {"encrypted": base64.b64encode(blob).decode(), "algorithm": req.algorithm, "size_bytes": len(blob)}
