"""Auth routes: register, login, me. First registered user becomes administrator."""
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.core.security import (
    DbSession,
    CurrentUser,
    AdminOnly,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.dataset import Dataset
from app.models.rubric import Rubric
from app.models.evaluation import EvaluationRun
from app.models.review import ReviewAssignment
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.audit import log_action

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _bootstrap_role(db, email: str) -> str:
    """First user in an empty workspace becomes super admin; others join as testers."""
    has_users = db.scalar(select(func.count()).select_from(User)) or 0
    if has_users == 0:
        return UserRole.SUPER_ADMIN
    return UserRole.TESTER


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession, request: Request):
    from app.core.ratelimit import rate_limit
    rate_limit(request, "auth-register", max_events=10, window_seconds=300)
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    user = User(
        email=payload.email.lower(),
        name=payload.name.strip(),
        hashed_password=hash_password(payload.password),
        role=_bootstrap_role(db, payload.email.lower()),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(db, user_id=user.id, action="auth.register", entity_type="user", entity_id=user.id, request=request)
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession, request: Request):
    from app.core.config import settings as app_settings
    from app.core.ratelimit import rate_limit
    # 60/5min per IP: still throttles brute force (12 attempts/min) while
    # accommodating legitimate multi-user test suites and shared offices (V3.1).
    rate_limit(request, "auth-login", max_events=app_settings.login_rate_limit, window_seconds=300)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled.")
    log_action(db, user_id=user.id, action="auth.login", entity_type="user", entity_id=user.id, request=request)
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser, db: DbSession):
    return user


@router.get("/me/organizations")
def my_organizations(user: CurrentUser, db: DbSession):
    """Organizations the current user belongs to (client portal bootstrap)."""
    from sqlalchemy.orm import joinedload

    from app.models.organization import OrganizationMember

    memberships = db.scalars(
        select(OrganizationMember)
        .options(joinedload(OrganizationMember.organization))
        .where(OrganizationMember.user_id == user.id)
    ).unique().all()
    return [
        {
            "id": m.organization.id,
            "name": m.organization.name,
            "slug": m.organization.slug,
            "status": m.organization.status,
            "role": m.role,
        }
        for m in memberships
    ]


@router.get("/users")
def list_users(user: CurrentUser, db: DbSession):
    """Directory of active users — staff only (V3.1: client and worker accounts
    must not be able to enumerate the platform user list)."""
    if user.role not in UserRole.STAFF:
        raise HTTPException(status_code=403, detail="Staff access required.")
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    return [
        {"id": u.id, "email": u.email, "name": u.name, "role": u.role}
        for u in users
    ]


@router.put("/users/{user_id}/role")
def change_role(user_id: int, payload: dict, db: DbSession, admin: AdminOnly, request: Request):
    """Super admin changes a user's platform role. Every change is audited."""
    from app.services.audit import log_action
    role = (payload.get("role") or "").strip()
    if role not in UserRole.ALL:
        raise HTTPException(status_code=422, detail=f"Unknown role '{role}'. Allowed: {UserRole.ALL}")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    old_role = target.role
    if target.id == admin.id and role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=400, detail="A super admin cannot demote themselves.")
    target.role = role
    db.commit()
    log_action(db, user_id=admin.id, action="user.role_change", entity_type="user", entity_id=target.id,
               details={"from": old_role, "to": role}, request=request)
    return {"id": target.id, "role": target.role}


@router.put("/users/{user_id}/status")
def change_status(user_id: int, payload: dict, db: DbSession, admin: AdminOnly, request: Request):
    """Suspend or reactivate an account (suspension blocks login immediately)."""
    from app.services.audit import log_action
    is_active = payload.get("is_active")
    if not isinstance(is_active, bool):
        raise HTTPException(status_code=422, detail="is_active must be a boolean.")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == admin.id and not is_active:
        raise HTTPException(status_code=400, detail="A super admin cannot suspend themselves.")
    target.is_active = is_active
    db.commit()
    log_action(db, user_id=admin.id, action="user.status_change", entity_type="user", entity_id=target.id,
               details={"is_active": is_active}, request=request)
    return {"id": target.id, "is_active": target.is_active}


@router.post("/users")
def create_user(payload: dict, db: DbSession, admin: AdminOnly, request: Request):
    """Admin creates an account directly (invitation-less onboarding)."""
    from app.core.security import hash_password
    from app.services.audit import log_action
    email = (payload.get("email") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    password = payload.get("password") or ""
    role = (payload.get("role") or UserRole.TESTER).strip()
    if not email or not name or len(password) < 8:
        raise HTTPException(status_code=422, detail="email, name and a password of at least 8 characters are required.")
    if role not in UserRole.ALL:
        raise HTTPException(status_code=422, detail=f"Unknown role '{role}'.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, name=name, hashed_password=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(db, user_id=admin.id, action="user.created", entity_type="user", entity_id=user.id,
               details={"email": email, "role": role}, request=request)
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}
