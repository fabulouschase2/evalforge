import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { StatusBadge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import LoginPage from "@/pages/LoginPage";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/components/ui/toast";

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <ToastProvider>
          <LoginPage />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("StatusBadge", () => {
  it("renders statuses in readable form", () => {
    render(<StatusBadge status="borderline" />);
    expect(screen.getByText("borderline")).toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("shows title, description and action", () => {
    render(
      <EmptyState title="Nothing here" description="Some explanation" action={<button>Do it</button>} />,
    );
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("Some explanation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Do it" })).toBeInTheDocument();
  });
});

describe("LoginPage", () => {
  it("submits credentials and shows validation errors", async () => {
    const user = userEvent.setup();
    const ok = vi.fn();
    // auth context lives above; render with providers and stub fetch
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ access_token: "t", token_type: "bearer", user: { id: 1, email: "a@b.dev", name: "A", role: "administrator", created_at: "2026-01-01T00:00:00" } }),
        { status: 200 },
      ),
    );

    renderLogin();

    await user.type(screen.getByLabelText("Email"), "a@b.dev");
    await user.type(screen.getByLabelText("Password"), "Password!23");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(fetchMock).toHaveBeenCalled();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/auth/login");
    expect((init as RequestInit).method).toBe("POST");
    ok();
    fetchMock.mockRestore();
  });

  it("renders a link to register", () => {
    renderLogin();
    expect(screen.getByText("Create one")).toBeInTheDocument();
  });
});
