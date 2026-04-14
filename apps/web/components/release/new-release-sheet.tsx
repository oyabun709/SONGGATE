"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@clerk/nextjs";
import { Plus, X } from "lucide-react";
import { UploadZone } from "./UploadZone";

const schema = z.object({
  title: z.string().min(1, "Title is required"),
  artist: z.string().min(1, "Artist is required"),
  submission_format: z.enum(["DDEX_ERN_43", "DDEX_ERN_42", "CSV", "JSON"]),
  upc: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

export function NewReleaseSheet() {
  const [open, setOpen] = useState(false);
  const [releaseId, setReleaseId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { getToken } = useAuth();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { submission_format: "DDEX_ERN_43" },
  });

  async function onSubmit(values: FormValues) {
    setCreating(true);
    setError(null);
    try {
      const token = await getToken();
      const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${apiBase}/releases`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(values),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail ?? `Failed to create release (${res.status})`);
      }
      const data = await res.json();
      setReleaseId(data.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setCreating(false);
    }
  }

  function close() {
    setOpen(false);
    setReleaseId(null);
    setError(null);
    reset();
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
      >
        <Plus className="h-4 w-4" />
        New Release
      </button>
    );
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={close}
        aria-hidden
      />

      {/* Sheet */}
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="text-base font-semibold text-slate-900">
            {releaseId ? "Upload Artifacts" : "New Release"}
          </h2>
          <button
            onClick={close}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {!releaseId ? (
            /* Step 1 — create the release record */
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Release title *
                </label>
                <input
                  {...register("title")}
                  className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  placeholder="e.g. Midnights"
                />
                {errors.title && (
                  <p className="mt-1 text-xs text-red-600">{errors.title.message}</p>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Artist *
                </label>
                <input
                  {...register("artist")}
                  className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  placeholder="e.g. Taylor Swift"
                />
                {errors.artist && (
                  <p className="mt-1 text-xs text-red-600">{errors.artist.message}</p>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Submission format *
                </label>
                <select
                  {...register("submission_format")}
                  className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                >
                  <option value="DDEX_ERN_43">DDEX ERN 4.3</option>
                  <option value="DDEX_ERN_42">DDEX ERN 4.2</option>
                  <option value="CSV">CSV</option>
                  <option value="JSON">JSON</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700">
                  UPC / EAN
                </label>
                <input
                  {...register("upc")}
                  className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  placeholder="12-digit barcode"
                />
              </div>

              {error && (
                <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={creating}
                className="w-full rounded-md bg-indigo-600 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:opacity-60"
              >
                {creating ? "Creating…" : "Continue to Upload"}
              </button>
            </form>
          ) : (
            /* Step 2 — upload artifacts */
            <div className="space-y-6">
              <p className="text-sm text-slate-500">
                Upload one or more artifacts for this release. DDEX package upload
                triggers an automatic QA scan.
              </p>

              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  DDEX Package
                </h3>
                <UploadZone releaseId={releaseId} fileType="ddex_package" />
              </section>

              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Audio
                </h3>
                <UploadZone releaseId={releaseId} fileType="audio" />
              </section>

              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Artwork
                </h3>
                <UploadZone releaseId={releaseId} fileType="artwork" />
              </section>

              <button
                onClick={close}
                className="w-full rounded-md border border-slate-200 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
              >
                Done
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
