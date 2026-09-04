import { BarChart, Bar, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, Cell } from "recharts";
import { getTrendResult } from "@/lib/trend";
import type { Direction, TrendGame } from "@/types/api";

interface TrendChartProps {
  data: TrendGame[];
  line: number | null;
  direction?: Direction | null;
  height?: number;
}

export function TrendChart({ data, line, direction, height = 150 }: TrendChartProps) {
  if (!data || data.length === 0) return null;

  const chartData = data.map(d => ({
    opponent: d.opponent,
    rebounds: d.rebounds,
    date: d.date,
    result: getTrendResult(d.rebounds, line, direction),
  }));

  return (
    <div
      style={{ width: "100%", height }}
      role="img"
      aria-label={`Recent rebound totals${line !== null ? ` compared with the ${direction ? `${direction.toLowerCase()} ` : ""}${line} line` : ""}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
          <XAxis 
            dataKey="opponent" 
            tick={{ fill: "#ccc", fontSize: 10 }} 
            axisLine={{ stroke: "#333" }}
            tickLine={false}
          />
          <YAxis 
            tick={{ fill: "#ccc", fontSize: 10 }} 
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{ 
              background: "#1a1a2e", 
              border: "1px solid #444", 
              borderRadius: 8,
              color: "#ffffff",
              fontSize: 12
            }}
            formatter={(value) => [`${String(value)} rebounds`, "Rebounds"]}
            labelFormatter={(label, payload) => {
              if (payload && payload[0]) {
                const entry = payload[0].payload as { date?: string };
                return `vs ${String(label)}${entry.date ? ` (${entry.date})` : ""}`;
              }
              return `vs ${String(label)}`;
            }}
          />
          {line !== null && (
            <ReferenceLine 
              y={line} 
              stroke="rgba(255, 255, 255, 0.5)" 
              strokeDasharray="5 5" 
              strokeWidth={1.5}
              label={{ value: `Line: ${line}`, position: "right", fill: "#ccc", fontSize: 10 }}
            />
          )}
          <Bar dataKey="rebounds" radius={[3, 3, 0, 0]}>
            {chartData.map((entry, index) => (
              <Cell 
                key={`cell-${index}`} 
                fill={
                  entry.result === "hit"
                    ? "rgba(34, 197, 94, 0.75)"
                    : entry.result === "miss"
                      ? "rgba(248, 113, 113, 0.75)"
                      : "rgba(161, 161, 170, 0.65)"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
