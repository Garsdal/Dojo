import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { useKnowledgeDetail } from "@/hooks/use-domain-knowledge";
import type { KnowledgeAtom } from "@/types";

interface KnowledgeAtomCardProps {
  atom: KnowledgeAtom;
  domainBadge?: string;
  onEvidenceClick?: (experimentId: string) => void;
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return "bg-muted-teal";
  if (confidence >= 0.4) return "bg-wheat";
  return "bg-danger";
}

function confidenceBarColor(confidence: number): string {
  if (confidence >= 0.7) return "bg-muted-teal";
  if (confidence >= 0.4) return "bg-wheat";
  return "bg-danger";
}

export function KnowledgeAtomCard({ atom, domainBadge, onEvidenceClick }: KnowledgeAtomCardProps) {
  const [expanded, setExpanded] = useState(false);
  const { data: detail } = useKnowledgeDetail(expanded ? atom.id : undefined);

  return (
    <div
      className={cn(
        "bg-white rounded-xl border transition-all",
        expanded
          ? "border-soft-fawn/40 shadow-md"
          : "border-soft-fawn/20 hover:shadow-md hover:border-soft-fawn/40",
      )}
    >
      {/* Collapsed header — always visible */}
      <button
        className="w-full flex gap-3 p-3 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Confidence dot */}
        <div className="flex items-center shrink-0 pt-0.5">
          <div className={cn("w-2 h-2 rounded-full mt-1", confidenceColor(atom.confidence))} />
        </div>

        {/* Claim + context */}
        <div className="flex-1 min-w-0 space-y-0.5">
          <p className={cn("text-sm font-medium text-blackberry leading-snug", !expanded && "line-clamp-2")}>
            {atom.claim}
          </p>
          {!expanded && (
            <p className="text-xs text-grey line-clamp-1">{atom.context}</p>
          )}
        </div>

        {/* Right: confidence % + domain badge + chevron */}
        <div className="flex flex-col items-end gap-1 shrink-0 ml-2">
          <div className="flex items-center gap-1.5">
            {domainBadge && (
              <span className="text-[10px] text-grey bg-soft-fawn/30 rounded-full px-1.5 py-0.5">
                {domainBadge}
              </span>
            )}
            <span className="text-xs font-semibold text-blackberry">
              {Math.round(atom.confidence * 100)}%
            </span>
          </div>
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5 text-grey" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-grey" />
          )}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-soft-fawn/15 pt-3">
          {/* Confidence bar */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-grey font-medium">Confidence</span>
              <span className="text-xs font-semibold text-blackberry">{Math.round(atom.confidence * 100)}%</span>
            </div>
            <div className="h-1.5 bg-soft-fawn/20 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", confidenceBarColor(atom.confidence))}
                style={{ width: `${atom.confidence * 100}%` }}
              />
            </div>
          </div>

          {/* Context */}
          <div>
            <span className="text-xs text-grey font-medium block mb-0.5">Context</span>
            <p className="text-sm text-blackberry">{atom.context}</p>
          </div>

          {/* Action */}
          {atom.action && (
            <div>
              <span className="text-xs text-grey font-medium block mb-0.5">Recommended Action</span>
              <p className="text-sm text-grey italic">→ {atom.action}</p>
            </div>
          )}

          {/* Evidence */}
          {atom.evidence_ids.length > 0 && (
            <div>
              <span className="text-xs text-grey font-medium block mb-1">
                Evidence ({atom.evidence_ids.length})
              </span>
              <div className="flex flex-wrap gap-1.5">
                {atom.evidence_ids.map((expId) => (
                  <button
                    key={expId}
                    onClick={() => onEvidenceClick?.(expId)}
                    className={cn(
                      "font-mono text-[10px] bg-wheat/20 text-blackberry rounded-full px-2 py-0.5",
                      onEvidenceClick ? "hover:bg-wheat/40 transition-colors cursor-pointer" : "",
                    )}
                  >
                    {expId.slice(0, 12)}…
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Version history from detail */}
          {detail && detail.links.length > 0 && (
            <div>
              <span className="text-xs text-grey font-medium block mb-1">
                Links ({detail.links.length})
              </span>
              <div className="flex flex-wrap gap-1.5">
                {detail.links.slice(0, 5).map((link) => (
                  <span
                    key={link.id}
                    className="text-[10px] text-grey bg-soft-fawn/20 rounded-full px-2 py-0.5"
                  >
                    {link.link_type}
                  </span>
                ))}
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  );
}
