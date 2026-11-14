"""Pydantic request/response schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: str
    created_at: datetime


# ---------- Client portal (V3) ----------
class ProjectRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    category: str = "custom_evaluation"
    evaluation_types: list[str] | None = None
    expected_task_volume: int | None = Field(default=None, ge=0)
    required_languages: list[str] | None = None
    required_skills: list[str] | None = None
    dataset_availability: str | None = Field(default=None, max_length=30)
    expected_delivery: datetime | None = None
    quality_requirements: str | None = None
    special_instructions: str | None = None


# ---------- Projects ----------
class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    contact_email: EmailStr | None = None
    settings: dict | None = None
    owner_email: EmailStr | None = Field(
        default=None, description="Optional: attach this existing user as client_owner."
    )


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    contact_email: EmailStr | None = None
    settings: dict | None = None
    status: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: int | None = Field(default=None, description="legacy alias field, ignored")
    organization_id: int | None = None
    client: str | None = None
    project_type: str | None = None
    instructions: str | None = None
    required_skills: list[str] | None = None
    supported_languages: list[str] | None = None
    start_date: datetime | None = None
    deadline: datetime | None = None
    status: str | None = None
    quality_requirements: str | None = None
    target_task_volume: int | None = Field(default=None, ge=0)
    blind_review: bool | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    owner_id: int | None
    created_at: datetime


# ---------- Datasets ----------
class RecordOut(BaseModel):
    record_id: str
    prompt: str
    response: str
    reference_answer: str | None = None
    reference_sources: list[Any] = []
    expected_label: str | None = None
    gold_explanation: str | None = None
    metadata: dict[str, Any] = {}


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: int | None = None


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int | None
    name: str
    description: str | None
    format: str
    source_filename: str | None
    current_version: int
    is_demo: bool
    status: str = "active"
    created_by: int | None
    created_at: datetime


class ImportPreviewRequest(BaseModel):
    column_mapping: dict[str, str] | None = Field(
        default=None,
        description="Maps canonical fields -> source columns, e.g. {'prompt': 'question'}",
    )
    record_id_column: str | None = None
    expected_label_column: str | None = None


class ImportCommitRequest(BaseModel):
    column_mapping: dict[str, str] | None = None
    record_id_column: str | None = None
    expected_label_column: str | None = None
    notes: str | None = None
    create_new_version: bool = False


class ImportReport(BaseModel):
    format: str
    total_rows: int
    valid_count: int
    invalid_count: int
    duplicate_count: int
    missing_value_count: int
    detected_columns: list[str]
    missing_required_fields: list[str]
    invalid_records: list[dict[str, Any]]
    duplicate_records: list[dict[str, Any]]
    warnings: list[str]
    preview: list[RecordOut]


class DatasetVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version_number: int
    record_count: int
    content_hash: str | None
    notes: str | None
    created_at: datetime


# ---------- Rubrics ----------
class RubricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: int | None = None
    definition: dict[str, Any]


class RubricUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict[str, Any] | None = None


class RubricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int | None
    name: str
    description: str | None
    current_version: int
    is_demo: bool
    created_by: int | None
    created_at: datetime


class RubricVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rubric_id: int
    version_number: int
    definition: dict[str, Any]
    created_at: datetime


class ValidationIssue(BaseModel):
    level: str  # error | warning
    path: str
    message: str


class RubricValidationResponse(BaseModel):
    valid: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]


# ---------- Evaluations ----------
class EvaluationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dataset_id: int
    dataset_version_id: int | None = None
    rubric_id: int
    rubric_version_id: int | None = None
    config: dict[str, Any] | None = None


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    dataset_id: int
    dataset_version_id: int
    rubric_id: int
    rubric_version_id: int
    status: str
    config: dict[str, Any] | None
    total_records: int
    passed_count: int
    failed_count: int
    borderline_count: int
    needs_review_count: int
    avg_score: float | None
    error: str | None
    is_demo: bool
    created_by: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: str
    rule_name: str
    check_type: str
    criterion_id: str | None
    input_excerpt: str | None
    output: str | None
    passed: bool | None
    uncertain: bool
    evidence: str | None
    explanation: str | None
    severity: str
    evaluator_version: str
    rubric_version: int
    executed_at: datetime


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    dataset_record_id: int
    record_id: str
    status: str
    automated_label: str
    gold_label: str | None
    score: float
    confidence: float
    borderline_category: str | None
    needs_review: bool
    criterion_scores: dict[str, Any] | None
    factuality: dict[str, Any] | None
    summary: dict[str, Any] | None
    created_at: datetime


class ResultDetailOut(ResultOut):
    findings: list[FindingOut] = []


# ---------- Reviews ----------
class CriterionScoreIn(BaseModel):
    criterion_id: str
    score: float
    comment: str | None = None


class ReviewSubmitRequest(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    criterion_scores: list[CriterionScoreIn] = []
    reasoning: str | None = None
    evidence: str | None = None
    uncertain: bool = False


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    result_id: int
    reviewer_id: int
    status: str
    blind: bool
    created_at: datetime
    submitted_at: datetime | None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    assignment_id: int
    result_id: int
    reviewer_id: int
    criterion_scores: dict[str, Any] | None
    label: str
    reasoning: str | None
    evidence: str | None
    uncertain: bool
    agrees_with_automated: bool | None
    submitted_at: datetime


class AssignReviewersRequest(BaseModel):
    reviewer_ids: list[int] = Field(min_length=1)
    result_ids: list[int] | None = None


class AdjudicateRequest(BaseModel):
    final_label: str = Field(min_length=1, max_length=50)
    final_criterion_scores: list[CriterionScoreIn] = []
    rationale: str = Field(min_length=1)


# ---------- Analytics ----------
class ConfusionMatrixOut(BaseModel):
    labels: list[str]
    matrix: list[list[int]]
    gold_total: int


class MetricsOut(BaseModel):
    run_id: int | None = None
    gold_labeled_count: int
    accuracy: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    cohen_kappa: float | None = None
    insufficient_reason: str | None = None
    confusion_matrix: ConfusionMatrixOut | None = None
    pass_rate: float | None = None
    avg_score: float | None = None
    borderline_rate: float | None = None
    failure_categories: dict[str, int] = {}


class AgreementOut(BaseModel):
    reviewer_count: int
    items_with_multiple_reviews: int
    full_agreement_items: int
    raw_agreement_rate: float | None
    fleiss_kappa: float | None
    disagreement_items: int
    reviewer_agreement_with_automated: dict[str, Any]
    note: str | None = None


class OverviewOut(BaseModel):
    total_records: int
    completed_runs: int
    active_runs: int
    automated_pass_rate: float | None
    failed_count: int
    borderline_count: int
    review_queue_size: int
    reviewer_agreement: float | None
    recent_runs: list[EvaluationOut] = []
    failure_categories: dict[str, int] = {}
    trend: list[dict[str, Any]] = []
    dataset_count: int
    rubric_count: int


# ---------- Audit / Settings ----------
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any] | None
    ip: str | None
    created_at: datetime


class PaginatedOut(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


class SettingsOut(BaseModel):
    review_blind_by_default: bool = True
    reviewers_per_result: int = 2
    borderline_confidence_below: float = 0.6
    borderline_score_margin: float = 0.08
    auto_assign_reviews_on_borderline: bool = True
    max_upload_mb: int = 25


class SettingsUpdate(BaseModel):
    review_blind_by_default: bool | None = None
    reviewers_per_result: int | None = Field(default=None, ge=1, le=5)
    borderline_confidence_below: float | None = Field(default=None, ge=0, le=1)
    borderline_score_margin: float | None = Field(default=None, ge=0, le=0.5)
    auto_assign_reviews_on_borderline: bool | None = None
    max_upload_mb: int | None = Field(default=None, ge=1, le=200)


TokenResponse.model_rebuild()
