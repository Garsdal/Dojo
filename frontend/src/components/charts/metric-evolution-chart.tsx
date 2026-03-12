import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { cn } from "@/lib/utils";
import type { MetricPoint } from "@/types";

interface MetricEvolutionChartProps {
  data: MetricPoint[] | undefined;
  isLoading: boolean;
}

interface TooltipPayloadEntry {
  value: number;
  payload: { expId: string };
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-soft-fawn/30 rounded-xl px-3 py-2 shadow-sm text-xs">
      <div className="font-semibold text-blackberry">{payload[0].value.toFixed(4)}</div>
      <div className="text-grey">exp: {payload[0].payload.expId}…</div>
    </div>
  );
}

export function MetricEvolutionChart({ data, isLoading }: MetricEvolutionChartProps) {
  const metricKeys = useMemo(() => {
    if (!data) return [];
    const keys = new Set<string>();
    data.forEach((p) => Object.keys(p.metrics).forEach((k) => keys.add(k)));
    return Array.from(keys).sort();
  }, [data]);

  const [selectedMetric, setSelectedMetric] = useState<string>(metricKeys[0] ?? "");

  const chartData = useMemo(() => {
    if (!data) return [];
    return data
      .filter((p) => selectedMetric in p.metrics)
      .map((p, i) => ({
        index: i + 1,
        value: p.metrics[selectedMetric],
        expId: p.experiment_id.slice(0, 8),
      }));
  }, [data, selectedMetric]);

  if (isLoading) {
    return <p className="text-sm text-grey">Loading…</p>;
  }

  if (!data || data.length === 0) {
    return (
      <p className="text-sm text-grey">
        No metrics yet. Metrics appear after experiments complete.
      </p>
    );
  }

  if (metricKeys.length === 0) {
    return <p className="text-sm text-grey">No numeric metrics recorded.</p>;
  }

  return (
    <div className="space-y-4">
      {/* Metric selector pills */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {metricKeys.map((key) => (
          <button
            key={key}
            onClick={() => setSelectedMetric(key)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium transition-all",
              key === selectedMetric
                ? "bg-wheat/50 text-blackberry font-semibold"
                : "text-grey hover:text-blackberry hover:bg-wheat/20",
            )}
          >
            {key}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="bg-white rounded-2xl border border-soft-fawn/20 p-4">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(214,186,115,0.15)" />
            <XAxis
              dataKey="index"
              tick={{ fontSize: 10, fill: "#857E7B" }}
              tickLine={false}
              axisLine={{ stroke: "rgba(214,186,115,0.2)" }}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#857E7B" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => v.toFixed(2)}
            />
            <Tooltip content={<CustomTooltip />} />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#59344F"
              strokeWidth={2}
              dot={{ r: 3, fill: "#59344F", strokeWidth: 0 }}
              activeDot={{ r: 5, fill: "#8BBF9F", strokeWidth: 0 }}
            />
          </LineChart>
        </ResponsiveContainer>
        <div className="text-center mt-1">
          <span className="text-xs text-grey font-medium">{selectedMetric}</span>
        </div>
      </div>
    </div>
  );
}
