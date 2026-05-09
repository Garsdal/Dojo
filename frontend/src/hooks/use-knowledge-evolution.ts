import { useMemo } from "react";
import type { KnowledgeAtom } from "@/types";

export interface KnowledgeEvolutionPoint {
  index: number;
  label: string;
  atomId: string;
  cumulative: number;
  isUpdate: boolean;
  confidence: number;
}

/**
 * Derives a knowledge evolution timeline from atom data.
 *
 * Atoms are immutable-append, so every entry is "new" — cumulative is just
 * the running atom count, and ``isUpdate`` is always false. The shape is
 * preserved for the chart consumer; ``isUpdate`` may regain meaning if the
 * model adds explicit supersession links later.
 */
export function useKnowledgeEvolution(atoms: KnowledgeAtom[] | undefined): KnowledgeEvolutionPoint[] {
  return useMemo(() => {
    if (!atoms || atoms.length === 0) return [];

    return atoms.map((atom, i) => ({
      index: i + 1,
      label: `#${i + 1}`,
      atomId: atom.id,
      cumulative: i + 1,
      isUpdate: false,
      confidence: atom.confidence,
    }));
  }, [atoms]);
}
