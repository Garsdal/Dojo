import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import type { CodeRun, CodeRunDetail } from "@/types";

/**
 * Fetch all code runs for an experiment.
 * Pass `enabled=false` to skip fetching (e.g. when the Code tab is not active).
 */
export function useExperimentCode(
  experimentId: string | undefined,
  enabled: boolean,
) {
  return useSWR<CodeRun[]>(
    experimentId && enabled ? `/experiments/${experimentId}/code` : null,
    (url: string) => apiFetch<CodeRun[]>(url),
  );
}

/**
 * Fetch the source code + metadata for a specific code run.
 * Pass `runNumber=null` to skip fetching (e.g. when no run is expanded).
 */
export function useExperimentCodeRun(
  experimentId: string | undefined,
  runNumber: number | null,
) {
  return useSWR<CodeRunDetail>(
    experimentId && runNumber !== null
      ? `/experiments/${experimentId}/code/${runNumber}`
      : null,
    (url: string) => apiFetch<CodeRunDetail>(url),
  );
}
