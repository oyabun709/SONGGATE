import { NewReleaseSheet } from "@/components/release/new-release-sheet";

export default function ReleasesPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Releases</h1>
          <p className="mt-1 text-sm text-slate-500">
            Manage release artifacts and track QA scan status.
          </p>
        </div>
        <NewReleaseSheet />
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-400">
        No releases yet. Create a release to upload your first artifact.
      </div>
    </div>
  );
}
