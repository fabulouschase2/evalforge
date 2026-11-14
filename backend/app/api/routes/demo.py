"""Demo endpoint: loads the clearly labeled demonstration pipeline.

V3 security: restricted to staff — the demo seeds accounts with documented
passwords and must not be triggerable by workers or client users.
"""
from fastapi import APIRouter, HTTPException, Request

from app.core.security import AdminPM, DbSession
from app.services.audit import log_action
from app.services.demo import load_demo

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/load")
def load_demonstration_data(db: DbSession, user: AdminPM, request: Request):
    result = load_demo(db, user)
    log_action(db, user_id=user.id, action="demo.load", entity_type="evaluation", entity_id=result.get("evaluation_run_id"),
               details={
                   "note": "Demonstration pipeline loaded — clearly labeled, not production data.",
                   "dataset_id": result.get("dataset_id"),
                   "dataset_version_id": result.get("dataset_version_id"),
                   "rubric_version_id": result.get("rubric_version_id"),
                   "records": result.get("records"),
                   "flagged_for_review": result.get("flagged_for_review"),
                   "disagreement_items": result.get("disagreement_items"),
               }, request=request)
    return result
