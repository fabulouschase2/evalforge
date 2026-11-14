// Profile page: account info, role and security notes.
import { useAuth } from "@/lib/auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ROLE_LABELS, type Role } from "@/lib/roles";
import { fmtDateTime } from "@/lib/utils";

export default function ProfilePage() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="space-y-5 max-w-2xl">
      <h1 className="text-xl font-bold text-fg">Profile</h1>
      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <CardDescription>Managed by platform administrators. Contact a super admin for changes.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex justify-between"><span className="text-fg-muted">Name</span><span className="text-fg">{user.name}</span></div>
          <div className="flex justify-between"><span className="text-fg-muted">Email</span><span className="text-fg">{user.email}</span></div>
          <div className="flex justify-between">
            <span className="text-fg-muted">Platform role</span>
            <Badge variant="default">{ROLE_LABELS[user.role as Role] ?? user.role}</Badge>
          </div>
          <div className="flex justify-between"><span className="text-fg-muted">Member since</span><span className="text-fg">{fmtDateTime(user.created_at)}</span></div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Security</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-fg-muted">
          <div>Sessions use JWT bearer tokens; your token expires automatically and is validated on every request.</div>
          <div>Passwords are stored as bcrypt hashes and never leave the server.</div>
          <div>All actions you take are recorded in the immutable audit trail.</div>
        </CardContent>
      </Card>
    </div>
  );
}
