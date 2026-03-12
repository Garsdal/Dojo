import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { StateBadge } from "@/components/state-badge";
import { FlaskConical, Wrench, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Domain } from "@/types";

const accentColors: Record<string, string> = {
  active: "bg-muted-teal",
  completed: "bg-muted-teal",
  draft: "bg-wheat",
  paused: "bg-wheat",
  failed: "bg-danger",
  stopped: "bg-danger",
  pending: "bg-grey/40",
  archived: "bg-grey/40",
};

interface DomainCardProps {
  domain: Domain;
}

export function DomainCard({ domain }: DomainCardProps) {
  const navigate = useNavigate();
  const accentColor = accentColors[domain.status] ?? "bg-grey/40";

  return (
    <Card
      className="cursor-pointer hover:shadow-md hover:border-soft-fawn/40 transition-all relative overflow-hidden pl-2 animate-fade-in"
      onClick={() => navigate(`/domains/${domain.id}`)}
    >
      <div className={cn("absolute left-0 top-0 bottom-0 w-1.5 rounded-l-2xl", accentColor)} />
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <span className="font-heading font-bold text-blackberry text-base leading-tight">
            {domain.name}
          </span>
          <StateBadge state={domain.status} />
        </div>
        {domain.description && (
          <p className="text-grey text-sm line-clamp-2 mt-1">{domain.description}</p>
        )}
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex items-center gap-3 text-xs text-grey">
          <span className="flex items-center gap-1">
            <FlaskConical className="h-3 w-3" />
            {domain.experiment_ids.length} experiments
          </span>
          <span className="flex items-center gap-1">
            <Wrench className="h-3 w-3" />
            {domain.tools.length} tools
          </span>
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-xs text-grey">
            {new Date(domain.created_at).toLocaleDateString()}
          </span>
          <ArrowRight className="h-3 w-3 text-grey/50" />
        </div>
      </CardContent>
    </Card>
  );
}
