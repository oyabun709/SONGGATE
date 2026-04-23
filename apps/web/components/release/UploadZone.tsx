"use client";

import { useCallback, useState } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { useAuth } from "@clerk/nextjs";
import {
  Upload,
  CheckCircle2,
  XCircle,
  FileArchive,
  Image,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── types ────────────────────────────────────────────────────────────────────

export type FileType = "ddex_package" | "artwork";

interface UploadZoneProps {
  releaseId: string;
  fileType: FileType;
  onUploadComplete?: (result: ConfirmResult) => void;
  className?: string;
}

interface ConfirmResult {
  releaseId: string;
  objectKey: string;
  artifactUrl: string;
  scanId: string | null;
}

type UploadState =
  | { status: "idle" }
  | { status: "rejected"; errors: string[] }
  | { status: "ready"; file: File }
  | { status: "signing" }
  | { status: "uploading"; file: File; progress: number }
  | { status: "confirming" }
  | { status: "complete"; result: ConfirmResult }
  | { status: "error"; message: string };

// ─── config ───────────────────────────────────────────────────────────────────

const MB = 1024 * 1024;
const GB = 1024 * MB;

const TYPE_CONFIG: Record<
  FileType,
  {
    label: string;
    hint: string;
    icon: React.ElementType;
    maxSize: number;
    accept: Record<string, string[]>;
  }
> = {
  ddex_package: {
    label: "DDEX Package",
    hint: "Work with three supported formats: DDEX XML, CSV, and JSON. · max 500 MB",
    icon: FileArchive,
    maxSize: 500 * MB,
    accept: {
      "application/zip": [".zip"],
      "application/x-zip-compressed": [".zip"],
      "text/xml": [".xml"],
      "application/xml": [".xml"],
    },
  },
  artwork: {
    label: "Artwork",
    hint: ".jpg, .png, .tiff · max 100 MB",
    icon: Image,
    maxSize: 100 * MB,
    accept: {
      "image/jpeg": [".jpg", ".jpeg"],
      "image/png": [".png"],
      "image/tiff": [".tiff", ".tif"],
    },
  },
};

// ─── helpers ──────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes >= GB) return `${(bytes / GB).toFixed(1)} GB`;
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function uploadToS3(
  url: string,
  file: File,
  onProgress: (pct: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    // Must match the ContentType used when the presigned URL was generated
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`S3 PUT returned ${xhr.status}: ${xhr.responseText}`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during S3 upload"));
    xhr.onabort = () => reject(new Error("Upload aborted"));
    xhr.send(file);
  });
}

// ─── component ────────────────────────────────────────────────────────────────

export function UploadZone({
  releaseId,
  fileType,
  onUploadComplete,
  className,
}: UploadZoneProps) {
  const { getToken } = useAuth();
  const [state, setState] = useState<UploadState>({ status: "idle" });
  const config = TYPE_CONFIG[fileType];
  const Icon = config.icon;
  const apiBase =
    process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  // ── drop handler ──────────────────────────────────────────────────────────

  const onDrop = useCallback(
    (accepted: File[], rejected: FileRejection[]) => {
      if (rejected.length > 0) {
        const errors = rejected.flatMap((r) =>
          r.errors.map((e) =>
            e.code === "file-too-large"
              ? `${r.file.name} is too large (max ${formatBytes(config.maxSize)})`
              : e.message
          )
        );
        setState({ status: "rejected", errors });
        return;
      }
      if (accepted.length > 0) {
        setState({ status: "ready", file: accepted[0] });
      }
    },
    [config.maxSize]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: config.accept,
    maxSize: config.maxSize,
    multiple: false,
    disabled:
      state.status === "signing" ||
      state.status === "uploading" ||
      state.status === "confirming" ||
      state.status === "complete",
  });

  // ── upload flow ───────────────────────────────────────────────────────────

  async function startUpload() {
    if (state.status !== "ready") return;
    const file = state.file;

    try {
      const token = await getToken();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      };

      // Step 1 — get presigned URL
      setState({ status: "signing" });
      const presignRes = await fetch(`${apiBase}/uploads/presign`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          release_id: releaseId,
          file_type: fileType,
        }),
      });
      if (!presignRes.ok) {
        const err = await presignRes.json().catch(() => ({}));
        throw new Error(err.detail ?? `Presign failed (${presignRes.status})`);
      }
      const { upload_url, object_key } = await presignRes.json();

      // Step 2 — upload directly to S3
      setState({ status: "uploading", file, progress: 0 });
      await uploadToS3(upload_url, file, (pct) =>
        setState({ status: "uploading", file, progress: pct })
      );

      // Step 3 — confirm
      setState({ status: "confirming" });
      const confirmRes = await fetch(`${apiBase}/uploads/confirm`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          object_key,
          release_id: releaseId,
          file_type: fileType,
        }),
      });
      if (!confirmRes.ok) {
        const err = await confirmRes.json().catch(() => ({}));
        throw new Error(err.detail ?? `Confirm failed (${confirmRes.status})`);
      }
      const confirmData = await confirmRes.json();

      const result: ConfirmResult = {
        releaseId: confirmData.release_id,
        objectKey: confirmData.object_key,
        artifactUrl: confirmData.artifact_url,
        scanId: confirmData.scan_id ?? null,
      };
      setState({ status: "complete", result });
      onUploadComplete?.(result);
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : "Upload failed",
      });
    }
  }

  function reset() {
    setState({ status: "idle" });
  }

  // ── render ────────────────────────────────────────────────────────────────

  if (state.status === "complete") {
    return (
      <div
        className={cn(
          "flex flex-col items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-6 text-center",
          className
        )}
      >
        <CheckCircle2 className="h-8 w-8 text-emerald-500" />
        <div>
          <p className="text-sm font-medium text-emerald-800">
            {config.label} uploaded successfully
          </p>
          {state.result.scanId && (
            <p className="mt-0.5 text-xs text-emerald-600">
              Scan {state.result.scanId.slice(0, 8)}… queued
            </p>
          )}
        </div>
        <button
          onClick={reset}
          className="text-xs text-emerald-700 underline underline-offset-2 hover:text-emerald-900"
        >
          Upload another
        </button>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div
        className={cn(
          "flex flex-col items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-6 text-center",
          className
        )}
      >
        <XCircle className="h-8 w-8 text-red-400" />
        <div>
          <p className="text-sm font-medium text-red-800">Upload failed</p>
          <p className="mt-0.5 text-xs text-red-600">{state.message}</p>
        </div>
        <button
          onClick={reset}
          className="text-xs text-red-700 underline underline-offset-2 hover:text-red-900"
        >
          Try again
        </button>
      </div>
    );
  }

  const isActive =
    state.status === "signing" ||
    state.status === "uploading" ||
    state.status === "confirming";

  return (
    <div className={cn("space-y-3", className)}>
      {/* Drop target */}
      <div
        {...getRootProps()}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-3 rounded-lg border-2 border-dashed p-6 text-center transition-colors",
          isDragActive
            ? "border-indigo-400 bg-indigo-50"
            : state.status === "ready"
            ? "border-indigo-300 bg-slate-50"
            : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50",
          isActive && "pointer-events-none opacity-60"
        )}
      >
        <input {...getInputProps()} />
        <Icon
          className={cn(
            "h-8 w-8",
            isDragActive ? "text-indigo-500" : "text-slate-300"
          )}
        />
        <div>
          <p className="text-sm font-medium text-slate-700">
            {isDragActive
              ? `Drop ${config.label.toLowerCase()} here`
              : state.status === "ready"
              ? state.file.name
              : `Drag & drop ${config.label.toLowerCase()} or click to browse`}
          </p>
          <p className="mt-0.5 text-xs text-slate-400">
            {state.status === "ready"
              ? formatBytes(state.file.size)
              : config.hint}
          </p>
        </div>
      </div>

      {/* Validation errors */}
      {state.status === "rejected" && (
        <ul className="space-y-1">
          {state.errors.map((e, i) => (
            <li key={i} className="text-xs text-red-600">
              {e}
            </li>
          ))}
        </ul>
      )}

      {/* Progress bar */}
      {state.status === "uploading" && (
        <div className="space-y-1">
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-indigo-500 transition-all duration-150"
              style={{ width: `${state.progress}%` }}
            />
          </div>
          <p className="text-right text-xs text-slate-400">
            {state.progress}%
          </p>
        </div>
      )}

      {/* Status label for non-upload active states */}
      {(state.status === "signing" || state.status === "confirming") && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {state.status === "signing"
            ? "Preparing upload…"
            : "Finalizing…"}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2">
        {state.status === "ready" && (
          <button
            onClick={startUpload}
            className="flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
          >
            <Upload className="h-4 w-4" />
            Upload {config.label}
          </button>
        )}
        {(state.status === "ready" || state.status === "rejected") && (
          <button
            onClick={reset}
            className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
