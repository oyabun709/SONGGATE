import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "bg-slate-100 text-slate-900",
        critical: "bg-red-100 text-red-700",
        warning: "bg-amber-100 text-amber-700",
        info: "bg-blue-50 text-blue-700",
        pass: "bg-emerald-100 text-emerald-700",
        warn: "bg-amber-100 text-amber-700",
        fail: "bg-red-100 text-red-700",
        fraud: "bg-red-50 text-red-800 border border-red-200",
        enrichment: "bg-emerald-50 text-emerald-800 border border-emerald-200",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
