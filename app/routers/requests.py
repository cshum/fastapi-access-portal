from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AccessRequest, Group, RequestStatus
from app.schemas import AccessRequestCreate, AccessRequestOut
from app.security import CurrentUser

router = APIRouter(prefix="/requests", tags=["access requests"])


@router.post("", response_model=AccessRequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: AccessRequestCreate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AccessRequest:
    """The self-service half: a member asks for a group, with a justification."""
    if db.get(Group, payload.group_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")

    duplicate = db.scalar(
        select(AccessRequest).where(
            AccessRequest.user_id == user.id,
            AccessRequest.group_id == payload.group_id,
            AccessRequest.status == RequestStatus.pending,
        )
    )
    if duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A pending request already exists for this group"
        )

    req = AccessRequest(
        user_id=user.id, group_id=payload.group_id, justification=payload.justification
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


@router.get("", response_model=list[AccessRequestOut])
def list_my_requests(
    user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> list[AccessRequest]:
    stmt = (
        select(AccessRequest)
        .where(AccessRequest.user_id == user.id)
        .order_by(AccessRequest.created_at.desc())
    )
    return list(db.scalars(stmt))
