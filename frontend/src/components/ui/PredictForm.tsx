import { useEffect, useRef, useState, type FormEvent } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PredictResults } from "@/components/ui/PredictResults";
import { Loader2 } from "lucide-react";
import { ApiRequestError, fetchJson } from "@/lib/api";
import { easternToday } from "@/lib/format";
import type { PredictRequest, PredictResponse } from "@/types/api";

type Venue = "auto" | "home" | "away";

function parseOptionalNumber(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

function validAmericanOdds(value: number | null): boolean {
  return value === null || (Number.isFinite(value) && Number.isInteger(value) && (value <= -100 || value >= 100));
}

export function PredictForm() {
  const [player, setPlayer] = useState("");
  const [opponent, setOpponent] = useState("");
  const [date, setDate] = useState(easternToday);
  const [spread, setSpread] = useState("");
  const [line, setLine] = useState("");
  const [overOdds, setOverOdds] = useState("");
  const [underOdds, setUnderOdds] = useState("");
  const [bookmaker, setBookmaker] = useState("");
  const [matchup, setMatchup] = useState("");
  const [venue, setVenue] = useState<Venue>("auto");
  const [recordPrediction, setRecordPrediction] = useState(false);
  const [ledgerToken, setLedgerToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PredictResponse | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const canRecord = line.trim() !== "" && (overOdds.trim() !== "" || underOdds.trim() !== "");

  useEffect(() => () => {
    activeRequest.current?.abort();
    activeRequest.current = null;
  }, []);

  const buildRequest = (): PredictRequest => {
    const parsedLine = parseOptionalNumber(line);
    const parsedOverOdds = parseOptionalNumber(overOdds);
    const parsedUnderOdds = parseOptionalNumber(underOdds);
    const parsedSpread = parseOptionalNumber(spread) ?? 0;

    if (!player.trim()) throw new Error("Enter a player name.");
    if (!/^[A-Za-z]{3}$/.test(opponent.trim())) throw new Error("Opponent must be a three-letter NBA abbreviation.");
    if (!date) throw new Error("Choose the game date.");
    if (!Number.isFinite(parsedSpread) || parsedSpread < -40 || parsedSpread > 40) {
      throw new Error("Player team spread must be between -40 and +40.");
    }
    if (parsedLine !== null && (!Number.isFinite(parsedLine) || parsedLine < 0 || parsedLine > 40)) {
      throw new Error("Rebound line must be between 0 and 40.");
    }
    if ((parsedOverOdds !== null || parsedUnderOdds !== null) && parsedLine === null) {
      throw new Error("Enter a rebound line before entering prices.");
    }
    if (!validAmericanOdds(parsedOverOdds) || !validAmericanOdds(parsedUnderOdds)) {
      throw new Error("American odds must be -100 or lower, or +100 or higher.");
    }
    const shouldRecord = recordPrediction && canRecord;
    if (shouldRecord && !ledgerToken.trim()) {
      throw new Error("Enter the configured ledger write token to save this pick.");
    }

    return {
      player: player.trim(),
      opponent: opponent.trim().toUpperCase(),
      spread: parsedSpread,
      line: parsedLine,
      over_odds: parsedOverOdds,
      under_odds: parsedUnderOdds,
      bookmaker: bookmaker.trim() || null,
      matchup: matchup.trim() || null,
      date,
      home_game: venue === "auto" ? null : venue === "home",
      record_prediction: shouldRecord,
    };
  };

  const runPrediction = async (payload: PredictRequest, writeToken: string) => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const headers = new Headers({ "Content-Type": "application/json" });
      if (payload.record_prediction && writeToken) headers.set("X-Ledger-Write-Token", writeToken);
      const response = await fetchJson<PredictResponse>(
        "/predict",
        {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
          signal: controller.signal,
        },
        { timeoutMs: 110_000 },
      );
      setResult(response);
      if (payload.record_prediction) setLedgerToken("");
    } catch (requestError: unknown) {
      if (requestError instanceof ApiRequestError && requestError.kind === "aborted") return;
      setError(requestError instanceof Error ? requestError.message : "Failed to run simulation.");
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setLoading(false);
      }
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      void runPrediction(buildRequest(), ledgerToken.trim());
    } catch (validationError: unknown) {
      setError(validationError instanceof Error ? validationError.message : "Check the form values.");
    }
  };

  const retry = () => {
    try {
      void runPrediction(buildRequest(), ledgerToken.trim());
    } catch (validationError: unknown) {
      setError(validationError instanceof Error ? validationError.message : "Check the form values.");
    }
  };

  const cancel = () => activeRequest.current?.abort();

  const updateLine = (value: string) => {
    setLine(value);
    if (!value.trim()) {
      setRecordPrediction(false);
      setLedgerToken("");
    }
  };

  const updateOverOdds = (value: string) => {
    setOverOdds(value);
    if (!value.trim() && !underOdds.trim()) {
      setRecordPrediction(false);
      setLedgerToken("");
    }
  };

  const updateUnderOdds = (value: string) => {
    setUnderOdds(value);
    if (!value.trim() && !overOdds.trim()) {
      setRecordPrediction(false);
      setLedgerToken("");
    }
  };

  const updateRecordPrediction = (checked: boolean) => {
    setRecordPrediction(checked);
    if (!checked) setLedgerToken("");
  };

  return (
    <div className="space-y-6">
      <Card className="w-full border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl">
        <CardHeader className="border-b border-zinc-800 pb-5">
          <CardTitle className="flex items-center gap-2 text-xl font-bold">🏀 Player Lookup</CardTitle>
          <p className="mt-1 text-sm text-zinc-400">Run a date-specific projection with optional market prices.</p>
        </CardHeader>
        <CardContent className="pt-5">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="lookup-player" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Player name</label>
              <input id="lookup-player" type="text" value={player} onChange={(event) => setPlayer(event.target.value)} placeholder="e.g. Nikola Jokic" required maxLength={100} autoComplete="off" className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="lookup-opponent" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Opponent</label>
                <input id="lookup-opponent" type="text" value={opponent} onChange={(event) => setOpponent(event.target.value)} placeholder="BOS" required minLength={3} maxLength={3} pattern="[A-Za-z]{3}" autoComplete="off" className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm uppercase placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
              <div>
                <label htmlFor="lookup-date" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Game date</label>
                <input id="lookup-date" type="date" value={date} onChange={(event) => setDate(event.target.value)} required className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="lookup-spread" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Player team spread</label>
                <input id="lookup-spread" type="number" value={spread} onChange={(event) => setSpread(event.target.value)} placeholder="-5.5" min="-40" max="40" step="0.5" className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
              <div>
                <label htmlFor="lookup-line" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Rebound line</label>
                <input id="lookup-line" type="number" value={line} onChange={(event) => updateLine(event.target.value)} placeholder="10.5" min="0" max="40" step="0.5" className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
            </div>

            <fieldset>
              <legend className="mb-1 text-xs uppercase tracking-wider text-zinc-500">American odds by side (optional)</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="lookup-over-odds" className="sr-only">Over odds</label>
                  <input id="lookup-over-odds" type="number" value={overOdds} onChange={(event) => updateOverOdds(event.target.value)} placeholder="Over -110" step="1" className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                </div>
                <div>
                  <label htmlFor="lookup-under-odds" className="sr-only">Under odds</label>
                  <input id="lookup-under-odds" type="number" value={underOdds} onChange={(event) => updateUnderOdds(event.target.value)} placeholder="Under -110" step="1" className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                </div>
              </div>
              <p className="mt-1.5 text-xs text-zinc-600">Without a price, results are informational and do not claim a betting edge.</p>
            </fieldset>

            <div>
              <label htmlFor="lookup-bookmaker" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Sportsbook / price source (optional)</label>
              <input id="lookup-bookmaker" type="text" value={bookmaker} onChange={(event) => setBookmaker(event.target.value)} maxLength={50} placeholder="e.g. FanDuel" autoComplete="off" className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
            </div>

            <div>
              <label htmlFor="lookup-matchup" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Matchup override (optional)</label>
              <input id="lookup-matchup" type="text" value={matchup} onChange={(event) => setMatchup(event.target.value)} maxLength={100} placeholder="e.g. Al Horford" autoComplete="off" className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
            </div>

            <fieldset>
              <legend className="mb-1 text-xs uppercase tracking-wider text-zinc-500">Venue</legend>
              <div className="flex gap-1 rounded-md border border-zinc-700 bg-zinc-900 p-1">
                {(["auto", "home", "away"] as const).map((option) => (
                  <button type="button" key={option} aria-pressed={venue === option} onClick={() => setVenue(option)} className={`flex-1 rounded px-2 py-1.5 text-xs font-semibold capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 sm:px-3 ${venue === option ? "bg-emerald-600 text-white" : "text-zinc-400 hover:text-zinc-200"}`}>
                    {option === "auto" ? "Auto from schedule" : option}
                  </button>
                ))}
              </div>
              {venue === "auto" && <p className="mt-1.5 text-xs text-zinc-600">If the schedule cannot verify this exact opponent and date, choose Home or Away explicitly.</p>}
            </fieldset>

            <label className={`flex items-start gap-3 rounded-md border p-3 text-sm ${canRecord ? "cursor-pointer border-zinc-700 bg-zinc-900/50 text-zinc-300" : "cursor-not-allowed border-zinc-800 bg-zinc-950 text-zinc-600"}`}>
              <input
                type="checkbox"
                checked={recordPrediction}
                disabled={!canRecord}
                onChange={(event) => updateRecordPrediction(event.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-zinc-600 bg-zinc-900 text-emerald-600 focus:ring-emerald-500"
              />
              <span>
                <span className="block font-semibold">Save actionable pick to evaluation ledger</span>
                <span className="mt-0.5 block text-xs text-zinc-500">Unchecked by default. Requires a line and at least one side-specific price; the server saves only eligible picks.</span>
              </span>
            </label>

            {recordPrediction && (
              <div className="rounded-md border border-zinc-700 bg-zinc-900/50 p-3">
                <label htmlFor="lookup-ledger-token" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Ledger write token</label>
                <input
                  id="lookup-ledger-token"
                  type="password"
                  value={ledgerToken}
                  onChange={(event) => setLedgerToken(event.target.value)}
                  required={recordPrediction}
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  aria-describedby="lookup-ledger-token-note"
                  placeholder="Required to save an issued pick"
                  className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2.5 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <p id="lookup-ledger-token-note" className="mt-1.5 text-xs text-zinc-500">Sent only as the X-Ledger-Write-Token header for this request. It is never included in the JSON body or browser storage.</p>
              </div>
            )}

            <div className="flex flex-col gap-2 sm:flex-row">
              <button type="submit" disabled={loading} className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-emerald-600 py-3 font-bold text-white transition-colors duration-200 hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-zinc-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300">
                {loading ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Simulating…</> : "Run simulation"}
              </button>
              {loading && <button type="button" onClick={cancel} className="rounded-lg border border-zinc-700 px-4 py-3 text-sm font-semibold text-zinc-300 hover:bg-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400">Cancel</button>}
            </div>

            {error && (
              <div className="rounded-md border border-red-900/50 bg-red-950/20 p-3 text-sm text-red-400" role="alert">
                <p>{error}</p>
                <button type="button" onClick={retry} className="mt-2 rounded bg-red-900/30 px-2.5 py-1.5 text-xs font-semibold text-red-200 hover:bg-red-900/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400">Retry request</button>
              </div>
            )}
          </form>
        </CardContent>
      </Card>

      {result && <PredictResults data={result} />}
    </div>
  );
}
