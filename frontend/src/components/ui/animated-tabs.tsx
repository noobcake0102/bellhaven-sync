// 21st.dev: educalvolpz/animated-tabs. Tabs with a sliding indicator and keyboard navigation.
// Adapted: optional count badge per tab.
import { cn } from "@/lib/utils";
import { motion, useReducedMotion } from "motion/react";
import { type ReactNode, useCallback } from "react";

export interface AnimatedTabsProps {
  activeTab: string;
  className?: string;
  layoutId?: string;
  onChange: (tabId: string) => void;
  tabs: { id: string; label: string; icon?: ReactNode; count?: number }[];
}

const SPRING = { bounce: 0.05, duration: 0.25, type: "spring" as const };

export default function AnimatedTabs({ tabs, activeTab, onChange, layoutId = "tabs", className }: AnimatedTabsProps) {
  const shouldReduceMotion = useReducedMotion();

  const handleKeyDown = useCallback((event: React.KeyboardEvent, currentIndex: number) => {
    let newIndex = currentIndex;
    if (event.key === "ArrowRight") newIndex = (currentIndex + 1) % tabs.length;
    else if (event.key === "ArrowLeft") newIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") newIndex = 0;
    else if (event.key === "End") newIndex = tabs.length - 1;
    else return;
    event.preventDefault();
    const newTab = tabs[newIndex];
    if (newTab) { onChange(newTab.id); document.getElementById(`${layoutId}-tab-${newTab.id}`)?.focus(); }
  }, [tabs, onChange, layoutId]);

  return (
    <div aria-label="Sections" role="tablist" className={cn("relative inline-flex max-w-full gap-0 overflow-x-auto rounded-lg bg-muted p-1", className)}>
      {tabs.map((tab, index) => {
        const isActive = activeTab === tab.id;
        return (
          <button key={tab.id} id={`${layoutId}-tab-${tab.id}`} role="tab" type="button" aria-selected={isActive} tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(tab.id)} onKeyDown={(e) => handleKeyDown(e, index)}
            className={cn("relative z-10 flex flex-1 cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-md px-4 py-2 font-medium text-sm transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
            {isActive && (
              <motion.span layout layoutId={layoutId} style={{ originY: "0px" }} transition={shouldReduceMotion ? { duration: 0 } : SPRING}
                className="absolute inset-0 rounded-md border border-border bg-card shadow-sm" />
            )}
            {tab.icon ? <span className="relative z-10">{tab.icon}</span> : null}
            <span className="relative z-10">{tab.label}</span>
            {tab.count !== undefined && (
              <span className={cn("relative z-10 rounded-full px-1.5 py-0.5 font-mono text-[11px] leading-none", isActive ? "bg-primary text-primary-foreground" : "bg-border text-muted-foreground")}>{tab.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
