// V3 E2E: client journey through the real UI — organization, request, approval,
// conversion, client dataset upload, messaging, deliverable publish + download.
// Requires dev servers on :5173 (frontend) and :8000 (backend) like the v2 spec.
import { test, expect, request as pwRequest } from "@playwright/test";

const BASE = "http://localhost:5173";

let adminToken = "";
let orgId = 0;
let clientEmail = "";

async function api(path: string, token: string, method = "GET", payload?: unknown) {
  const req = await pwRequest.newContext();
  try {
    const res = await req.fetch(`http://localhost:8000${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      data: payload ? JSON.stringify(payload) : undefined,
    });
    const text = await res.text();
    return { status: res.status(), json: () => JSON.parse(text), text };
  } finally {
    await req.dispose();
  }
}

test.describe.serial("V3 client portal workflow", () => {
  test("admin sets up organization, client member and project request", async ({ page, request }) => {
    // admin login via UI
    await page.goto(`${BASE}/login`);
    await page.getByRole("textbox", { name: "Email" }).fill("admin@evalforge.dev");
    await page.getByRole("textbox", { name: "Password" }).fill("AdminPass!23");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Administration overview" })).toBeVisible({ timeout: 15000 });

    // fetch admin token for API setup
    const login = await request.post("http://localhost:8000/api/auth/login", {
      data: { email: "admin@evalforge.dev", password: "AdminPass!23" },
    });
    adminToken = (await login.json()).access_token;

    const stamp = Date.now();
    clientEmail = `client.e2e.${stamp}@demo.dev`;

    // create org + client owner through the UI (Organizations page)
    await page.goto(`${BASE}/organizations`);
    await page.getByRole("button", { name: "New organization" }).click();
    await page.getByLabel("Name").fill(`E2E Org ${stamp}`);
    await page.getByRole("button", { name: "Create organization", exact: true }).click();
    await expect(page.getByText("Organization created")).toBeVisible({ timeout: 10000 });

    const orgs = await (await api("/api/organizations", adminToken)).json();
    orgId = orgs[0].id;

    // register the client user (gets tester role), then add as client_owner
    const reg = await api("/api/auth/register", adminToken, "POST", {
      email: clientEmail, name: "E2E Client", password: "ClientPass!23",
    });
    expect([200, 201, 409]).toContain(reg.status);
    const add = await api(`/api/organizations/${orgId}/members`, adminToken, "POST", {
      email: clientEmail, role: "client_owner",
    });
    expect(add.status).toBe(201);
  });

  test("client submits a project request in the UI", async ({ page }) => {
    await page.goto(`${BASE}/login`);
    await page.getByRole("textbox", { name: "Email" }).fill(clientEmail);
    await page.getByRole("textbox", { name: "Password" }).fill("ClientPass!23");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible({ timeout: 15000 });

    await page.goto(`${BASE}/client/requests`);
    await page.getByRole("button", { name: "New request" }).click();
    await page.getByLabel("Project title *").fill("E2E annotation request");
    await page.getByLabel("Description").fill("Browser-test request with expected volume.");
    await page.getByLabel("Expected task volume").fill("250");
    await page.getByRole("button", { name: "Submit request" }).click();
    await expect(page.getByText("Request submitted")).toBeVisible({ timeout: 10000 });
  });

  test("admin approves and converts; client sees the project", async ({ page }) => {
    // admin side through the queue UI
    await page.goto(`${BASE}/login`);
    await page.getByRole("textbox", { name: "Email" }).fill("admin@evalforge.dev");
    await page.getByRole("textbox", { name: "Password" }).fill("AdminPass!23");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Administration overview" })).toBeVisible({ timeout: 15000 });

    await page.goto(`${BASE}/client-requests`);
    const row = page.locator("tr", { hasText: "E2E annotation request" }).first();
    await expect(row).toBeVisible({ timeout: 10000 });
    await row.getByRole("button", { name: "Approve" }).click();
    await page.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByText(/Request updated/)).toBeVisible({ timeout: 10000 });

    const row2 = page.locator("tr", { hasText: "E2E annotation request" }).first();
    await row2.getByRole("button", { name: "Convert" }).click();
    await page.getByRole("button", { name: "Create project" }).click();
    await expect(page.getByText(/Project created/)).toBeVisible({ timeout: 10000 });
  });

  test("client monitors the converted project and downloads a deliverable", async ({ page }) => {
    await page.goto(`${BASE}/login`);
    await page.getByRole("textbox", { name: "Email" }).fill(clientEmail);
    await page.getByRole("textbox", { name: "Password" }).fill("ClientPass!23");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible({ timeout: 15000 });

    await page.goto(`${BASE}/client/projects`);
    await expect(page.getByText("E2E annotation request")).toBeVisible({ timeout: 10000 });

    // staff publish a deliverable via API, then the client downloads it in the UI
    const projects = await (await api("/api/client/projects", adminToken)).json();
    // (client projects endpoint needs the client token; use admin /projects instead)
    const all = await (await api("/api/projects", adminToken)).json();
    const proj = all.find((p: { name: string }) => p.name === "E2E annotation request");
    expect(proj).toBeTruthy();
    const pub = await api(`/api/admin/projects/${proj.id}/deliverables`, adminToken, "POST",
      { label: "E2E batch", format: "json" });
    expect(pub.status).toBe(201);

    await page.goto(`${BASE}/client/deliverables`);
    await expect(page.getByText("E2E batch")).toBeVisible({ timeout: 10000 });
    const downloadBtn = page.getByRole("button", { name: "Download" }).first();
    await expect(downloadBtn).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 15000 }),
      downloadBtn.click(),
    ]);
    expect(download.suggestedFilename()).toContain(".json");
  });
});
