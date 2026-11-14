import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Shield } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";

export default function LoginPage() {
  const { login, user, loading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to="/dashboard" replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-teal">
            <Shield className="h-6 w-6 text-[#0B1518]" />
          </div>
          <div className="text-center">
            <h1 className="text-xl font-bold text-fg">EvalForge AI</h1>
            <p className="mt-1 text-sm text-fg-muted">Evaluation &amp; quality assurance platform</p>
          </div>
        </div>

        <form onSubmit={submit} className="rounded-lg border border-border bg-base-card p-5 shadow-lg" aria-label="Sign in">
          <div className="mb-4">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email" type="email" required autoComplete="email"
              placeholder="you@team.dev" value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="mb-5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password" type="password" required autoComplete="current-password"
              placeholder="••••••••" value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <div role="alert" className="mb-4 rounded-md border border-danger/40 bg-[rgba(239,68,68,0.08)] px-3 py-2 text-sm text-danger">
              {error}
            </div>
          )}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </Button>
          <p className="mt-4 text-center text-sm text-fg-muted">
            No account?{" "}
            <Link to="/register" className="font-medium text-teal hover:underline">
              Create one
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
