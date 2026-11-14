// API entity types mirroring the FastAPI schemas.

export interface User {
  id: number;
  email: string;
  name: string;
  role: string;
  is_active?: boolean;
  created_at?: string;
}

export interface Project {
  id: number;
  name: string;
  description: string | null;
  owner_id: number | null;
  created_at: string;
}

export interface Dataset {
  id: number;
  project_id: number | null;
  name: string;
  description: string | null;
  format: string;
  source_filename: string | null;
  current_version: number;
  is_demo: boolean;
  status?: "active" | "archived";
  custom_field_definitions?: { key: string; label: string; type: string; required?: boolean; options?: string[] }[] | null;
  created_by: number | null;
  created_at: string;
}

export interface DatasetVersion {
  id: number;
  dataset_id: number;
  version_number: number;
  record_count: number;
  content_hash: string | null;
  notes: string | null;
  created_at: string;
}

export interface DatasetRecord {
  id?: number;
  record_id: string;
  prompt: string;
  response: string;
  reference_answer: string | null;
  reference_sources: unknown[];
  expected_label: string | null;
  gold_explanation?: string | null;
  metadata: Record<string, unknown>;
  errors?: string[];
  // v2 collection extension
  supporting_evidence?: string | null;
  source_url?: string | null;
  content_category?: string | null;
  difficulty_level?: string | null;
  language?: string | null;
  instructions?: string | null;
  collection_status?: string | null;
  custom_fields?: Record<string, unknown>;
  version_id?: number;
}

export interface ImportReport {
  format: string;
  total_rows: number;
  valid_count: number;
  invalid_count: number;
  duplicate_count: number;
  missing_value_count: number;
  detected_columns: string[];
  missing_required_fields: string[];
  invalid_records: { row: number; record_id: string; errors: string[] }[];
  duplicate_records: { row: number; record_id: string; reason: string }[];
  warnings: string[];
  preview: DatasetRecord[];
}

export interface CheckDefinition {
  type: string;
  name?: string;
  rule_id?: string;
  severity?: string;
  params?: Record<string, unknown>;
}

export interface CriterionDefinition {
  id: string;
  name: string;
  description?: string;
  weight: number;
  scoring_scale: { type: "binary" | "likert"; min?: number; max?: number; labels?: Record<string, string> };
  pass_threshold: number;
  checks: CheckDefinition[];
  human_review_required?: boolean;
  expected_evidence?: string | null;
}

export interface RubricDefinition {
  name: string;
  description?: string;
  criteria: CriterionDefinition[];
  passing_threshold: number;
  borderline_rules?: {
    confidence_below?: number;
    score_margin?: number;
    categories_enabled?: string[];
  };
  human_review_policy?: {
    when_borderline?: boolean;
    when_failed?: boolean;
    sample_failed_pct?: number;
  };
  examples?: { prompt: string; response: string; expected_outcome: string }[];
  expected_evidence?: string | null;
  borderline_conditions?: string | null;
  form?: { fields: FormField[] };
}

export interface Rubric {
  id: number;
  project_id: number | null;
  name: string;
  description: string | null;
  current_version: number;
  is_demo: boolean;
  created_by: number | null;
  created_at: string;
}

export interface RubricVersion {
  id: number;
  rubric_id: number;
  version_number: number;
  definition: RubricDefinition;
  created_at: string;
}

export interface ValidationIssue {
  level: string;
  path: string;
  message: string;
}

export interface EvaluationRun {
  id: number;
  name: string;
  dataset_id: number;
  dataset_version_id: number;
  rubric_id: number;
  rubric_version_id: number;
  status: "pending" | "running" | "completed" | "failed";
  total_records: number;
  passed_count: number;
  failed_count: number;
  borderline_count: number;
  needs_review_count: number;
  avg_score: number | null;
  error: string | null;
  is_demo: boolean;
  created_by: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface CriterionScore {
  criterion_id: string;
  name: string;
  weight: number;
  score: number;
  raw_score: number;
  scale: { min: number; max: number };
  passed: boolean;
}

export interface EvaluationResult {
  id: number;
  run_id: number;
  dataset_record_id: number;
  record_id: string;
  status: "pass" | "fail" | "borderline";
  automated_label: string;
  gold_label: string | null;
  score: number;
  confidence: number;
  borderline_category: string | null;
  needs_review: boolean;
  criterion_scores: { criteria: CriterionScore[] } | null;
  factuality: { verdict: string; counts?: Record<string, number>; note?: string } | null;
  summary: {
    borderline_explanation?: string | null;
    confidence_reasons?: string[];
    findings_passed?: number;
    findings_failed?: number;
    findings_inconclusive?: number;
  } | null;
  created_at: string;
}

export interface Finding {
  id: number;
  rule_id: string;
  rule_name: string;
  check_type: string;
  criterion_id: string | null;
  passed: boolean | null;
  uncertain: boolean;
  evidence: string | null;
  explanation: string | null;
  severity: string;
  evaluator_version: string;
  rubric_version: number;
  executed_at: string;
}

export interface ReviewAssignment {
  id: number;
  result_id: number;
  reviewer_id: number;
  status: "pending" | "submitted";
  blind: boolean;
  created_at: string;
  submitted_at: string | null;
}

export interface Review {
  id: number;
  assignment_id: number;
  result_id: number;
  reviewer_id: number;
  criterion_scores: Record<string, { score: number; comment?: string }>;
  label: string;
  reasoning: string | null;
  evidence: string | null;
  uncertain: boolean;
  agrees_with_automated: boolean | null;
  submitted_at: string;
}

export interface ReviewWorkspace {
  assignment: ReviewAssignment;
  result: EvaluationResult & { gold_label: string | null };
  record: DatasetRecord;
  run: { id: number; name: string; rubric_id: number; rubric_version_id: number } | null;
  findings: Finding[];
  visible_reviews: Review[];
  own_review_submitted: boolean;
  own_review: Review | null;
  adjudication: Adjudication | null;
}

export interface Adjudication {
  id: number;
  final_label: string;
  rationale: string;
  final_criterion_scores: Record<string, unknown>;
  review_ids: number[];
  created_at: string;
}

export interface QueueItem {
  assignment: ReviewAssignment;
  result_id: number;
  record_id: string;
  run_id: number;
  run_name: string | null;
  automated_status: string;
  automated_label: string;
  borderline_category: string | null;
  prompt_excerpt: string | null;
}

export interface Overview {
  total_records: number;
  completed_runs: number;
  active_runs: number;
  automated_pass_rate: number | null;
  failed_count: number;
  borderline_count: number;
  review_queue_size: number;
  reviewer_agreement: number | null;
  recent_runs: EvaluationRun[];
  failure_categories: Record<string, number>;
  trend: { run_id: number; name: string; created_at: string; pass_rate: number | null; borderline_rate: number | null; avg_score: number | null }[];
  dataset_count: number;
  rubric_count: number;
}

export interface Metrics {
  run_id: number | null;
  gold_labeled_count: number;
  accuracy: number | null;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  cohen_kappa: number | null;
  kappa_note?: string;
  insufficient_reason: string | null;
  confusion_matrix: { labels: string[]; matrix: number[][] } | null;
  pass_rate: number | null;
  avg_score: number | null;
  borderline_rate: number | null;
  failure_categories: Record<string, number>;
}

export interface Agreement {
  reviewer_count: number;
  items_with_multiple_reviews: number;
  full_agreement_items: number;
  raw_agreement_rate: number | null;
  fleiss_kappa: number | null;
  disagreement_items: number;
  reviewer_agreement_with_automated: Record<string, { total: number; agree: number }>;
  note: string | null;
}

export interface AuditLog {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, unknown> | null;
  ip: string | null;
  created_at: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface AppSettings {
  review_blind_by_default: boolean;
  reviewers_per_result: number;
  borderline_confidence_below: number;
  borderline_score_margin: number;
  auto_assign_reviews_on_borderline: boolean;
  max_upload_mb: number;
}

export const BORDERLINE_CATEGORIES: Record<string, string> = {
  partially_correct: "Partially correct",
  evidence_insufficient: "Evidence insufficient",
  context_misleading: "Context misleading",
  ambiguous_instruction: "Ambiguous instruction",
  conflicting_evidence: "Conflicting evidence",
  reviewer_disagreement: "Reviewer disagreement",
  uncertain_automated_decision: "Uncertain automated decision",
};

export const CHECK_TYPES = [
  "format_regex", "json_valid", "min_words", "max_words", "min_chars", "max_chars",
  "sentence_count", "required_keywords", "forbidden_patterns", "required_fields",
  "completeness", "evidence_citation", "numeric_match", "reference_overlap",
];

// ---------- v2 platform types ----------

export interface Organization {
  id: number;
  name: string;
  description: string | null;
}

export interface ProjectMember {
  id: number;
  user_id: number;
  role: "admin" | "tester" | "reviewer";
  name: string;
  email: string;
  platform_role: string;
  added_at: string;
}

export interface ProjectDetail extends Project {
  organization_id: number | null;
  organization_name: string | null;
  client: string | null;
  project_type: string;
  status: string;
  instructions: string | null;
  required_skills: string[];
  supported_languages: string[];
  start_date: string | null;
  deadline: string | null;
  quality_requirements: string | null;
  target_task_volume: number | null;
  blind_review: boolean;
  is_admin: boolean;
  is_demo?: boolean;
  member_count: number;
  dataset_count: number;
  task_count: number;
}

export interface TaskRecord {
  id: number;
  record_id: string;
  prompt: string;
  response: string;
  reference_answer: string | null;
  reference_sources: unknown[];
  supporting_evidence?: string | null;
  source_url?: string | null;
  content_category?: string | null;
  language?: string;
  custom_fields: Record<string, unknown>;
}

export interface PlatformTask {
  id: number;
  project_id: number;
  project_name?: string | null;
  title: string;
  task_type: string;
  instructions: string | null;
  status: string;
  priority: string;
  difficulty: string;
  estimated_minutes: number | null;
  deadline: string | null;
  max_attempts: number;
  attempt_count: number;
  rubric_id: number | null;
  rubric_version_id: number | null;
  assigned_tester_id: number | null;
  assigned_tester_name?: string | null;
  claimed_at: string | null;
  assignment_expires_at: string | null;
  created_at: string;
  record?: TaskRecord;
  record_id?: string;
  has_record?: boolean;
  assignment_history?: { user_id: number; action: string; assigned_at: string; released_at: string | null }[];
}

export interface FormField {
  id: string;
  type: "yes_no" | "single_select" | "multi_select" | "numeric" | "likert" | "text" | "evidence";
  label: string;
  required?: boolean;
  options?: string[];
  scale?: { min: number; max: number };
  help?: string;
  conditional_on?: { field_id: string; values: unknown[] };
}

export interface SubmissionSummary {
  id: number;
  task_id: number;
  project_id: number;
  attempt_number: number;
  status: string;
  payload: Record<string, unknown>;
  label: string | null;
  explanation: string | null;
  evidence: { kind: string; value: string; note?: string }[];
  rubric_version_id: number | null;
  time_spent_seconds: number | null;
  submitted_at: string;
  decided_at: string | null;
  task_title: string | null;
  tester_id: number | null;
  tester_name: string | null;
  project_name: string | null;
  blind_review?: boolean;
  reviews?: SubmissionReviewItem[];
  adjudication?: { id: number; final_decision: string; rationale: string; created_at: string } | null;
  task_record?: TaskRecord | null;
  rubric_definition?: RubricDefinition | null;
}

export interface SubmissionReviewItem {
  id: number;
  decision: string;
  comments: string | null;
  corrected_labels: Record<string, unknown> | null;
  flagged_suspicious: boolean;
  ambiguous: boolean;
  escalated: boolean;
  reviewer_id: number;
  reviewer_name: string | null;
  created_at: string;
}

export interface TaskWorkspace {
  task: {
    id: number;
    title: string;
    task_type: string;
    instructions: string | null;
    status: string;
    priority: string;
    difficulty: string;
    estimated_minutes: number | null;
    deadline: string | null;
    attempt_count: number;
    max_attempts: number;
    claimed_at: string | null;
    project_name: string | null;
    blind_review: boolean;
  };
  record: TaskRecord | null;
  form_fields: FormField[];
  rubric_definition: RubricDefinition | null;
  draft_payload: Record<string, unknown> | null;
  draft_updated_at: string | null;
  submissions: { id: number; attempt_number: number; status: string; submitted_at: string; payload: Record<string, unknown> }[];
  feedback: { submission_id: number; attempt: number; decision: string; comments: string | null; reviewer_name: string | null; created_at: string }[];
  can_submit: boolean;
}

export interface NotificationItem {
  id: number;
  type: string;
  title: string;
  body: string | null;
  entity_type: string | null;
  entity_id: string | null;
  read: boolean;
  created_at: string;
}

export interface AdminOverview {
  total_projects: number;
  active_projects: number;
  total_datasets: number;
  total_records: number;
  task_total: number;
  tasks_by_status: Record<string, number>;
  avg_completion_hours: number | null;
  completion_samples: number;
  tester_performance: { tester_id: number; name: string; submitted: number; approved: number; rejected: number; revision_required: number; approval_rate: number | null }[];
  reviewer_performance: { reviewer_id: number; name: string; reviews: number; approved: number; rejected: number; revision_requested: number }[];
  overall_quality_score: number | null;
  decided_submissions: number;
  daily_submissions: { day: string; count: number }[];
  project_progress: { project_id: number; name: string; total_tasks: number; approved: number }[];
}

export interface QualityOverview {
  total_submissions: number;
  escalated: number;
  flagged_suspicious: number;
  ambiguous_reviews: number;
  multi_review_items: number;
  disagreement_items: number;
  disagreement_rate: number | null;
  pending_adjudications: number;
}

export interface AdjudicationQueueItem {
  id: number;
  task_id: number;
  project_id: number;
  project_name: string | null;
  task_title: string | null;
  attempt_number: number;
  status: string;
  label: string | null;
  explanation: string | null;
  escalated: boolean;
  flagged_suspicious: boolean;
  submitted_at: string;
  tester_name: string | null;
  decision_counts: Record<string, number>;
}

export interface ReviewerConsistency {
  reviewers: {
    reviewer_id: number;
    name: string;
    total_reviews: number;
    decisions: Record<string, number>;
    escalations: number;
    ambiguous_flags: number;
    compared_to_adjudication: number;
    matches_adjudication: number | null;
  }[];
  note: string;
}

export interface TesterQuality {
  testers: {
    tester_id: number;
    name: string;
    submitted: number;
    approved: number;
    rejected: number;
    revision_required: number;
    resubmissions: number;
    approval_rate: number | null;
    recent_feedback: { submission_id: number; decision: string; comments: string }[];
  }[];
}

export interface AgreementAnalysis {
  items_with_multiple_reviews: number;
  full_agreement_items: number;
  raw_agreement_rate: number | null;
  fleiss_kappa: number | null;
  decision_labels: string[];
  note: string;
}
