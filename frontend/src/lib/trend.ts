import type { Direction } from "@/types/api";

export type TrendResult = "hit" | "miss" | "push" | "neutral";

export function getTrendResult(
  rebounds: number,
  line: number | null,
  direction?: Direction | null,
): TrendResult {
  if (line === null || !direction) return "neutral";
  if (rebounds === line) return "push";
  if (direction === "UNDER") return rebounds < line ? "hit" : "miss";
  return rebounds > line ? "hit" : "miss";
}
