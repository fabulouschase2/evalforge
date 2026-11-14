"""Password hashing, JWT issuing/verification and auth dependencies."""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import get_db
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

ROLES = UserRole.ALL


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str | int, role: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {"sub": str(subject), "role": role, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise unauthorized
    user_id = payload.get("sub")
    if user_id is None:
        raise unauthorized
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]


class RoleChecker:
    """Dependency enforcing role-based authorization."""

    def __init__(self, allowed: list[str]) -> None:
        self.allowed = allowed

    def __call__(self, user: CurrentUser) -> User:
        if user.role not in self.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(self.allowed)}",
            )
        return user


def require_roles(*roles: str) -> RoleChecker:
    return RoleChecker(list(roles))


# Pre-built Annotated role dependencies for route signatures.
# AdminOnly       — platform administrators (users, settings, audit)
# AdminPM         — staff who manage projects, data and tasks
# AdminPMEvaluator— staff allowed to author datasets/rubrics and run evaluations
#                   (kept for v1 router compatibility; tester is a worker role)
# OrgAdmin        — super_admin / project_admin (organization administration)
AdminOnly = Annotated[User, Depends(RoleChecker([UserRole.SUPER_ADMIN]))]
AdminPM = Annotated[User, Depends(RoleChecker(list(UserRole.STAFF)))]
AdminPMEvaluator = Annotated[User, Depends(RoleChecker(list(UserRole.STAFF)))]
OrgAdmin = Annotated[User, Depends(RoleChecker(list(UserRole.ADMINISTRATORS)))]


def user_exists(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))
