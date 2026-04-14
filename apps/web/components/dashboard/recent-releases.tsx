"use client";

export function RecentReleases() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold text-slate-900">Recent Releases</h2>
      <div className="mt-4 flex flex-col items-center justify-center py-8 text-center text-slate-400">
        <p className="text-sm">No recent releases</p>
      </div>
    </div>
  );
}
