import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const stateStyles: Record<string, string> = {
  draft: "bg-soft-fawn/20 text-soft-fawn border-0",
  pending: "bg-grey/15 text-grey border-0",
  running: "bg-wheat/50 text-blackberry border-0 animate-pulse",
  active: "bg-muted-teal/20 text-muted-teal border-0",
  paused: "bg-wheat/30 text-blackberry border-0",
  completed: "bg-muted-teal/20 text-muted-teal border-0",
  failed: "bg-danger/15 text-danger border-0",
  stopped: "bg-danger/15 text-danger border-0",
  archived: "bg-grey/10 text-grey border-0",
};

export function StateBadge({ state }: { state: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-xs capitalize rounded-full px-2.5",
        stateStyles[state] ?? stateStyles.pending,
      )}
    >
      {state}
    </Badge>
  );
}
