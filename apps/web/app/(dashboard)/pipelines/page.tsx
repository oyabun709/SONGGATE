export default function PipelinesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Pipelines</h1>
        <p className="mt-1 text-sm text-slate-500">
          Monitor active QA pipeline runs and their task execution status.
        </p>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-400">
        No active pipelines. Pipelines start when a release is submitted.
      </div>
    </div>
  );
}
