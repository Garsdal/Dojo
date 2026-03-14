import useSWR from "swr";
import { apiFetch } from "@/lib/api";

export interface WorkspaceStatus {
  configured: boolean;
  ready?: boolean;
  path?: string;
  python_path?: string | null;
  source?: string;
  error?: string;
}

export interface WorkspaceScanSuggestion {
  name: string;
  description: string;
  type: string;
  code: string;
  example_usage: string;
  parameters: Record<string, unknown>;
}

export interface WorkspaceScanResult {
  summary: {
    data_files: string[];
    python_modules: string[];
    has_requirements: boolean;
    has_pyproject: boolean;
  };
  suggestions: WorkspaceScanSuggestion[];
}

/**
 * Fetch workspace status for a domain.
 * Note: The domain detail page reads workspace.ready from the existing useDomain
 * response, so this hook is not consumed there. It is exported here for future use
 * (e.g. polling after triggering a long-running setup).
 */
export function useWorkspaceStatus(domainId: string | undefined) {
  return useSWR<WorkspaceStatus>(
    domainId ? `/domains/${domainId}/workspace/status` : null,
    (url: string) => apiFetch<WorkspaceStatus>(url),
  );
}

export async function setupWorkspace(
  domainId: string,
): Promise<{ status: string; path: string; python_path: string | null }> {
  return apiFetch(`/domains/${domainId}/workspace/setup`, { method: "POST" });
}

export async function scanWorkspace(domainId: string): Promise<WorkspaceScanResult> {
  return apiFetch(`/domains/${domainId}/workspace/scan`, { method: "POST" });
}
