"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

const placeholder = [
  { name: "Mon", passed: 0, failed: 0 },
  { name: "Tue", passed: 0, failed: 0 },
  { name: "Wed", passed: 0, failed: 0 },
  { name: "Thu", passed: 0, failed: 0 },
  { name: "Fri", passed: 0, failed: 0 },
  { name: "Sat", passed: 0, failed: 0 },
  { name: "Sun", passed: 0, failed: 0 },
];

export function PipelineHealth() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold text-slate-900">
        Pipeline Health (7d)
      </h2>
      <div className="mt-4 h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={placeholder} barSize={12} barGap={4}>
            <XAxis
              dataKey="name"
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#94a3b8" }}
              axisLine={false}
              tickLine={false}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                fontSize: 12,
                borderRadius: 6,
                border: "1px solid #e2e8f0",
              }}
            />
            <Bar dataKey="passed" fill="#6366f1" radius={[2, 2, 0, 0]} />
            <Bar dataKey="failed" fill="#f87171" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-indigo-500" /> Passed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-red-400" /> Failed
        </span>
      </div>
    </div>
  );
}
