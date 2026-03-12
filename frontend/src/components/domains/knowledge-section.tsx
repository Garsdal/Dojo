import { useState, useMemo } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { KnowledgeAtom } from "@/types";

interface KnowledgeSectionProps {
  atoms: KnowledgeAtom[] | undefined;
  isLoading: boolean;
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return "bg-muted-teal";
  if (confidence >= 0.4) return "bg-wheat";
  return "bg-danger";
}

export function KnowledgeSection({ atoms, isLoading }: KnowledgeSectionProps) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!atoms) return [];
    const q = search.toLowerCase();
    if (!q) return atoms;
    return atoms.filter(
      (a) =>
        a.claim.toLowerCase().includes(q) ||
        a.context.toLowerCase().includes(q),
    );
  }, [atoms, search]);

  if (isLoading) {
    return <p className="text-sm text-grey">Loading…</p>;
  }

  if (!atoms || atoms.length === 0) {
    return (
      <p className="text-sm text-grey">
        No knowledge yet. The agent will accumulate knowledge during research runs.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-grey" />
        <Input
          placeholder="Search claims and context…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9 text-sm"
        />
      </div>

      {/* Results count */}
      {search && (
        <p className="text-xs text-grey">
          {filtered.length} of {atoms.length} results
        </p>
      )}

      {/* Knowledge cards */}
      {filtered.length === 0 && search ? (
        <p className="text-sm text-grey py-4 text-center">No matching knowledge found.</p>
      ) : (
        <div className="space-y-2">
          {filtered.map((atom) => (
            <div
              key={atom.id}
              className="flex gap-3 bg-white rounded-xl border border-soft-fawn/20 p-3 hover:border-soft-fawn/40 transition-colors"
            >
              {/* Confidence bar */}
              <div className="flex flex-col items-center gap-0.5 shrink-0 pt-0.5">
                <div className={cn("w-1 rounded-full", confidenceColor(atom.confidence))} style={{ height: "100%", minHeight: "40px" }} />
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0 space-y-1">
                <p className="text-sm font-medium text-blackberry leading-snug">
                  {atom.claim}
                </p>
                <p className="text-xs text-grey line-clamp-2">{atom.context}</p>
                {atom.action && (
                  <p className="text-xs text-grey/70 italic">→ {atom.action}</p>
                )}
              </div>

              {/* Right side: badges */}
              <div className="flex flex-col items-end gap-1 shrink-0">
                <span className="text-xs font-semibold text-blackberry">
                  {Math.round(atom.confidence * 100)}%
                </span>
                <span className="text-[10px] text-grey bg-wheat/20 rounded-full px-1.5 py-0.5">
                  v{atom.version}
                </span>
                {atom.evidence_ids.length > 0 && (
                  <span className="text-[10px] text-grey">
                    {atom.evidence_ids.length} evidence
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
