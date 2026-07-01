"""Protocol 17 scatter/reassemble endpoints."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from utils.security import verify_token

router = APIRouter(prefix="/stark/scatter", tags=["scatter"])


class ScatterRequest(BaseModel):
    passphrase: str


class ReassembleRequest(BaseModel):
    passphrase: str


@router.post("")
async def scatter(req: ScatterRequest, _=Depends(verify_token)):
    from core.scatter import get_engine
    result = get_engine().scatter(req.passphrase)
    if not result["ok"]:
        raise HTTPException(503, detail=result.get("error", "Scatter failed"))
    return result


@router.get("/status")
async def scatter_status(_=Depends(verify_token)):
    from core.scatter import get_engine
    return get_engine().status()


@router.post("/reassemble")
async def reassemble(req: ReassembleRequest, _=Depends(verify_token)):
    from core.scatter import get_engine
    result = get_engine().reassemble(req.passphrase)
    if not result["ok"]:
        raise HTTPException(400, detail=result.get("error", "Reassembly failed"))
    return result


@router.get("/nodes")
async def list_nodes(_=Depends(verify_token)):
    from services.scatter_nodes import get_nodes
    nodes = get_nodes()
    return {"nodes": [{"name": n.name, "available": n.available()} for n in nodes]}
