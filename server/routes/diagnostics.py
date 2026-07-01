from fastapi import APIRouter, Depends
from utils.security import verify_token
from utils.diagnostics import full_diagnostic

router = APIRouter(prefix="/stark", tags=["diagnostics"])

@router.get("/diagnostics", dependencies=[Depends(verify_token)])
def diagnostics():
    return full_diagnostic()
