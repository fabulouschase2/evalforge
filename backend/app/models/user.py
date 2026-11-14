"""User accounts, platform roles and role helpers.

Roles (v2 platform):
- super_admin        platform owner; sees everything, manages everything
- project_admin      administrates the projects they own / are admin members of
- project_manager    manages assigned projects (tasks, membership, monitoring)
- tester             completes/annotates tasks in projects they are members of
- reviewer           reviews submitted work in their projects
- senior_reviewer    quality lead; adjudication, monitoring, reports

Legacy roles from v1 (administrator / evaluator) are migrated in the database
by Alembic; constants below are the only values the application writes.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole:
    SUPER_ADMIN = "super_admin"
    PROJECT_ADMIN = "project_admin"
    PROJECT_MANAGER = "project_manager"
    TESTER = "tester"
    REVIEWER = "reviewer"
    SENIOR_REVIEWER = "senior_reviewer"
    # --- v3 client (external organization) roles; no internal capabilities ---
    CLIENT_OWNER = "client_owner"
    CLIENT_PROJECT_MANAGER = "client_project_manager"
    CLIENT_VIEWER = "client_viewer"

    ALL = [
        SUPER_ADMIN, PROJECT_ADMIN, PROJECT_MANAGER, TESTER, REVIEWER, SENIOR_REVIEWER,
        CLIENT_OWNER, CLIENT_PROJECT_MANAGER, CLIENT_VIEWER,
    ]

    # Roles that manage projects / data collection
    STAFF = [SUPER_ADMIN, PROJECT_ADMIN, PROJECT_MANAGER]
    # Roles that administrate the platform (users, settings, audit)
    ADMINISTRATORS = [SUPER_ADMIN, PROJECT_ADMIN]
    # Roles that perform task work
    WORKERS = [TESTER]
    # Roles that review submitted work
    REVIEWERS = [REVIEWER, SENIOR_REVIEWER, SUPER_ADMIN, PROJECT_ADMIN]
    # Roles that adjudicate disputes
    ADJUDICATORS = [SENIOR_REVIEWER, SUPER_ADMIN]
    # Roles with full platform visibility (quality leads monitor everything)
    PLATFORM_WIDE = [SUPER_ADMIN, SENIOR_REVIEWER]
    # External client organization roles (tenant-scoped, non-internal)
    CLIENT_ROLES = [CLIENT_OWNER, CLIENT_PROJECT_MANAGER, CLIENT_VIEWER]
    # Client roles that may author content (requests, uploads, messages)
    CLIENT_WRITE_ROLES = [CLIENT_OWNER, CLIENT_PROJECT_MANAGER]

    # v1 -> v2 mapping used by the Alembic data migration
    LEGACY_MAP = {
        "administrator": SUPER_ADMIN,
        "evaluator": TESTER,
        "reviewer": REVIEWER,
        "project_manager": PROJECT_MANAGER,
    }


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default=UserRole.TESTER, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def is_staff(self) -> bool:
        return self.role in UserRole.STAFF

    def is_platform_admin(self) -> bool:
        return self.role in UserRole.ADMINISTRATORS

    def can_review(self) -> bool:
        return self.role in UserRole.REVIEWERS

    def can_adjudicate(self) -> bool:
        return self.role in UserRole.ADJUDICATORS
