import { Card, CardContent } from "@/components/ui/card";
import { BettingAnalysis } from "@/components/ui/BettingAnalysis";
import type { PredictResponse } from "@/types/api";

export function PredictResults({ data }: { data: PredictResponse }) {
  return (
    <Card className="w-full border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl" aria-live="polite">
      <CardContent className="pt-6">
        <BettingAnalysis data={data} metrics={data.analysis} range={data.range} manual />
        {data.recording?.requested && (
          <div className="mt-5 rounded-lg border border-zinc-700 bg-zinc-900/50 p-3 text-sm text-zinc-300" role="status">
            <strong>{data.recording.recorded ? "Saved for performance tracking." : "Not saved for performance tracking."}</strong>
            {data.recording.reason && <span> {data.recording.reason}</span>}
            <p className="mt-1 text-xs text-zinc-500">This records a model pick. It does not place a bet.</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
