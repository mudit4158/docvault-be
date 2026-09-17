import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.services.tag_service import TagService
from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db

router = APIRouter(prefix="/tags", tags=["documents"])


@router.get("", response_model=list[str])
async def tag_suggestions(
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Suggested labels: the defaults plus labels the caller has used."""
    return await TagService(db).suggestions(account_id)
