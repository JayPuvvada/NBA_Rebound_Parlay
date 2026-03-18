import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PredictResults } from "@/components/ui/PredictResults";
import { Loader2 } from "lucide-react";

export function PredictForm() {
  const [player, setPlayer] = useState("");
  const [opponent, setOpponent] = useState("");
  const [spread, setSpread] = useState("");
  const [line, setLine] = useState("");
  const [odds, setOdds] = useState("");
  const [matchup, setMatchup] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch("http://127.0.0.1:5001/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          player,
          opponent: opponent.toUpperCase(),
          spread: spread || "0",
          line: line || null,
          odds: odds || null,
          matchup: matchup || null,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Server error");
      setResult(data);
    } catch (err: any) {
      setError(err.message || "Failed to run simulation.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card className="w-full bg-zinc-950 border-zinc-800 text-zinc-100 shadow-2xl">
        <CardHeader className="border-b border-zinc-800 pb-5">
          <CardTitle className="text-xl font-bold flex items-center gap-2">
            🏀 Player Lookup
          </CardTitle>
          <p className="text-zinc-400 text-sm mt-1">Enter player details to run the simulation engine.</p>
        </CardHeader>
        <CardContent className="pt-5">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Player Name */}
            <div>
              <label className="block text-xs text-zinc-500 mb-1 uppercase tracking-wider">Player Name</label>
              <input
                type="text"
                value={player}
                onChange={(e) => setPlayer(e.target.value)}
                placeholder="e.g. Nikola Jokic"
                required
                className="w-full bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 placeholder-zinc-600"
              />
            </div>

            {/* Opponent + Spread */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-zinc-500 mb-1 uppercase tracking-wider">Opponent</label>
                <input
                  type="text"
                  value={opponent}
                  onChange={(e) => setOpponent(e.target.value)}
                  placeholder="BOS"
                  required
                  maxLength={3}
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 placeholder-zinc-600 uppercase"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-500 mb-1 uppercase tracking-wider">Spread</label>
                <input
                  type="number"
                  value={spread}
                  onChange={(e) => setSpread(e.target.value)}
                  placeholder="-5.5"
                  step="0.5"
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 placeholder-zinc-600"
                />
              </div>
            </div>

            {/* Line + Odds */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-zinc-500 mb-1 uppercase tracking-wider">Betting Line (O/U)</label>
                <input
                  type="number"
                  value={line}
                  onChange={(e) => setLine(e.target.value)}
                  placeholder="10.5"
                  step="0.5"
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 placeholder-zinc-600"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-500 mb-1 uppercase tracking-wider">American Odds</label>
                <input
                  type="number"
                  value={odds}
                  onChange={(e) => setOdds(e.target.value)}
                  placeholder="-110"
                  step="1"
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 placeholder-zinc-600"
                />
              </div>
            </div>

            {/* Matchup Override */}
            <div>
              <label className="block text-xs text-zinc-500 mb-1 uppercase tracking-wider">Matchup Override (Optional)</label>
              <input
                type="text"
                value={matchup}
                onChange={(e) => setMatchup(e.target.value)}
                placeholder="e.g. Al Horford"
                className="w-full bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 placeholder-zinc-600"
              />
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-emerald-600 hover:bg-emerald-700 disabled:bg-zinc-700 disabled:cursor-not-allowed text-white font-bold py-3 rounded-lg transition-colors duration-200 flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Simulating...
                </>
              ) : (
                "Run Simulation"
              )}
            </button>

            {error && (
              <div className="p-3 border border-red-900/50 bg-red-950/20 text-red-400 rounded-md text-sm">
                {error}
              </div>
            )}
          </form>
        </CardContent>
      </Card>

      {/* Results */}
      {result && <PredictResults data={result} />}
    </div>
  );
}
