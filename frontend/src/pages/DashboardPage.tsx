// Dashboard dispatcher: each role lands on its own workspace overview.
import { useAuth } from "@/lib/auth";
import { isClientRole, isStaff } from "@/lib/roles";
import AdminOverview from "@/pages/dashboard/AdminOverview";
import TesterOverview from "@/pages/dashboard/TesterOverview";
import ReviewerOverview from "@/pages/dashboard/ReviewerOverview";
import QualityOverview from "@/pages/dashboard/QualityOverview";
import ClientDashboard from "@/pages/client/ClientDashboard";
import { EmptyState } from "@/components/ui/states";

export default function DashboardPage() {
  const { user } = useAuth();
  const role = user?.role ?? "tester";

  if (isClientRole(role)) return <ClientDashboard />;
  if (isStaff(role)) return <AdminOverview />;
  if (role === "tester") return <TesterOverview />;
  if (role === "senior_reviewer") return <QualityOverview />;
  if (role === "reviewer") return <ReviewerOverview />;
  return <EmptyState title="Unknown role" description={`No workspace configured for role "${role}".`} />;
}
