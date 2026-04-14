export default function RulesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Rules</h1>
        <p className="mt-1 text-sm text-slate-500">
          Define and manage QA validation rules applied to release artifacts.
        </p>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-400">
        No rules configured. Add your first rule to start validating releases.
      </div>
    </div>
  );
}
