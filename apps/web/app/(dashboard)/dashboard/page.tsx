import { StatsCards } from "@/components/dashboard/stats-cards";
import { RecentReleases } from "@/components/dashboard/recent-releases";
import { PipelineHealth } from "@/components/dashboard/pipeline-health";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Release operations overview and QA pipeline status.
        </p>
      </div>
      <StatsCards />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <RecentReleases />
        <PipelineHealth />
      </div>
    </div>
  );
}
