import { Badge } from "@/components/ui/badge";
import { useHealth } from "@/hooks/use-health";
import { cn } from "@/lib/utils";
import { FlaskConical } from "lucide-react";

export function Header() {
  const { data, error } = useHealth();
  const isHealthy = !!data && !error && data.status === "ok";

  return (
    <header className="flex items-center justify-between h-14 px-6 border-b border-soft-fawn/20 bg-surface">
      <div className="flex items-center gap-2.5">
        <FlaskConical className="h-5 w-5 text-muted-teal" />
        <span className="font-heading font-extrabold text-blackberry text-xl tracking-tight">AgentML</span>
        <Badge className="bg-wheat/30 text-blackberry border-0 text-xs">
          v0.1.0
        </Badge>
      </div>
      <div className="flex items-center gap-2">
        <div
          className={cn(
            "h-2 w-2 rounded-full",
            isHealthy ? "bg-muted-teal" : "bg-danger",
          )}
        />
        <span className="text-xs text-grey">
          {isHealthy ? "Connected" : "Disconnected"}
        </span>
      </div>
    </header>
  );
}
