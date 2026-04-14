export default function ReportsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Reports</h1>
        <p className="mt-1 text-sm text-slate-500">
          QA reports, pass/fail trends, and release quality metrics.
        </p>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-400">
        No reports available yet. Reports are generated after pipeline runs.
      </div>
    </div>
  );
}
