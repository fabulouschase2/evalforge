// V3.1 e2e: quality flows through the real UI.
// Covers: golden task queue configuration, golden-task scoring through a real
// worker submission, qualification take flow (pass), reviewer revision requests
// with tester feedback, and the senior-reviewer adjudication surface.
//
// Requires dev servers (backend :8000, frontend :5173). The admin account
// admin@evalforge.dev must exist (the v2 workflow spec / smoke test create it).
import { expect, test } from "@playwright/test";

const adminEmail = "admin@evalforge.dev";
const adminPassword = "AdminPass!23";
const stamp = Date.now();
const password = "E2ePass!23";
const workerEmail = `q-worker-${stamp}@evalforge.dev`;
const rev1Email = `q-rev1-${stamp}@evalforge.dev`;
const rev2Email = `q-rev2-${stamp}@evalforge.dev`;
const seniorEmail = `q-senior-${stamp}@evalforge.dev`;
const projectName = `Q flows ${stamp}`;

async function login(page: import("@playwright/test").Page, email: string) {
  // reuse an existing valid session for this user (avoids the auth rate limiter)
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
    await page.evaluate(() => localStorage.clear()).catch(() => {});
    await page.goto("/login");
    appeared = await page.getByLabel("Email").waitFor({ state: "visible", timeout: 5000 })
      .then(() => true).catch(() => false);
    if (!appeared) await page.waitForTimeout(800);
  }
  expect(appeared, "login page rendered").toBe(true);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(email === adminEmail ? adminPassword : password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/dashboard|client/, { timeout: 15000 });
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

let projectId = 0;
let datasetId = 0;
let rubricId = 0;

test.describe.serial("V3.1 quality flows", () => {
  test("admin seeds users, project, dataset, rubric, tasks; configures golden queue; creates golden task + qualification", async ({ page }) => {
    await login(page, adminEmail);

    // project via the real UI
    await page.goto("/projects");
    await page.getByRole("button", { name: "New project" }).first().click();
    await page.getByLabel("Project name").fill(projectName);
    await page.getByRole("dialog").getByRole("button", { name: "Create project" }).click();
    await expect(page.getByText(projectName).first()).toBeVisible({ timeout: 10000 });
    const projects = await adminApi(page, "GET", "/projects");
    projectId = (projects.body as { id: number; name: string }[]).find((p) => p.name === projectName)!.id;

    // members
    const members: [string, string, string][] = [
      [workerEmail, "tester", "tester"],
      [rev1Email, "reviewer", "reviewer"],
      [rev2Email, "reviewer", "reviewer"],
      [seniorEmail, "senior_reviewer", "reviewer"],
    ];
    for (const [email, role, memberRole] of members) {
      const u = await adminApi(page, "POST", "/auth/users", { email, name: email.split("@")[0], password, role });
      expect([200, 201]).toContain(u.status);
      await adminApi(page, "POST", `/projects/${projectId}/members`, { email, role: memberRole });
    }

    // dataset + records via the real upload endpoint
    const ds = await adminApi(page, "POST", "/datasets", { name: `DS ${stamp}`, project_id: projectId });
    expect(ds.status).toBe(201);
    datasetId = ds.body.id;
    const upload = await page.evaluate(async ({ datasetId }) => {
      const token = localStorage.getItem("evalforge_token");
      const rows = [
        { record_id: "q1", prompt: "Capital of France?", response: "Paris is the capital of France.", reference_answer: "Paris" },
        { record_id: "q2", prompt: "2+2?", response: "4", reference_answer: "4" },
        { record_id: "q3", prompt: "Largest ocean?", response: "The Pacific Ocean.", reference_answer: "Pacific" },
      ];
      const fd = new FormData();
      fd.append("file", new File([JSON.stringify(rows)], "records.json", { type: "application/json" }));
      const res = await fetch(`/api/datasets/${datasetId}/upload/commit`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` }, body: fd,
      });
      return res.status;
    }, { datasetId });
    expect(upload).toBe(201);

    // rubric (no evaluation form -> free-form workspace with explanation field)
    const rub = await adminApi(page, "POST", "/rubrics", {
      name: `R ${stamp}`,
      definition: {
        name: "R", criteria: [
          { id: "acc", name: "Accuracy", description: "d", weight: 1.0,
            scoring_scale: { type: "binary", min: 0, max: 1 }, pass_threshold: 1,
            checks: [{ type: "completeness", rule_id: "c", params: {} }] },
        ],
        passing_threshold: 0.6,
      },
      project_id: projectId,
    });
    rubricId = rub.body.id;

    // golden queue configuration through the real dialog
    await page.goto("/golden-tasks");
    await page.getByRole("button", { name: /Queue config/ }).click();
    await page.getByLabel("Project *").selectOption({ label: projectName });
    await page.getByLabel("Insertion percentage").fill("100");
    await page.getByLabel("Min ordinary tasks between probes").fill("0");
    await page.getByRole("button", { name: "Save config" }).click();
    await expect(page.getByText("Golden task config saved")).toBeVisible({ timeout: 10000 });

    // golden task (known wrong-answer trap for free-form submissions)
    const golden = await adminApi(page, "POST", "/golden-tasks", {
      project_id: projectId,
      title: "GOLDEN capital",
      reference_answer: { answer: "Paris" },
      scoring_method: "exact",
      difficulty: "easy",
      payload: { prompt: "Capital of France?" },
    });
    expect(golden.status).toBe(201);

    // qualification assessment
    const assessment = await adminApi(page, "POST", "/qualifications", {
      title: `Qual ${stamp}`, assessment_type: "mcq", passing_score: 1.0,
      skill_tags: ["Data annotation"],
      questions: [{ question_type: "mcq", prompt: "Capital of France?",
                    options: ["Paris", "London"], correct_answer: { value: "Paris" }, points: 1 }],
    });
    expect(assessment.status).toBe(201);

    // generate tasks (golden probes woven in at 100%)
    const gen = await adminApi(page, "POST", "/tasks/generate",
                               { project_id: projectId, dataset_id: datasetId, rubric_id: rubricId });
    expect(gen.body.created).toBeGreaterThanOrEqual(1);
    expect(gen.body.golden_inserted).toBeGreaterThanOrEqual(1);
  });

  test("worker passes the qualification assessment in the UI", async ({ page }) => {
    await login(page, workerEmail);
    await page.goto("/my-qualifications");
    await page.getByRole("button", { name: "Take" }).first().click();
    await expect(page.getByText("Capital of France?").first()).toBeVisible({ timeout: 15000 });
    const radio = page.getByRole("radio", { name: "Paris" });
    if ((await radio.count()) === 1) {
      await radio.check();
    } else {
      await page.locator('input[type="radio"]').first().check();
    }
    await page.getByRole("button", { name: "Submit attempt" }).click();
    await expect(page.getByText("Assessment passed!")).toBeVisible({ timeout: 10000 });
  });

  test("worker submissions are scored by the golden probe; report reflects attempts", async ({ page }) => {
    await login(page, workerEmail);
    // submit wrong answers to every available task; at least one is the golden probe.
    // Marketplace UX: Start task CLAIMS (toast, no navigation) -> work via My Tasks.
    for (let i = 0; i < 4; i++) {
      await page.goto("/tasks/available");
      await expect(page.getByText(projectName).first()).toBeVisible({ timeout: 15000 });
      const start = page.getByRole("button", { name: "Start task" });
      if ((await start.count()) === 0) break;
      await start.last().click();
      await expect(page.getByText("Task claimed")).toBeVisible({ timeout: 10000 });

      await page.goto("/tasks/mine");
      await page.getByRole("link", { name: /Continue|Start/ }).first().click();
      await expect(page.getByText("Written explanation").first()).toBeVisible({ timeout: 15000 });
      await page.getByLabel("Written explanation").fill("London");
      await page.getByRole("button", { name: "Submit work" }).click();
      await page.getByRole("button", { name: "Submit now" }).click();
      await expect(page.getByText("Work submitted")).toBeVisible({ timeout: 15000 });
    }
    // the golden report (quality lead surface) shows stored attempts
    await login(page, adminEmail);
    await page.goto("/quality/golden");
    await expect(page.getByText("Golden attempts").first()).toBeVisible({ timeout: 10000 });
    const report = await adminApi(page, "GET", "/quality/golden/report");
    expect(report.body.attempts).toBeGreaterThanOrEqual(1);
    expect(report.body.accuracy).toBeLessThan(1); // wrong answers were recorded honestly
  });

  test("reviewer requests revisions; tester receives the feedback", async ({ page }) => {
    await login(page, rev1Email);
    await page.goto("/review-queue");
    await expect(page.getByText(projectName).first()).toBeVisible({ timeout: 15000 });
    const reviewLinks = page.getByRole("link", { name: "Review →" });
    const count = await reviewLinks.count();
    expect(count).toBeGreaterThanOrEqual(1);
    for (let i = 0; i < count; i++) {
      await page.goto("/review-queue");
      await page.getByRole("link", { name: "Review →" }).first().click();
      await page.getByLabel("Decision").selectOption("revision_requested");
      await page.getByLabel("Reviewer comments").fill("Please add your reasoning.");
      await page.getByRole("button", { name: "Record decision" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Record decision" }).click();
      await expect(page.getByText("Decision recorded")).toBeVisible({ timeout: 15000 });
    }
    // tester sees the revision feedback: a notification and the submissions page
    await login(page, workerEmail);
    await page.goto("/notifications");
    await expect(page.getByText(/revision/i).first()).toBeVisible({ timeout: 15000 });
  });

  test("senior reviewer adjudication surface renders; reviewer2 weighs in for disagreement", async ({ page }) => {
    // reviewer 2 approves one of the revision requests' siblings to create
    // decision history; the senior sees the adjudication queue page
    await login(page, rev2Email);
    await page.goto("/review-queue");
    const link = page.getByRole("link", { name: "Review →" }).first();
    if (await link.count()) {
      await link.click();
      await page.getByLabel("Decision").selectOption("approved");
      await page.getByRole("button", { name: "Record decision" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Record decision" }).click();
      await expect(page.getByText("Decision recorded")).toBeVisible({ timeout: 15000 });
    }
    await login(page, seniorEmail);
    await page.goto("/quality/adjudication");
    await expect(page.getByRole("heading", { name: /Adjudication/i }).first()).toBeVisible({ timeout: 10000 });
  });
});
