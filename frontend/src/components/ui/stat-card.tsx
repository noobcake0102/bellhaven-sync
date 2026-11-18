// 21st.dev: ravikatiyar162/card-10 (Stat Card). A key metric with a count-up animation.
// Adapted: the trend line is replaced by a coloured tone and a one-line hint; the card is clickable.
import * as React from "react";
import { motion, useSpring, useTransform, animate } from "motion/react";
import { cn } from "@/lib/utils";

interface StatCardProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  title: string; value: number; hint: string; tone?: "neutral" | "green" | "yellow" | "red"; active?: boolean;
}

const TONE = { neutral: "bg-primary", green: "bg-green-600", yellow: "bg-amber-500", red: "bg-red-600" };

export const StatCard = React.forwardRef<HTMLButtonElement, StatCardProps>(({ title, value, hint, tone = "neutral", active, className, ...props }, ref) => {
  const motionValue = useSpring(0, { damping: 100, stiffness: 100 });
  const displayValue = useTransform(motionValue, (latest) => Math.round(latest).toLocaleString());
  React.useEffect(() => { const controls = animate(motionValue, value, { duration: 0.9, ease: "easeOut" }); return controls.stop; }, [value, motionValue]);

  return (
    <button ref={ref} type="button" aria-label={`${title}: ${value}. ${hint}`} {...props}
      className={cn("group flex cursor-pointer flex-col gap-1 rounded-xl border bg-card p-4 text-left text-card-foreground shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active && "ring-2 ring-ring", className)}>
      <div className="flex items-center gap-2">
        <span className={cn("size-2.5 rounded-full", TONE[tone])} />
        <p className="text-sm font-medium text-muted-foreground">{title}</p>
      </div>
      <motion.h3 className="font-semibold text-4xl tracking-tighter tabular-nums">{displayValue}</motion.h3>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </button>
  );
});
StatCard.displayName = "StatCard";
