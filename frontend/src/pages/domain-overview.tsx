import { useState } from "react";
import { useDomains, createDomain } from "@/hooks/use-domains";
import { DomainCard } from "@/components/domains/domain-card";
import { DomainForm } from "@/components/domains/domain-form";
import { cn } from "@/lib/utils";
import { LayoutGrid } from "lucide-react";

type Filter = "all" | "active" | "draft" | "archived";

const filters: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "draft", label: "Draft" },
  { value: "archived", label: "Archived" },
];

export default function DomainOverviewPage() {
  const { data: domains, isLoading, mutate } = useDomains();
  const [isCreating, setIsCreating] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

  const handleCreate = async (data: {
    name: string;
    description: string;
    prompt: string;
  }) => {
    setIsCreating(true);
    try {
      await createDomain(data);
      await mutate();
    } finally {
      setIsCreating(false);
    }
  };

  const filteredDomains =
    domains?.filter((d) => {
      if (filter === "all") return true;
      if (filter === "active")
        return d.status === "active" || d.status === "paused";
      if (filter === "draft") return d.status === "draft";
      if (filter === "archived") return d.status === "archived";
      return true;
    }) ?? [];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-heading font-extrabold text-blackberry text-[1.75rem] leading-tight">
            Research Domains
          </h1>
          <p className="text-grey text-sm mt-1">Manage your AI research domains</p>
        </div>
        <DomainForm onSubmit={handleCreate} isLoading={isCreating} />
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-1 bg-wheat/15 rounded-xl p-1 w-fit">
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={cn(
              "px-4 py-1.5 rounded-lg text-sm font-medium transition-all",
              filter === f.value
                ? "bg-white text-blackberry shadow-sm font-semibold"
                : "text-grey hover:text-blackberry",
            )}
          >
            {f.label}
            {domains && f.value !== "all" && (
              <span className="ml-1.5 text-xs opacity-60">
                {
                  domains.filter((d) => {
                    if (f.value === "active")
                      return d.status === "active" || d.status === "paused";
                    if (f.value === "draft") return d.status === "draft";
                    if (f.value === "archived") return d.status === "archived";
                    return false;
                  }).length
                }
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Loading */}
      {isLoading && <p className="text-sm text-grey">Loading domains…</p>}

      {/* Empty state */}
      {!isLoading && filteredDomains.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <LayoutGrid className="h-12 w-12 text-grey/30 mb-4" />
          <p className="text-grey mb-2 font-medium">No domains found</p>
          <p className="text-grey/70 text-sm">
            {filter !== "all"
              ? `No ${filter} domains. Try a different filter.`
              : "Create your first research domain to get started."}
          </p>
        </div>
      )}

      {/* Domain Grid */}
      {filteredDomains.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredDomains.map((domain) => (
            <DomainCard key={domain.id} domain={domain} />
          ))}
        </div>
      )}
    </div>
  );
}
