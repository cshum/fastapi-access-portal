from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Role, User

# `tokenUrl` is only used to point Swagger UI at the login endpoint.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode(), hashed.encode())


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Dependencies can depend on other dependencies, and FastAPI resolves the
    graph per request. This one composes the token scheme with the DB session."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise invalid
    email = payload.get("sub")
    if not email:
        raise invalid
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise invalid
    return user


# An annotated alias: this is the idiomatic way to avoid repeating Depends(...)
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_approver(user: CurrentUser) -> User:
    """Authorisation as a dependency. Same shape as a NestJS CanActivate guard,
    but it composes into the type signature of the endpoint."""
    if user.role is not Role.approver:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Approver role required"
        )
    return user


ApproverUser = Annotated[User, Depends(require_approver)]
