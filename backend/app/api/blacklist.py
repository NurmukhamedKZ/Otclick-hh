from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.schemas.blacklist import BlacklistCreate, BlacklistResponse
from app.services import blacklist as blacklist_service

router = APIRouter(prefix="/api/blacklist", tags=["blacklist"])


@router.get("", response_model=list[BlacklistResponse])
async def list_all(user_id: str = Depends(get_current_user)):
    rows = await blacklist_service.list_blacklist(user_id)
    return [BlacklistResponse(**r) for r in rows]


@router.post("", response_model=BlacklistResponse, status_code=status.HTTP_201_CREATED)
async def create(
    body: BlacklistCreate,
    user_id: str = Depends(get_current_user),
):
    row = await blacklist_service.add_blacklist(
        user_id,
        employer_id=body.employer_id,
        employer_name=body.employer_name,
        reason=body.reason or "manual",
    )
    return BlacklistResponse(**row)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(entry_id: str, user_id: str = Depends(get_current_user)):
    await blacklist_service.remove_blacklist(user_id, entry_id)
