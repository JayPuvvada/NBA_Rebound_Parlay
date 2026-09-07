import { usePersonalPicks } from "@/lib/personal-context";
import { snapshotPick } from "@/lib/personal-picks";
import type { ProjectionBase, ProjectionMetrics } from "@/types/api";

export function SavePickControl({ data, metrics }: { data: ProjectionBase; metrics: ProjectionMetrics }) {
  const personal = usePersonalPicks();
  if (!personal || personal.enabled === false) return null;
  const demo = personal.mode !== "account";
  const sample = demo || import.meta.env.VITE_SAMPLE_DATA === "true" || data.metadata?.projection_inputs?.source?.startsWith("demo") === true;
  let pick;
  try { pick = snapshotPick(data, metrics, sample); } catch { return null; }
  const saved = personal.picks.some(p => p.id === pick.id);
  return <div className="space-y-2 text-sm">
    {!personal.signedIn ? <a href="#picks" className="text-emerald-300 underline">{demo ? "Sign in to the test profile to save this pick" : "Sign in to save this pick"}</a> : <div className="flex flex-wrap items-center gap-4">
      <button type="button" disabled={saved || personal.busy} onClick={() => personal.save(pick)} className="rounded-lg bg-emerald-600 px-4 py-2 font-semibold disabled:bg-zinc-800 disabled:text-zinc-400">{saved ? "Saved to My Picks" : personal.busy ? "Please wait…" : "Save pick"}</button>
      <a href="#picks" className="text-emerald-300 underline">View My Picks</a>
    </div>}
    <p className="text-xs text-zinc-500">{demo ? "Demo bookmark in this browser only." : "Saves a snapshot to your private account."} Does not place a bet or write to the performance ledger.</p>
    {personal.error && <p role="alert" className="text-red-300">{personal.error}</p>}
  </div>;
}
