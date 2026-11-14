"""Project access control — the single source of truth for who may touch what.

Platform roles decide capabilities; project membership decides visibility.
Super admins see everything. Project admins/managers see projects they own or
administer. Testers see projects they are tester members of (active only).
Reviewers see projects they are reviewer members of.

All decisions are made server-side from the database; client-provided roles or
project ids are never trusted.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.project import Project, ProjectMember
from app.models.user import User, UserRole


def _member_project_ids(db: Session, user_id: int, role: str) -> set[int]:
    rows = db.scalars(
        select(ProjectMember.project_id).where(
            ProjectMember.user_id == user_id, ProjectMember.role == role
        )
    ).all()
    return set(rows)


def visible_project_ids(db: Session, user: User) -> set[int] | None:
    """None means 'all projects' (platform-wide roles)."""
    if user.role in UserRole.PLATFORM_WIDE:
        return None
    if user.role in (UserRole.PROJECT_ADMIN, UserRole.PROJECT_MANAGER):
        owned = set(db.scalars(select(Project.id).where(Project.owner_id == user.id)).all())
        return owned | _member_project_ids(db, user.id, "admin")
    if user.role == UserRole.TESTER:
        return _member_project_ids(db, user.id, "tester")
    if user.role in (UserRole.REVIEWER, UserRole.SENIOR_REVIEWER):
        return _member_project_ids(db, user.id, "reviewer")
    if user.role in UserRole.CLIENT_ROLES:
        # v3 tenant isolation: client users see only projects of their orgs.
        from app.services.org_access import visible_project_ids_for_client
        return visible_project_ids_for_client(db, user)
    return set()


def can_access_project(db: Session, user: User, project: Project) -> bool:
    ids = visible_project_ids(db, user)
    return ids is None or project.id in ids


def require_project(db: Session, user: User, project_id: int) -> Project:
    """Load a project enforcing visibility. Raises PermissionError / LookupError."""
    project = db.scalars(
        select(Project).options(joinedload(Project.members)).where(Project.id == project_id)
    ).unique().one_or_none()
    if project is None:
        raise LookupError("Project not found.")
    if not can_access_project(db, user, project):
        raise PermissionError("You do not have access to this project.")
    return project


def require_project_admin(db: Session, user: User, project: Project) -> None:
    """Staff role on the platform AND admin of this specific project."""
    if user.role == UserRole.SUPER_ADMIN:
        return
    if user.role not in UserRole.STAFF:
        raise PermissionError("Staff role required.")
    if not project.is_admin_of(user.id):
        raise PermissionError("You do not administer this project.")


def is_project_tester(db: Session, user: User, project_id: int) -> bool:
    if user.role != UserRole.TESTER:
        return False
    return project_id in _member_project_ids(db, user.id, "tester")


def is_project_reviewer(db: Session, user: User, project_id: int) -> bool:
    if user.role not in (UserRole.REVIEWER, UserRole.SENIOR_REVIEWER):
        return False
    return project_id in _member_project_ids(db, user.id, "reviewer")


def project_reviewer_ids(db: Session, project_id: int) -> list[int]:
    """Reviewer-role members of a project (users with reviewer platform roles)."""
    members = db.scalars(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.role == "reviewer"
        )
    ).all()
    out = []
    for m in members:
        user = db.get(User, m.user_id)
        if user is not None and user.role in UserRole.REVIEWERS and user.is_active:
            out.append(user.id)
    return out


# --------------------------------------------------------------------------
# Dataset authorization (v3: shared by datasets.py and collection.py routes)
# --------------------------------------------------------------------------

class DatasetArchived(Exception):
    """Raised when a write targets an archived dataset (maps to HTTP 409)."""


def require_dataset_read(db: Session, user: User, dataset) -> None:
    """Read access to a dataset: visible project, or staff-only if projectless."""
    from app.models.dataset import Dataset  # local import to avoid cycles
    assert isinstance(dataset, Dataset)
    if dataset.project_id:
        try:
            require_project(db, user, dataset.project_id)
        except PermissionError:
            raise PermissionError("You do not have access to this dataset.")
    elif user.role not in UserRole.STAFF and user.role not in (
        UserRole.REVIEWER, UserRole.SENIOR_REVIEWER, UserRole.TESTER
    ):
        raise PermissionError("Datasets without a project are staff-only.")


def require_dataset_edit(db: Session, user: User, dataset, allow_archived: bool = False) -> None:
    """Modify a dataset: staff administering the project (super_admin if projectless)."""
    if not allow_archived and dataset.status == "archived":
        raise DatasetArchived("Dataset is archived and read-only. Restore it first.")
    if dataset.project_id:
        project = require_project(db, user, dataset.project_id)
        try:
            require_project_admin(db, user, project)
        except PermissionError:
            raise PermissionError("You do not administer this dataset's project.")
    elif user.role != UserRole.SUPER_ADMIN:
        raise PermissionError("Datasets without a project are managed by super admins only.")


def dataset_visibility(db: Session, user: User) -> dict:
    """Filter description for dataset list endpoints.

    {'all': True} — no filter (platform-wide roles).
    {'project_ids': set, 'include_projectless': bool} — otherwise.
    """
    if user.role in UserRole.PLATFORM_WIDE:
        return {"all": True}
    if user.role in UserRole.STAFF:
        return {"project_ids": visible_project_ids(db, user), "include_projectless": True}
    return {"project_ids": visible_project_ids(db, user), "include_projectless": False}
