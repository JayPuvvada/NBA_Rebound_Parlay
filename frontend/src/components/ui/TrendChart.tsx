import { BarChart, Bar, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, Cell } from "recharts";

interface TrendGame {
  date: string;
  rebounds: number;
  opponent: string;
  minutes?: number;
}

interface TrendChartProps {
  data: TrendGame[];
  line: number | null;
  height?: number;
}

export function TrendChart({ data, line, height = 150 }: TrendChartProps) {
  if (!data || data.length === 0) return null;

  const chartData = data.map(d => ({
    opponent: d.opponent,
    rebounds: d.rebounds,
    date: d.date,
    hit: line !== null ? d.rebounds > line : true,
  }));

  return (
    <div style={{ width: "100%", height }}>
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
            formatter={(value: number) => [`${value} rebounds`, "Rebounds"]}
            labelFormatter={(label: string, payload: any[]) => {
              if (payload && payload[0]) {
                return `vs ${label} (${payload[0].payload.date})`;
              }
              return `vs ${label}`;
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
                fill={entry.hit ? "rgba(34, 197, 94, 0.7)" : "rgba(248, 113, 113, 0.7)"} 
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
