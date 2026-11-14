import { type HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "bg-teal-soft text-teal",
        neutral: "bg-base-panel text-fg-muted border border-border",
        success: "bg-[rgba(34,197,94,0.12)] text-ok",
        warning: "bg-[rgba(245,158,11,0.12)] text-warn",
        danger: "bg-[rgba(239,68,68,0.12)] text-danger",
        info: "bg-[rgba(96,165,250,0.12)] text-info",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps extends HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

const STATUS_VARIANT: Record<string, VariantProps<typeof badgeVariants>["variant"]> = {
  pass: "success",
  completed: "success",
  fail: "danger",
  failed: "danger",
  borderline: "warning",
  pending: "info",
  running: "info",
  submitted: "success",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge variant={STATUS_VARIANT[status] ?? "neutral"} className={className}>
      {status.replace(/_/g, " ")}
    </Badge>
  );
}
