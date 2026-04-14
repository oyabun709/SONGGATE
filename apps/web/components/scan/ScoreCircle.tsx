"use client";

import { cn } from "@/lib/utils";

interface ScoreCircleProps {
  score: number | null;
  grade: "PASS" | "WARN" | "FAIL" | null;
  size?: "sm" | "md" | "lg";
  animated?: boolean;
  className?: string;
}

const SIZE_MAP = {
  sm: { container: 80, stroke: 6, r: 31 },
  md: { container: 140, stroke: 10, r: 54 },
  lg: { container: 200, stroke: 12, r: 82 },
};

const GRADE_COLORS = {
  PASS: {
    track: "#d1fae5",
    fill: "#10b981",
    text: "text-emerald-600",
    label: "bg-emerald-100 text-emerald-700",
  },
  WARN: {
    track: "#fef3c7",
    fill: "#f59e0b",
    text: "text-amber-600",
    label: "bg-amber-100 text-amber-700",
  },
  FAIL: {
    track: "#fee2e2",
    fill: "#ef4444",
    text: "text-red-600",
    label: "bg-red-100 text-red-700",
  },
  null: {
    track: "#e2e8f0",
    fill: "#94a3b8",
    text: "text-slate-400",
    label: "bg-slate-100 text-slate-500",
  },
};

export function ScoreCircle({
  score,
  grade,
  size = "lg",
  animated = true,
  className,
}: ScoreCircleProps) {
  const { container, stroke, r } = SIZE_MAP[size];
  const cx = container / 2;
  const cy = container / 2;
  const circumference = 2 * Math.PI * r;
  const pct = score !== null ? Math.max(0, Math.min(100, score)) / 100 : 0;
  const dashoffset = circumference * (1 - pct);

  const colors = GRADE_COLORS[grade ?? "null"];

  const textSizeClass =
    size === "lg"
      ? "text-5xl"
      : size === "md"
      ? "text-3xl"
      : "text-xl";

  return (
    <div
      className={cn("flex flex-col items-center gap-3", className)}
      role="img"
      aria-label={`Readiness score: ${score ?? "—"} — ${grade ?? "pending"}`}
    >
      {/* SVG circle */}
      <div className="relative" style={{ width: container, height: container }}>
        <svg
          width={container}
          height={container}
          viewBox={`0 0 ${container} ${container}`}
          style={{ transform: "rotate(-90deg)" }}
        >
          {/* Background track */}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={colors.track}
            strokeWidth={stroke}
          />
          {/* Progress arc */}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={colors.fill}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashoffset}
            style={
              animated
                ? { transition: "stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)" }
                : undefined
            }
          />
        </svg>

        {/* Score text centered */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("font-bold tabular-nums leading-none", textSizeClass, colors.text)}>
            {score !== null ? Math.round(score) : "—"}
          </span>
          {size !== "sm" && (
            <span className="mt-1 text-xs font-medium text-slate-400 uppercase tracking-wider">
              Score
            </span>
          )}
        </div>
      </div>

      {/* Grade badge */}
      {grade !== null && (
        <span
          className={cn(
            "rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider",
            colors.label
          )}
        >
          {grade}
        </span>
      )}
      {grade === null && score === null && (
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-400">
          Pending
        </span>
      )}
    </div>
  );
}
