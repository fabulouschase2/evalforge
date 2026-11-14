// End-to-end: the complete v2 multi-role workflow through the real UI.
//
// Requires dev servers running:
//   backend:  cd backend && uvicorn app.main:app --port 8000
//   frontend: cd frontend && npm run dev
// Run:  npx playwright test
//
// Flow: admin registers (first user = super admin) -> loads demo pipeline ->
// creates users via admin API -> creates project + dataset + rubric via UI ->
// generates tasks -> tester claims, fills the dynamic form and submits ->
// reviewer approves -> analytics + audit reflect the workflow.

import { expect, test } from "@playwright/test";

const stamp = Date.now();
// The seeded super admin (documented in README); fresh DBs recreate it via the
// smoke test or the same registration flow.
const adminEmail = "admin@evalforge.dev";
const adminPassword = "AdminPass!23";
const testerEmail = `e2e-tester-${stamp}@evalforge.dev`;
const reviewerEmail = `e2e-reviewer-${stamp}@evalforge.dev`;
const password = "E2ePass!23";
const projectName = `E2E project ${stamp}`;

async function login(page: import("@playwright/test").Page, email: string) {
  // If this context already holds a valid session for the target user, keep it.
  // Otherwise reset storage and sign in through the form (with retries for
  // dev-server HMR churn).
  const current = await page.evaluate(async () => {
    const t = localStorage.getItem("evalforge_token");
    if (!t) return null;
    try {
      const r = await fetch("/api/auth/me", { headers: { Authorization: `Bearer ${t}` } });
      return r.ok ? await r.json() : null;
    } catch {
      return null;
    }
  }).catch(() => null);
  if (current?.email === email) return;

  let appeared = false;
  for (let attempt = 0; attempt < 3 && !appeared; attempt++) {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForURL(/login/, { timeout: 10000 }).catch(() => {});
    await page.goto("/login");
    appeared = await page.getByLabel("Email").waitFor({ state: "visible", timeout: 5000 })
      .then(() => true).catch(() => false);
    if (!appeared) await page.waitForTimeout(800);
  }
  if (!appeared) {
    const state = await page.evaluate(() => ({
      errs: (window as unknown as { __errs?: string[] }).__errs ?? ["(none captured)"],
      url: window.location.href,
      rootHtml: document.getElementById("root")?.innerHTML?.slice(0, 300) ?? "",
    })).catch(() => ["(evaluate failed)"]);
    throw new Error("Login page did not render. State: " + JSON.stringify(state));
  }
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(email === adminEmail ? adminPassword : password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/dashboard/);
}

async function adminApi(page: import("@playwright/test").Page, method: string, path: string, data?: unknown) {
  return page.evaluate(async ({ method, path, data }) => {
    const token = localStorage.getItem("evalforge_token");
    const res = await fetch(`/api${path}`, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: data ? JSON.stringify(data) : undefined,
    });
    return { status: res.status, body: await res.json().catch(() => null) };
  }, { method, path, data });
}

test.describe.serial("EvalForge multi-role platform workflow", () => {
  let projectId = 0;
  let datasetId = 0;
  let rubricId = 0;

  test.beforeEach(async ({ page }) => {
    // capture every uncaught error so blank-screen failures report a cause
    await page.addInitScript(() => {
      (window as unknown as { __errs: string[] }).__errs = [];
      window.addEventListener("error", (e) => {
        (window as unknown as { __errs: string[] }).__errs.push(String(e.message));
      });
      window.addEventListener("unhandledrejection", (e) => {
        (window as unknown as { __errs: string[] }).__errs.push("rejection: " + String(e.reason));
      });
    });
  });

  test("admin signs in, creates accounts and project", async ({ page }) => {
    await login(page, adminEmail);
    await expect(page.getByText("Administration overview")).toBeVisible({ timeout: 15000 });

    // Create worker accounts through the admin API
    const r1 = await adminApi(page, "POST", "/auth/users", {
      email: testerEmail, name: "E2E Tester", password, role: "tester",
    });
    expect(r1.status).toBe(200);
    const r2 = await adminApi(page, "POST", "/auth/users", {
      email: reviewerEmail, name: "E2E Reviewer", password, role: "reviewer",
    });
    expect(r2.status).toBe(200);

    // Project with full configuration through the UI
    await page.goto("/projects");
    await page.getByRole("button", { name: "New project" }).click();
    await page.getByLabel("Project name").fill(projectName);
    await page.getByLabel("Project type").selectOption("data_annotation");
    await page.getByLabel("Client / organization").fill("E2E client");
    await page.getByLabel("Instructions for workers").fill("Be thorough.");
    await page.getByRole("button", { name: "Create project" }).click();
    await expect(page.getByRole("link", { name: new RegExp(projectName) })).toBeVisible({ timeout: 10000 });
    const href = await page.getByRole("link", { name: new RegExp(projectName) }).first().getAttribute("href");
    projectId = Number(href?.split("/").pop());
    expect(projectId).toBeGreaterThan(0);

    // Add members through project detail
    await page.goto(`/projects/${projectId}`);
    await page.getByRole("button", { name: "Add member" }).click();
    await page.getByLabel("User email").fill(testerEmail);
    await page.getByLabel("Membership role").selectOption("tester");
    await page.getByRole("button", { name: "Add member" }).last().click();
    await page.getByRole("button", { name: "Add member" }).click();
    await page.getByLabel("User email").fill(reviewerEmail);
    await page.getByLabel("Membership role").selectOption("reviewer");
    await page.getByRole("button", { name: "Add member" }).last().click();
    await expect(page.getByText(testerEmail)).toBeVisible();
    await expect(page.getByText(reviewerEmail)).toBeVisible();

    // Dataset + upload via wizard
    await page.goto("/datasets");
    await page.getByRole("button", { name: "New dataset" }).click();
    await page.getByLabel("Name").fill(`E2E DS ${stamp}`);
    await page.locator("#d-proj").selectOption({ label: projectName });
    await page.getByRole("button", { name: "Create dataset" }).click();
    // wait for the refetched list to contain THIS run's dataset, then open it
    const dsLink = page.getByRole("link", { name: `E2E DS ${stamp}` });
    await expect(dsLink).toBeVisible({ timeout: 15000 });
    await dsLink.click();
    await expect(page.getByText("Import records")).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: /choose a file to import/i }).click();
    await page.setInputFiles("input[type=file]", {
      name: "records.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify([
        { record_id: "e1", prompt: "What is the refund window?", response: "Refunds are available within 30 days.", reference_answer: "30 days" },
        { record_id: "e2", prompt: "Capital of France?", response: "The capital of France is Paris.", reference_answer: "Paris" },
      ]), "utf-8"),
    });
    await expect(page.getByText(/Commit import/)).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: /commit import/i }).click();
    // success signal: the "Import committed" toast + the wizard reset to the picker
    await expect(page.getByText("Import committed")).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("button", { name: /choose a file to import/i })).toBeVisible({ timeout: 20000 });
    const dsHref = await page.url();
    datasetId = Number(dsHref.split("/").pop());

    // Rubric with an evaluation form via the JSON tab
    await page.goto("/rubrics/new");
    await page.getByLabel("Rubric name").fill(`E2E Rubric ${stamp}`);
    await page.getByRole("tab", { name: "JSON" }).click();
    await page.getByLabel("Rubric JSON").fill(JSON.stringify({
      name: `E2E Rubric ${stamp}`,
      criteria: [{ id: "fmt", name: "Format", weight: 1, scoring_scale: { type: "binary", min: 0, max: 1 },
        pass_threshold: 1, checks: [{ type: "completeness", params: {} }] }],
      passing_threshold: 0.6,
      form: { fields: [
        { id: "verdict", type: "single_select", label: "Verdict", required: true, options: ["good", "bad"] },
        { id: "confidence", type: "likert", label: "Confidence", required: true, scale: { min: 1, max: 5 } },
      ] },
    }));
    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByText("Rubric definition is valid")).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: "Create rubric (version 1)" }).click();
    await expect(page).toHaveURL(/rubrics\/\d+/, { timeout: 10000 });
    rubricId = Number((await page.url()).split("/").pop());
  });

  test("admin generates tasks; tester claims, submits via dynamic form", async ({ page }) => {
    await login(page, adminEmail);
    await page.goto("/tasks");
    await page.getByRole("button", { name: "Generate from dataset" }).click();
    await page.getByLabel("Project", { exact: true }).selectOption({ index: 1 });
    const dsOption = page.getByLabel("Dataset", { exact: true }).locator("option").filter({ hasText: `E2E DS ${stamp}` });
    await page.getByLabel("Dataset", { exact: true }).selectOption(await dsOption.getAttribute("value") as never);
    const ruOption = page.getByLabel("Rubric", { exact: true }).locator("option").filter({ hasText: `E2E Rubric ${stamp}` });
    await page.getByLabel("Rubric", { exact: true }).selectOption(await ruOption.getAttribute("value") as never);
    await page.getByRole("button", { name: "Generate tasks" }).click();
    await expect(page.getByText(/task\(s\) created and published/)).toBeVisible({ timeout: 15000 });

    // Switch to the tester
    await login(page, testerEmail);
    await page.goto("/tasks/available");
    await expect(page.getByText(/What is the refund window/).first()).toBeVisible({ timeout: 15000 });
    const startButtons = page.getByRole("button", { name: /start task/i });
    await startButtons.first().click();
    await expect(page.getByText("Task claimed")).toBeVisible({ timeout: 10000 });

    await page.goto("/tasks/mine");
    await page.getByRole("link", { name: /Continue|Start/ }).first().click();
    await expect(page.getByText("Evaluation form")).toBeVisible({ timeout: 10000 });

    // Dynamic form from the rubric
    await page.getByLabel("Verdict").selectOption("good");
    // likert slider: leave default; fill explanation
    await page.getByLabel(/Written explanation/).fill("Response matches the reference.");
    await page.getByRole("button", { name: "Submit work" }).click();
    await page.getByRole("button", { name: "Submit now" }).click();
    await expect(page.getByText("Work submitted")).toBeVisible({ timeout: 15000 });

    // tester received no immediate decision yet; check notifications page renders
    await page.goto("/notifications");
    await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
  });

  test("reviewer approves; analytics and audit reflect the workflow", async ({ page }) => {
    await login(page, reviewerEmail);
    await page.goto("/review-queue");
    await expect(page.getByText(/E2E project/).first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("link", { name: "Review →" }).first().click();
    await expect(page.getByText("Tester submission")).toBeVisible({ timeout: 10000 });

    // blind review: tester identity hidden
    await expect(page.getByText(/identity hidden|blind/i).first()).toBeVisible();

    await page.getByLabel("Decision").selectOption("approved");
    await page.getByLabel("Reviewer comments").fill("Matches the reference answer.");
    await page.getByRole("button", { name: "Record decision" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Record decision" }).click();
    await expect(page.getByText("Decision recorded")).toBeVisible({ timeout: 15000 });

    // tester got the decision notification
    await login(page, testerEmail);
    await page.goto("/notifications");
    await expect(page.getByText(/approved/i).first()).toBeVisible({ timeout: 15000 });

    // admin overview reflects task activity
    await login(page, adminEmail);
    await page.goto("/dashboard");
    await expect(page.getByText("Administration overview")).toBeVisible();
    await expect(page.getByText("Tester performance")).toBeVisible({ timeout: 15000 });

    // audit trail contains the workflow
    await page.goto("/audit-logs");
    await expect(page.getByText("review.decision").first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("task.generate").first()).toBeVisible();
  });
});
