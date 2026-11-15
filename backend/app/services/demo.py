"""Demonstration data: clearly labeled example dataset + rubric + full pipeline seed.

Everything created here is marked is_demo / named with "[DEMO]" and is never
presented as production data. The demo exercises every borderline category and
includes planted reviewer disagreement to show adjudication.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.engine.runner import run_evaluation
from app.models.dataset import Dataset, DatasetRecord, DatasetVersion
from app.models.evaluation import EvaluationResult, EvaluationRun
from app.models.project import Project
from app.models.review import HumanReview, ReviewAssignment
from app.models.rubric import Rubric, RubricVersion
from app.models.user import User
from app.services.datasets import commit_import
from app.services.reviews import create_assignments, submit_review, reviews_disagree
from app.services.audit import log_action

logger = logging.getLogger("evalforge.demo")

DEMO_RUBRIC_DEFINITION = {
    "name": "Support Response Quality",
    "description": (
        "Demonstration rubric for customer-support responses. Combines deterministic "
        "formatting checks with reference-based factuality signals. All demo content is "
        "clearly labeled demonstration data, not production measurements."
    ),
    "criteria": [
        {
            "id": "format_compliance",
            "name": "Format & completeness",
            "description": "Response must be complete, non-truncated, reasonably sized and include an apology-free professional tone marker.",
            "weight": 0.25,
            "scoring_scale": {"type": "binary", "min": 0, "max": 1},
            "pass_threshold": 1,
            "checks": [
                {"type": "completeness", "name": "Completeness", "rule_id": "fmt.completeness", "params": {}},
                {"type": "max_words", "name": "Conciseness", "rule_id": "fmt.max_words", "params": {"max": 350}},
                {"type": "min_words", "name": "Substance", "rule_id": "fmt.min_words", "params": {"min": 8}},
            ],
        },
        {
            "id": "factual_accuracy",
            "name": "Factual accuracy (reference-based)",
            "description": "Lexical/numeric agreement with the reference answer. Heuristic signal — not semantic proof.",
            "weight": 0.45,
            "scoring_scale": {"type": "likert", "min": 0, "max": 2},
            "pass_threshold": 1,
            "checks": [
                {"type": "reference_overlap", "name": "Reference overlap", "rule_id": "fact.overlap", "params": {"support_threshold": 0.45}},
                {"type": "numeric_match", "name": "Numeric consistency", "rule_id": "fact.numeric", "params": {"tolerance": 0.01}},
            ],
        },
        {
            "id": "evidence_citation",
            "name": "Evidence citation",
            "description": "When reference sources are provided, the response must cite at least one of them ([n] markers or source names).",
            "weight": 0.30,
            "scoring_scale": {"type": "binary", "min": 0, "max": 1},
            "pass_threshold": 1,
            "checks": [
                {"type": "evidence_citation", "name": "Citations present", "rule_id": "evd.citation", "params": {"min_citations": 1}},
            ],
        },
    ],
    "passing_threshold": 0.68,
    "borderline_rules": {
        "confidence_below": 0.6,
        "score_margin": 0.1,
        "categories_enabled": [
            "partially_correct", "evidence_insufficient", "context_misleading",
            "ambiguous_instruction", "conflicting_evidence", "uncertain_automated_decision",
        ],
    },
    "human_review_policy": {"when_borderline": True, "when_failed": False, "sample_failed_pct": 0},
    "examples": [
        {
            "prompt": "How long do I have to request a refund?",
            "response": "Our policy allows refund requests within 30 days of purchase [1]. After that window, only store credit applies.",
            "expected_outcome": "pass — matches reference, cites source",
        },
        {
            "prompt": "What is the return shipping fee?",
            "response": "Return shipping is free for all customers, always.",
            "expected_outcome": "fail — contradicts reference fee ($6.99), no citation",
        },
    ],
    "expected_evidence": "Refund window, fees and policy numbers must match reference material and cite the policy source.",
    "borderline_conditions": (
        "Responses passing structural checks without reference material, numeric near-misses, "
        "or hedged factual claims are routed to human review instead of being auto-classified."
    ),
}

_DEMO_ROWS = [
    # 1 clearly correct
    {"record_id": "demo_001", "prompt": "How long do I have to request a refund after purchase?",
     "response": "You can request a refund within 30 days of purchase under our standard policy [1]. After 30 days, only store credit is available.",
     "reference_answer": "Refund requests are accepted within 30 days of purchase. After 30 days, only store credit is offered.",
     "reference_sources": ["Customer Refund Policy v4.2"],
     "expected_label": "pass", "gold_explanation": "Matches reference window and cites the policy source."},
    # 2 clearly incorrect
    {"record_id": "demo_002", "prompt": "How long do I have to request a refund after purchase?",
     "response": "You have a full 90 days to request a refund on any purchase, no questions asked [1].",
     "reference_answer": "Refund requests are accepted within 30 days of purchase. After 30 days, only store credit is offered.",
     "reference_sources": ["Customer Refund Policy v4.2"],
     "expected_label": "fail", "gold_explanation": "States a 90-day window; policy says 30 days. Direct numeric/policy contradiction."},
    # 3 partially correct
    {"record_id": "demo_003", "prompt": "Is there a fee to return an item by mail?",
     "response": "Yes, returns by mail include a small processing fee of 20% of the item price, deducted from your refund [1]. Return shipping itself is $6.99.",
     "reference_answer": "Returns by mail carry a 10% restocking fee deducted from the refund. Return shipping costs $6.99 unless the item is defective.",
     "reference_sources": ["Customer Refund Policy v4.2"],
     "expected_label": "borderline", "gold_explanation": "Return shipping is correct but the restocking fee is wrong (20% vs 10%): partially correct."},
    # 4 evidence-thin
    {"record_id": "demo_004", "prompt": "Which payment methods do you accept for international orders?",
     "response": "We accept all major payment methods for international orders, and everything works smoothly at checkout [1].",
     "reference_answer": "International orders accept Visa, Mastercard, American Express and PayPal. Bank transfer is available for orders over $500.",
     "reference_sources": ["International Checkout Guide 2025"],
     "expected_label": "borderline", "gold_explanation": "No specific methods listed; vague claims with no reference support despite citing a source."},
    # 5 context misleading (cites source but misstates it)
    {"record_id": "demo_005", "prompt": "Do you price-match competitors?",
     "response": "Yes — we guarantee to price-match any competitor, including marketplace sellers, at any time [2]. Just email us the link.",
     "reference_answer": "We price-match identical items from major authorized retailers within 14 days of purchase. Marketplace sellers and auction sites are excluded.",
     "reference_sources": ["Customer Refund Policy v4.2", "Price Match Guarantee Terms"],
     "expected_label": "fail", "gold_explanation": "Misstates the guarantee: marketplace sellers are explicitly excluded in [2]."},
    # 6 ambiguous instruction
    {"record_id": "demo_006", "prompt": "Tell me about shipping options or whatever makes sense for my order, thanks.",
     "response": "Our standard shipping takes 3-5 business days ($4.99), and express shipping arrives in 1-2 business days ($14.99) [1]. If you tell me your country I can narrow this down, since international delivery times differ.",
     "reference_answer": "Standard shipping is 3-5 business days at $4.99. Express is 1-2 business days at $14.99. International shipping varies by destination.",
     "reference_sources": ["Shipping Overview 2025"],
     "expected_label": "borderline", "gold_explanation": "Response is accurate; instruction itself was ambiguous. Human should confirm it addresses intent."},
    # 7 conflicting evidence
    {"record_id": "demo_007", "prompt": "What are your support hours?",
     "response": "Support is available 24/7 by chat and phone [1]. Email replies take up to 10 business days.",
     "reference_answer": "Chat support runs 24/7. Phone support is 8am-8pm ET on weekdays. Email replies take up to 2 business days.",
     "reference_sources": ["Support Center FAQ"],
     "expected_label": "fail", "gold_explanation": "Phone availability and email SLA both contradict the reference FAQ."},
    # 8 numeric correct
    {"record_id": "demo_008", "prompt": "How much is express shipping to a domestic address?",
     "response": "Express domestic shipping costs $14.99 and arrives within 1-2 business days [1].",
     "reference_answer": "Express shipping costs $14.99 for domestic addresses, delivered in 1-2 business days.",
     "reference_sources": ["Shipping Overview 2025"],
     "expected_label": "pass", "gold_explanation": "Exact numeric match with reference and cited source."},
    # 9 numeric incorrect
    {"record_id": "demo_009", "prompt": "How much is standard shipping to a domestic address?",
     "response": "Standard domestic shipping is $9.99 and typically takes 3-5 business days [1].",
     "reference_answer": "Standard shipping costs $4.99 and takes 3-5 business days for domestic addresses.",
     "reference_sources": ["Shipping Overview 2025"],
     "expected_label": "fail", "gold_explanation": "Shipping cost is wrong: $9.99 stated vs $4.99 in reference."},
    # 10 incomplete / truncated
    {"record_id": "demo_010", "prompt": "Can I change my subscription plan mid-cycle and what happens to my billing?",
     "response": "Yes, you can change plans at any time from Account Settings. When you upgrade...",
     "reference_answer": "Upgrades apply immediately with a prorated charge. Downgrades take effect at the next billing cycle. Mid-cycle changes never generate refunds.",
     "reference_sources": ["Subscription Billing FAQ"],
     "expected_label": "fail", "gold_explanation": "Response is truncated mid-sentence and never addresses billing behavior."},
    # 11 valid JSON required style
    {"record_id": "demo_011", "prompt": "List the payment methods for international orders as JSON with a 'methods' key.",
     "response": '{"methods": ["Visa", "Mastercard", "American Express", "PayPal"], "bank_transfer_min": 500}',
     "reference_answer": "International orders accept Visa, Mastercard, American Express and PayPal. Bank transfer is available for orders over $500.",
     "reference_sources": ["International Checkout Guide 2025"],
     "expected_label": "pass", "gold_explanation": "Valid JSON with required key; methods match reference exactly."},
    # 12 invalid JSON
    {"record_id": "demo_012", "prompt": "List the payment methods for international orders as JSON with a 'methods' key.",
     "response": "{'methods': [Visa, Mastercard, PayPal}",
     "reference_answer": "International orders accept Visa, Mastercard, American Express and PayPal. Bank transfer is available for orders over $500.",
     "reference_sources": ["International Checkout Guide 2025"],
     "expected_label": "fail", "gold_explanation": "Single quotes and unterminated array: invalid JSON, missing Amex."},
    # 13 verbose but correct content
    {"record_id": "demo_013", "prompt": "What is your warranty on electronics?",
     "response": (
         "Thank you for reaching out about warranties, we really appreciate customers like you and we want to make sure every "
         "question you have ever gets answered thoroughly and completely, so let me begin at the very beginning of our warranty "
         "story which starts with our founding team deciding in the early days of the company that customer trust was going to be "
         "the cornerstone of everything we build. Electronics carry a 24-month limited warranty covering manufacturing defects "
         "but not accidental damage [1]. The warranty starts on the date of purchase shown on your receipt and it transfers with "
         "the device if you sell it as noted in the warranty document which is available on our website in the legal section where "
         "you can also download the PDF and read about exclusions, claim steps, repair timelines, and service center addresses, "
         "and if you ever have questions our support team is happy to walk you through the process step by step at any time of day "
         "or night because we are here for you always and we truly mean that from the bottom of our hearts."
     ),
     "reference_answer": "Electronics carry a 24-month limited warranty covering manufacturing defects. Accidental damage is not covered. Warranty starts on purchase date and transfers with the device.",
     "reference_sources": ["Warranty Terms Electronics"],
     "expected_label": "borderline", "gold_explanation": "Factually correct and cited, but extremely verbose (word-limit violation). Human should weigh format vs accuracy."},
    # 14 no reference material
    {"record_id": "demo_014", "prompt": "Do you offer gift wrapping at checkout?",
     "response": "Yes, gift wrapping is available at checkout for a small fee, and you can add a personalized note before payment.",
     "reference_answer": None,
     "reference_sources": [],
     "expected_label": "pass", "gold_explanation": "Plausible but unverifiable: no reference material exists for this fact. Do not treat as confirmed."},
    # 15 hedged claims
    {"record_id": "demo_015", "prompt": "Will my order arrive before Christmas if I order today?",
     "response": "It might possibly arrive before Christmas if you order today, probably — delivery times seem to be around 4-6 days at the moment [1].",
     "reference_answer": "Standard delivery takes 3-5 business days. Orders placed by December 18 typically arrive before December 24, but carriers cannot guarantee holiday dates.",
     "reference_sources": ["Shipping Overview 2025"],
     "expected_label": "borderline", "gold_explanation": "Heavily hedged; delivery estimate is slower than reference. Needs human verification."},
    # 16 correct with citations
    {"record_id": "demo_016", "prompt": "What happens if my item arrives damaged?",
     "response": "Report the damage within 48 hours of delivery with photos; we ship a replacement or refund your order in full, and return shipping is free for damaged items [1].",
     "reference_answer": "Damaged items must be reported within 48 hours with photos. Customers receive a free replacement or full refund; return shipping for damaged goods is free.",
     "reference_sources": ["Customer Refund Policy v4.2"],
     "expected_label": "pass", "gold_explanation": "Matches reference procedure exactly and cites the policy."},
    # 17 no reference + actually wrong (system cannot know)
    {"record_id": "demo_017", "prompt": "Can I use two discount codes on one order?",
     "response": "Yes, you can stack up to three discount codes per order at checkout [1].",
     "reference_answer": None,
     "reference_sources": [],
     "expected_label": "fail", "gold_explanation": "Actually false (only one code allowed), but no reference exists — the system must NOT auto-classify; human review required."},
    # 18 correct, short
    {"record_id": "demo_018", "prompt": "Where can I download an invoice for my order?",
     "response": "You can download invoices from Account → Order History → Invoice PDF [1].",
     "reference_answer": "Invoices are available under Account, then Order History, using the Invoice PDF link.",
     "reference_sources": ["Account & Billing Help"],
     "expected_label": "pass", "gold_explanation": "Matches reference instructions with citation."},
]


def _demo_rows_with_meta() -> list[dict]:
    rows = []
    case_names = [
        "clearly_correct", "clearly_incorrect", "partially_correct", "evidence_thin",
        "context_misleading", "ambiguous_instruction", "conflicting_evidence",
        "numeric_correct", "numeric_incorrect", "incomplete_truncated",
        "json_valid", "json_invalid", "verbose_correct", "no_reference_unverifiable",
        "hedged_claims", "correct_with_citation", "no_reference_actually_wrong", "correct_short",
    ]
    for row, case in zip(_DEMO_ROWS, case_names):
        r = dict(row)
        r["metadata"] = {"demo_case": case, "source": "EvalForge demonstration dataset"}
        rows.append(r)
    return rows


def create_demo_users(db: Session) -> tuple[list[User], str]:
    """Two demo reviewers used for independent reviews.

    V3.1: the password is RANDOM per seed run — printed once to the server
    console and returned to the calling staff member. It is never hardcoded,
    documented, or predictable, so a forgotten demo instance cannot be
    compromised from documentation alone.
    """
    import secrets

    password = "Demo-" + secrets.token_urlsafe(12)
    users = []
    for name, email in (("Demo Reviewer One", "reviewer.one@evalforge.demo"),
                        ("Demo Reviewer Two", "reviewer.two@evalforge.demo")):
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name, hashed_password=hash_password(password), role="reviewer")
            db.add(user)
            users.append(user)
        else:
            # refresh the password so the printed credential always works
            user.hashed_password = hash_password(password)
            db.add(user)
    db.commit()
    for u in users:
        db.refresh(u)
    logger.warning(
        "DEMO reviewers seeded/updated. One-time credentials (not stored in docs): "
        "reviewer.one@evalforge.demo / reviewer.two@evalforge.demo -> %s", password,
    )
    return users, password


def load_demo(db: Session, for_user: User) -> dict:
    """Seed the complete demonstration pipeline (idempotent-ish: skips if present)."""
    marker = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- Project ---------------------------------------------------------
    project = db.scalar(select(Project).where(Project.name == "EvalForge Demonstration [DEMO]"))
    if project is None:
        project = Project(name="EvalForge Demonstration [DEMO]",
                          description=f"Demonstration project created {marker}. NOT production data.",
                          owner_id=for_user.id)
        db.add(project)
        db.flush()
        from app.models.project import ProjectMember
        # the loader gets membership matching their platform role so they can
        # always see the demo data under the v2 isolation model
        member_role = "admin" if for_user.role in ("super_admin", "project_admin", "project_manager") \
            else ("reviewer" if for_user.role in ("reviewer", "senior_reviewer") else "tester")
        db.add(ProjectMember(project_id=project.id, user_id=for_user.id, role=member_role, added_by=for_user.id))
        db.commit()
        db.refresh(project)

    # --- Dataset + records ------------------------------------------------
    dataset = db.scalar(select(Dataset).where(Dataset.name == "Support Response Quality — Demonstration [DEMO]"))
    if dataset is None:
        dataset = Dataset(
            project_id=project.id, name="Support Response Quality — Demonstration [DEMO]",
            description="Clearly labeled demonstration dataset: correct, incorrect, partial, ambiguous and evidence-thin AI responses with gold labels.",
            format="json", created_by=for_user.id, is_demo=True,
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        rows = _demo_rows_with_meta()
        version, report = commit_import(db, dataset, rows, notes=f"Demonstration seed {marker}", fmt="json", source_filename="demo_dataset.json")
    else:
        version = db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset.id).order_by(
            DatasetVersion.version_number.desc()).first()
        report = None

    # --- Rubric -----------------------------------------------------------
    rubric = db.scalar(select(Rubric).where(Rubric.name == "Support Response Quality [DEMO]"))
    if rubric is None:
        rubric = Rubric(project_id=project.id, name="Support Response Quality [DEMO]",
                        description=DEMO_RUBRIC_DEFINITION["description"], created_by=for_user.id, is_demo=True)
        db.add(rubric)
        db.flush()
        db.add(RubricVersion(rubric_id=rubric.id, version_number=1, definition=DEMO_RUBRIC_DEFINITION, created_by=for_user.id))
        db.commit()
        db.refresh(rubric)
    rubric_version = db.query(RubricVersion).filter(RubricVersion.rubric_id == rubric.id).order_by(
        RubricVersion.version_number.desc()).first()

    # --- Evaluation run -----------------------------------------------------
    run = db.scalar(select(EvaluationRun).where(
        EvaluationRun.dataset_id == dataset.id, EvaluationRun.rubric_id == rubric.id, EvaluationRun.is_demo.is_(True)))
    if run is None:
        run = EvaluationRun(
            name="Demonstration Run 1 [DEMO]",
            dataset_id=dataset.id, dataset_version_id=version.id,
            rubric_id=rubric.id, rubric_version_id=rubric_version.id,
            created_by=for_user.id, is_demo=True, config={"trigger": "demo_seed"},
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_evaluation(db, run, list(db.scalars(select(DatasetRecord).where(DatasetRecord.dataset_version_id == version.id)).all()), rubric_version.definition)
        log_action(db, user_id=for_user.id, action="demo.load", entity_type="evaluation", entity_id=run.id,
                   details={"note": "Demonstration data loaded — clearly labeled, not production metrics."})
    else:
        # ensure results exist even if the run row survived but execution didn't finish
        if run.status != "completed":
            run_evaluation(db, run, list(db.scalars(select(DatasetRecord).where(DatasetRecord.dataset_version_id == version.id)).all()), rubric_version.definition)

    # --- Review assignments + planted independent reviews --------------------
    reviewers, demo_reviewer_password = create_demo_users(db)
    flagged = list(db.scalars(select(EvaluationResult).where(
        EvaluationResult.run_id == run.id, EvaluationResult.needs_review.is_(True))).all())

    existing_assignments = db.scalar(
        select(func.count())
        .select_from(ReviewAssignment).where(ReviewAssignment.result_id.in_([r.id for r in flagged] or [0]))
    ) or 0

    if existing_assignments == 0 and flagged:
        for reviewer in reviewers:
            create_assignments(db, [r.id for r in flagged], [reviewer.id], assigned_by=for_user.id, blind=True)

        # Planted reviews: reviewers agree on most items, disagree on two, and two
        # items stay pending so the demo reviewer queue has real work to do.
        leave_pending = {"demo_011", "demo_014"}
        disagree_map = {}
        for result in flagged:
            if result.record_id in ("demo_013", "demo_017"):
                disagree_map[result.id] = result.record_id

        r1, r2 = reviewers[0], reviewers[1]
        for result in flagged:
            if result.record_id in leave_pending:
                continue
            a1 = db.scalar(select(ReviewAssignment).where(
                ReviewAssignment.result_id == result.id, ReviewAssignment.reviewer_id == r1.id))
            a2 = db.scalar(select(ReviewAssignment).where(
                ReviewAssignment.result_id == result.id, ReviewAssignment.reviewer_id == r2.id))
            record = db.get(DatasetRecord, result.dataset_record_id)
            case = (record.record_metadata or {}).get("demo_case", "") if record else ""

            if result.id in disagree_map:
                label1, label2 = ("pass", "fail") if result.record_id == "demo_013" else ("fail", "pass")
            else:
                label1 = label2 = "pass" if result.status != "fail" else "fail"

            for assignment, label, reviewer in ((a1, label1, r1), (a2, label2, r2)):
                if assignment is None:
                    continue
                submit_review(db, assignment, {
                    "label": label,
                    "criterion_scores": [],
                    "reasoning": (
                        f"[Demonstration review by {reviewer.name}] Agreed with the automated finding for the "
                        f"'{case}' demonstration case." if label1 == label2 else
                        f"[Demonstration review by {reviewer.name}] I reach a different conclusion than the other "
                        f"reviewer on this '{case}' case: I judge the response '{label}'."
                    ),
                    "evidence": None,
                    "uncertain": case in ("hedged_claims", "no_reference_unverifiable"),
                })

    disagreements = 0
    for result in flagged:
        reviews = list(db.scalars(select(HumanReview).where(HumanReview.result_id == result.id)).all())
        if reviews_disagree(reviews):
            disagreements += 1

    return {
        "project_id": project.id,
        "dataset_id": dataset.id,
        "dataset_version_id": version.id,
        "rubric_id": rubric.id,
        "rubric_version_id": rubric_version.id,
        "evaluation_run_id": run.id,
        "records": version.record_count,
        "flagged_for_review": len(flagged),
        "disagreement_items": disagreements,
        "demo_reviewer_emails": [u.email for u in reviewers],
        "demo_reviewer_password": demo_reviewer_password,
        "is_demo": True,
        "note": "All values above come from the clearly labeled demonstration dataset, not production measurements.",
    }
