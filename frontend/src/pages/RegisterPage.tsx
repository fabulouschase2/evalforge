import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";

export default function RegisterPage() {
  const { register, user, loading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to="/dashboard" replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    try {
      await register(email, name, password);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-bold text-fg">Create your account</h1>
          <p className="mt-1 text-sm text-fg-muted">
            The first account in a workspace becomes the administrator.
          </p>
        </div>

        <form onSubmit={submit} className="rounded-lg border border-border bg-base-card p-5 shadow-lg" aria-label="Create account">
          <div className="mb-4">
            <Label htmlFor="name">Full name</Label>
            <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex Reviewer" />
          </div>
          <div className="mb-4">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@team.dev" />
          </div>
          <div className="mb-5">
            <Label htmlFor="password">Password (min. 8 characters)</Label>
            <Input id="password" type="password" required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
          </div>
          {error && (
            <div role="alert" className="mb-4 rounded-md border border-danger/40 bg-[rgba(239,68,68,0.08)] px-3 py-2 text-sm text-danger">
              {error}
            </div>
          )}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Creating account…" : "Create account"}
          </Button>
          <p className="mt-4 text-center text-sm text-fg-muted">
            Already registered?{" "}
            <Link to="/login" className="font-medium text-teal hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
