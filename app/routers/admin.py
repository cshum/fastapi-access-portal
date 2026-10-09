from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AccessRequest, Group, Membership, RequestStatus
from app.schemas import AccessRequestOut, GroupCreate, GroupOut, MembershipOut
from app.security import ApproverUser, CurrentUser

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: GroupCreate, _: ApproverUser, db: Annotated[Session, Depends(get_db)]
) -> Group:
    if db.scalar(select(Group).where(Group.name == payload.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Group already exists")
    group = Group(name=payload.name, description=payload.description)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get("/groups", response_model=list[GroupOut])
def list_groups(_: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[Group]:
    return list(db.scalars(select(Group).order_by(Group.name)))


@router.get("/requests", response_model=list[AccessRequestOut])
def all_requests(
    _: ApproverUser,
    db: Annotated[Session, Depends(get_db)],
    status_filter: RequestStatus | None = None,
) -> list[AccessRequest]:
    stmt = select(AccessRequest).order_by(AccessRequest.created_at)
    if status_filter is not None:
        stmt = stmt.where(AccessRequest.status == status_filter)
    return list(db.scalars(stmt))


def _decide(
    request_id: int, approver_id: int, decision: RequestStatus, db: Session
) -> AccessRequest:
    req = db.get(AccessRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if req.status is not RequestStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Request already decided")

    req.status = decision
    req.decided_by_id = approver_id
    req.decided_at = datetime.now(timezone.utc)

    # Approving grants the group. The unique constraint plus this check make the
    # whole thing idempotent — re-approving can never create a second row.
    if decision is RequestStatus.approved:
        existing = db.scalar(
            select(Membership).where(
                Membership.user_id == req.user_id, Membership.group_id == req.group_id
            )
        )
        if existing is None:
            db.add(Membership(user_id=req.user_id, group_id=req.group_id))

    db.commit()
    db.refresh(req)
    return req


@router.post("/requests/{request_id}/approve", response_model=AccessRequestOut)
def approve(
    request_id: int, approver: ApproverUser, db: Annotated[Session, Depends(get_db)]
) -> AccessRequest:
    return _decide(request_id, approver.id, RequestStatus.approved, db)


@router.post("/requests/{request_id}/reject", response_model=AccessRequestOut)
def reject(
    request_id: int, approver: ApproverUser, db: Annotated[Session, Depends(get_db)]
) -> AccessRequest:
    return _decide(request_id, approver.id, RequestStatus.rejected, db)


@router.get("/users/{user_id}/memberships", response_model=list[MembershipOut])
def user_memberships(
    user_id: int, _: ApproverUser, db: Annotated[Session, Depends(get_db)]
) -> list[Membership]:
    return list(db.scalars(select(Membership).where(Membership.user_id == user_id)))
