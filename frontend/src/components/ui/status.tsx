// 21st.dev: diceui/status. Pill-shaped status badge with a pulsing indicator dot.
// Adapted: variants renamed to this app's three check colours; asChild removed.
import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

const statusVariants = cva(
  "inline-flex w-fit shrink-0 items-center gap-1.5 overflow-hidden whitespace-nowrap rounded-full border px-2.5 py-1 font-medium text-xs transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-muted text-muted-foreground **:data-[slot=status-indicator]:bg-muted-foreground",
        green: "border-green-600/20 bg-green-600/10 text-green-700 **:data-[slot=status-indicator]:bg-green-600",
        red: "border-red-600/25 bg-red-600/10 text-red-700 **:data-[slot=status-indicator]:bg-red-600",
        yellow: "border-amber-500/30 bg-amber-400/15 text-amber-700 **:data-[slot=status-indicator]:bg-amber-500",
        info: "border-sky-600/20 bg-sky-600/10 text-sky-700 **:data-[slot=status-indicator]:bg-sky-600",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

interface StatusProps extends VariantProps<typeof statusVariants>, React.ComponentProps<"div"> {}

function Status({ className, variant = "default", ...props }: StatusProps) {
  return <div data-slot="status" data-variant={variant} {...props} className={cn(statusVariants({ variant }), className)} />;
}

function StatusIndicator({ className, pulse = true, ...props }: React.ComponentProps<"div"> & { pulse?: boolean }) {
  return (
    <div
      data-slot="status-indicator"
      {...props}
      className={cn(
        "relative flex size-2 shrink-0 rounded-full",
        pulse && "before:absolute before:inset-0 before:animate-ping before:rounded-full before:bg-inherit",
        "after:absolute after:inset-[2px] after:rounded-full after:bg-inherit",
        className,
      )}
    />
  );
}

function StatusLabel({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="status-label" {...props} className={cn("leading-none", className)} />;
}

export { Status, StatusIndicator, StatusLabel, statusVariants };
