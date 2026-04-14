export default function ReleasesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Releases</h1>
        <p className="mt-1 text-sm text-slate-500">
          Manage and track all release artifacts and their QA status.
        </p>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-400">
        No releases yet. Upload a release artifact to get started.
      </div>
    </div>
  );
}
