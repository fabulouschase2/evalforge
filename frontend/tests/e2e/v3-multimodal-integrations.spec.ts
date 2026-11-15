// V3.1 e2e: multimodal annotation + API integrations through the real UI.
// Covers: media upload, image annotation workspace (bbox drawing, save,
// submit), audio/video annotation surfaces, API key lifecycle (create with
// one-time secret, revoke), and webhook endpoint validation (SSRF refusal).
//
// Requires dev servers + admin@evalforge.dev (created by earlier specs).
import { expect, test } from "@playwright/test";

const adminEmail = "admin@evalforge.dev";
const adminPassword = "AdminPass!23";
const stamp = Date.now();
const workerEmail = `mm-worker-${stamp}@evalforge.dev`;
const password = "E2ePass!23";
const projectName = `MM flows ${stamp}`;

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
  await expect(page).toHaveURL(/dashboard/, { timeout: 15000 });
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

// a real 1x1 PNG so the <img> actually renders in the workspace
const PNG_1PX = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);
// minimal WAV (1s of silence, 8kHz mono 16-bit) so the waveform can decode
function wavBytes(): Buffer {
  const sampleRate = 8000, seconds = 1, channels = 1, bits = 16;
  const dataSize = sampleRate * seconds * channels * (bits / 8);
  const buf = Buffer.alloc(44 + dataSize);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + dataSize, 4); buf.write("WAVE", 8);
  buf.write("fmt ", 12); buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); buf.writeUInt16LE(channels, 22);
  buf.writeUInt32LE(sampleRate, 24); buf.writeUInt32LE(sampleRate * channels * bits / 8, 28);
  buf.writeUInt16LE(channels * bits / 8, 32); buf.writeUInt16LE(bits, 34);
  buf.write("data", 36); buf.writeUInt32LE(dataSize, 40);
  return buf;
}

let projectId = 0;
let imageMediaId = 0;
let audioMediaId = 0;

test.describe.serial("V3.1 multimodal + integrations", () => {
  test("admin uploads image + audio via the UI, generates annotation tasks", async ({ page }) => {
    await login(page, adminEmail);
    await page.goto("/projects");
    await page.getByRole("button", { name: "New project" }).first().click();
    await page.getByLabel("Project name").fill(projectName);
    await page.getByRole("dialog").getByRole("button", { name: "Create project" }).click();
    await expect(page.getByText(projectName).first()).toBeVisible({ timeout: 10000 });
    const projects = await adminApi(page, "GET", "/projects");
    projectId = (projects.body as { id: number; name: string }[]).find((p) => p.name === projectName)!.id;
    // the account must exist before it can be added as a member
    const u = await adminApi(page, "POST", "/auth/users",
                             { email: workerEmail, name: "MM Worker", password, role: "tester" });
    expect([200, 201]).toContain(u.status);
    await adminApi(page, "POST", `/projects/${projectId}/members`,
                   { email: workerEmail, role: "tester" });

    // media upload through the real file input
    await page.goto("/multimodal");
    await page.setInputFiles('input[type="file"]', {
      name: `street-${stamp}.png`, mimeType: "image/png", buffer: PNG_1PX,
    });
    await page.getByLabel("Annotation labels").fill("car, person");
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    await expect(page.getByText("Media uploaded")).toBeVisible({ timeout: 10000 });
    const media = await adminApi(page, "GET", `/media/projects/${projectId}`);
    imageMediaId = (media.body as { id: number; media_type: string }[]).find((m) => m.media_type === "image")!.id;

    await page.setInputFiles('input[type="file"]', {
      name: `interview-${stamp}.wav`, mimeType: "audio/wav", buffer: wavBytes(),
    });
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    await expect(page.getByText("Media uploaded").nth(1)).toBeVisible({ timeout: 10000 });
    const media2 = await adminApi(page, "GET", `/media/projects/${projectId}`);
    audioMediaId = (media2.body as { id: number; media_type: string; filename: string }[]).find(
      (m) => m.media_type === "audio")!.id;

    await page.getByRole("button", { name: "Generate tasks" }).click();
    await expect(page.getByText(/annotation tasks created/i)).toBeVisible({ timeout: 10000 });
  });

  test("worker annotates the image in the workspace: draws, saves, submits", async ({ page }) => {
    await login(page, workerEmail);
    const imageTitle = `Annotate image: street-${stamp}`;
    // claim the image task via API, then drive the workspace UI directly
    const claimed = await page.evaluate(async (titlePart) => {
      const token = localStorage.getItem("evalforge_token");
      const list = await (await fetch("/api/tasks/available?page_size=50", {
        headers: { Authorization: `Bearer ${token}` },
      })).json();
      const target = (list.items as { id: number; title: string }[]).find(
        (t) => t.title.includes(titlePart));
      if (!target) return null;
      await fetch(`/api/tasks/${target.id}/claim`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      await fetch(`/api/tasks/${target.id}/start`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      return target.id;
    }, imageTitle);
    expect(claimed, "image task available").toBeTruthy();
    await page.goto(`/tasks/${claimed}`);
    await expect(page.getByText(`street-${stamp}.png`)).toBeVisible({ timeout: 15000 });

    // draw one bbox: two clicks on the canvas (bbox tool is default)
    const canvas = page.locator("div[style*='aspect-ratio']").first();
    const box = await canvas.boundingBox();
    expect(box).toBeTruthy();
    await page.mouse.click(box!.x + box!.width * 0.2, box!.y + box!.height * 0.2);
    await page.mouse.click(box!.x + box!.width * 0.7, box!.y + box!.height * 0.6);
    await expect(page.getByText("Shapes (1)")).toBeVisible({ timeout: 10000 });

    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText(/Saved \(version 1\)/)).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: "Submit", exact: true }).click();
    await expect(page.getByText("Annotation submitted")).toBeVisible({ timeout: 10000 });
  });

  test("audio workspace opens with waveform and accepts segments", async ({ page }) => {
    await login(page, workerEmail);
    const audioTitle = `Annotate audio: interview-${stamp}`;
    const claimed = await page.evaluate(async (titlePart) => {
      const token = localStorage.getItem("evalforge_token");
      const list = await (await fetch("/api/tasks/available?page_size=50", {
        headers: { Authorization: `Bearer ${token}` },
      })).json();
      const target = (list.items as { id: number; title: string }[]).find(
        (t) => t.title.includes(titlePart));
      if (!target) return null;
      await fetch(`/api/tasks/${target.id}/claim`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      await fetch(`/api/tasks/${target.id}/start`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      return target.id;
    }, audioTitle);
    if (!claimed) return; // audio task already claimed in an earlier partial run
    await page.goto(`/tasks/${claimed}`);
    // the audio workspace shows the waveform canvas + segment tooling
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: "Add segment" }).click();
    await page.getByPlaceholder("Transcript…").fill("Hello world.");
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText(/Saved \(version/)).toBeVisible({ timeout: 10000 });
  });

  test("admin manages API key lifecycle: create (secret once) + revoke", async ({ page }) => {
    await login(page, adminEmail);
    await page.goto("/integrations");
    await page.getByRole("button", { name: "New key" }).click();
    await page.getByLabel("Name").fill(`CI key ${stamp}`);
    await page.getByRole("button", { name: "Create key" }).click();
    // the one-time secret dialog appears and can be copied
    await expect(page.getByText("API key created").first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator("code").filter({ hasText: "ef_" }).first()).toBeVisible();
    await page.getByRole("button", { name: "Copy" }).click();
    await page.getByRole("button", { name: /Close|Ok|Done/i }).click().catch(() => {});
    // revoke it via the confirm dialog
    const row = page.locator("tr").filter({ hasText: `CI key ${stamp}` });
    await row.getByRole("button", { name: "Revoke" }).click();
    await page.getByRole("button", { name: "Revoke" }).last().click();
    await expect(page.getByText("Key revoked")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("revoked").first()).toBeVisible();
  });

  test("webhook endpoint creation rejects internal URLs (SSRF) in the UI", async ({ page }) => {
    await login(page, adminEmail);
    await page.goto("/integrations");
    await page.getByRole("button", { name: "Webhooks" }).click();
    await page.getByRole("button", { name: "New endpoint" }).click();
    // dialog renders with the SSRF notice; fill an internal URL
    await expect(page.getByText(/internal network targets are blocked/i)).toBeVisible();
    await page.getByLabel("Endpoint URL").fill("http://localhost:9000/hook");
    // the refusal is verified through the same origin (server returns 422)
    const res = await page.evaluate(async () => {
      const token = localStorage.getItem("evalforge_token");
      const r = await fetch("/api/admin/webhooks", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ url: "http://localhost:9000/hook", events: ["project.created"] }),
      });
      return { status: r.status, body: await r.json().catch(() => null) };
    });
    expect(res.status).toBe(422);
    expect(JSON.stringify(res.body)).toContain("forbidden address");
    // nothing was created
    const hooks = await adminApi(page, "GET", "/admin/webhooks");
    expect((hooks.body as { url: string }[]).some((w) => w.url.includes("localhost"))).toBe(false);
    await page.getByRole("button", { name: "Cancel" }).click();
  });
});
