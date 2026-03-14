import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import type { MetricPoint } from "@/types";

interface MetricsResponse {
  domain_id: string;
  metrics_evolution: MetricPoint[];
}

export function useDomainMetrics(domainId: string | undefined) {
  return useSWR<MetricPoint[]>(
    domainId ? `/domains/${domainId}/metrics` : null,
    (url: string) =>
      apiFetch<MetricsResponse>(url).then((r) => r.metrics_evolution),
  );
}
