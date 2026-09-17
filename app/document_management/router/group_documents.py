import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.schemas.share import GroupDocument
from app.document_management.services.share_service import ShareService
from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db

# Lives in document_management although the path starts /groups: the data is
# share grants and documents, which this module owns.
router = APIRouter(prefix="/groups", tags=["documents"])


@router.get("/{group_id}/documents", response_model=list[GroupDocument])
async def list_group_documents(
    group_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[GroupDocument]:
    """Documents shared into a group. Members only; others get 404."""
    return await ShareService(db).list_group_documents(group_id, account_id)
