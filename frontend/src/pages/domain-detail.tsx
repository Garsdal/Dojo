import { useParams, useNavigate } from "react-router-dom";
import { useDomain, updateDomain } from "@/hooks/use-domain";
import { useDomainExperiments } from "@/hooks/use-domain-experiments";
import { useDomainKnowledge } from "@/hooks/use-domain-knowledge";
import { useDomainMetrics } from "@/hooks/use-domain-metrics";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StateBadge } from "@/components/state-badge";
import { Breadcrumb } from "@/components/layout/breadcrumb";
import { ExperimentsSection } from "@/components/domains/experiments-section";
import { KnowledgeSection } from "@/components/domains/knowledge-section";
import { ToolsSection } from "@/components/domains/tools-section";
import { AgentSection } from "@/components/domains/agent-section";
import { MetricEvolutionChart } from "@/components/charts/metric-evolution-chart";
import {
  PauseCircle,
  PlayCircle,
  CheckCircle,
  Archive,
  Bot,
  FlaskConical,
  Brain,
  BarChart3,
  Wrench,
} from "lucide-react";

export default function DomainDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: domain, isLoading, mutate } = useDomain(id);
  const { data: experiments, isLoading: expLoading } = useDomainExperiments(id);
  const { data: knowledge, isLoading: knLoading } = useDomainKnowledge(id);
  const { data: metrics, isLoading: metLoading } = useDomainMetrics(id);

  if (isLoading) {
    return <p className="text-sm text-grey">Loading domain…</p>;
  }

  if (!domain) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-grey">Domain not found.</p>
        <Button variant="ghost" onClick={() => navigate("/")}>
          ← Back to domains
        </Button>
      </div>
    );
  }

  const handleStatusChange = async (status: string) => {
    await updateDomain(domain.id, { status });
    await mutate();
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: "Domains", href: "/" },
          { label: domain.name },
        ]}
      />

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="font-heading font-extrabold text-blackberry text-[1.75rem] leading-tight">
              {domain.name}
            </h1>
            <StateBadge state={domain.status} />
          </div>
          {domain.description && (
            <p className="text-grey text-sm mt-1">{domain.description}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {domain.status === "active" && (
            <Button variant="outline" size="sm" onClick={() => handleStatusChange("paused")}>
              <PauseCircle className="h-4 w-4" />
              Pause
            </Button>
          )}
          {domain.status === "paused" && (
            <Button variant="outline" size="sm" onClick={() => handleStatusChange("active")}>
              <PlayCircle className="h-4 w-4" />
              Resume
            </Button>
          )}
          {(domain.status === "active" || domain.status === "paused") && (
            <Button variant="outline" size="sm" onClick={() => handleStatusChange("completed")}>
              <CheckCircle className="h-4 w-4" />
              Complete
            </Button>
          )}
          {domain.status !== "archived" && (
            <Button variant="ghost" size="sm" onClick={() => handleStatusChange("archived")}>
              <Archive className="h-4 w-4" />
              Archive
            </Button>
          )}
        </div>
      </div>

      {/* Stat strip */}
      <div className="flex items-center gap-0 bg-wheat/10 rounded-xl overflow-hidden border border-soft-fawn/20">
        {[
          { label: "Experiments", value: domain.experiment_ids.length },
          { label: "Knowledge", value: knowledge?.length ?? "—" },
          { label: "Tools", value: domain.tools.length },
          { label: "Created", value: new Date(domain.created_at).toLocaleDateString() },
        ].map((stat, i) => (
          <div
            key={stat.label}
            className={`flex-1 px-5 py-3 ${i < 3 ? "border-r border-soft-fawn/20" : ""}`}
          >
            <div className="text-xs text-grey font-medium">{stat.label}</div>
            <div className="text-lg font-bold text-blackberry mt-0.5">{stat.value}</div>
          </div>
        ))}
      </div>

      {/* Tabbed content */}
      <Tabs defaultValue="agent" className="space-y-4">
        <TabsList>
          <TabsTrigger value="agent" className="flex items-center gap-1.5">
            <Bot className="h-3.5 w-3.5" />
            Agent
          </TabsTrigger>
          <TabsTrigger value="experiments" className="flex items-center gap-1.5">
            <FlaskConical className="h-3.5 w-3.5" />
            Experiments
          </TabsTrigger>
          <TabsTrigger value="knowledge" className="flex items-center gap-1.5">
            <Brain className="h-3.5 w-3.5" />
            Knowledge
          </TabsTrigger>
          <TabsTrigger value="metrics" className="flex items-center gap-1.5">
            <BarChart3 className="h-3.5 w-3.5" />
            Metrics
          </TabsTrigger>
          <TabsTrigger value="tools" className="flex items-center gap-1.5">
            <Wrench className="h-3.5 w-3.5" />
            Tools
          </TabsTrigger>
        </TabsList>

        <TabsContent value="agent">
          <AgentSection domainId={domain.id} />
        </TabsContent>

        <TabsContent value="experiments">
          <ExperimentsSection experiments={experiments} isLoading={expLoading} />
        </TabsContent>

        <TabsContent value="knowledge">
          <KnowledgeSection atoms={knowledge} isLoading={knLoading} />
        </TabsContent>

        <TabsContent value="metrics">
          <MetricEvolutionChart data={metrics} isLoading={metLoading} />
        </TabsContent>

        <TabsContent value="tools">
          <ToolsSection domainId={domain.id} tools={domain.tools} onMutate={() => mutate()} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
