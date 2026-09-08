import { useState } from "react";
import { usePersonalPicks } from "@/lib/personal-context";
import type { PickResult } from "@/lib/personal-picks";
import { formatAmericanOdds, formatTimestamp } from "@/lib/format";

const button = "rounded-lg bg-emerald-600 px-4 py-2 font-semibold text-white hover:bg-emerald-500 focus-visible:ring-2 focus-visible:ring-emerald-300";
export function MyPicks() {
  const personal = usePersonalPicks();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [creating, setCreating] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [repeatPassword, setRepeatPassword] = useState("");
  if (!personal) return null;
  const demo = personal.mode !== "account";
  return <div className="space-y-6">
    <div>
      <h2 className="text-2xl font-bold">My Picks</h2>
      <p className="mt-2 text-sm text-amber-200">{demo ? "Personal demo only — test login is not real account security. Picks stay in this browser at this address, not in a server account. Clearing site data removes them. No bets are placed." : "Your saved picks are private to your account and stored online. Sign back in to access them after clearing browser data or on another device. No bets are placed."}</p>
    </div>
    {personal.error && <p role="alert" className="text-red-300">{personal.error}</p>}
    {personal.refresh && <button type="button" disabled={personal.busy} onClick={personal.refresh} className="rounded border border-zinc-700 px-3 py-2 text-sm disabled:opacity-50">{personal.busy ? "Loading account…" : "Refresh picks"}</button>}
    {personal.enabled === false ? <p className="text-zinc-400">Follow docs/private-account.md to connect Supabase, then restart the demo. Login and cloud saving stay disabled until configured.</p> : !personal.signedIn ? <form className="max-w-md space-y-4 rounded-xl border border-zinc-800 bg-zinc-900/50 p-5" onSubmit={async event => {
      event.preventDefault();
      setLoginError(""); setConfirmation("");
      if (creating && personal.signup) {
        if (password !== repeatPassword) { setLoginError("Passwords do not match."); return; }
        const result = await personal.signup(username, password);
        if (!result) { setLoginError("Could not create your account. Check the message above."); return; }
        setPassword(""); setRepeatPassword(""); setCreating(false);
        if (result === "confirmation") setConfirmation("Check your email for a confirmation link, then return here and sign in. If you already have an account, sign in with your existing password.");
        return;
      }
      if (!await personal.login(username, password)) setLoginError(demo ? "Use the test username jay and password demo123." : "Sign-in failed. Check your credentials and the message above.");
      else { setPassword(""); setLoginError(""); }
    }}>
      <h3 className="text-lg font-semibold">{demo ? "Sign in to the test profile" : creating ? "Create your account" : "Sign in to your account"}</h3>
      {!demo && !personal.signup && <p className="text-sm text-zinc-400">Sign in with an existing account. Public signup is not available yet.</p>}
      {confirmation && <p role="status" className="text-sm text-emerald-300">{confirmation}</p>}
      {demo && <p className="text-sm text-zinc-400">Username: <code>jay</code> · Password: <code>demo123</code>. Do not enter a real password.</p>}
      <label className="block text-sm">{demo ? "Test username" : "Email"}<input id="demo-username" type={demo ? "text" : "email"} autoComplete={demo ? "off" : "username"} maxLength={254} required value={username} onChange={e => setUsername(e.target.value)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-3" /></label>
      <label className="block text-sm">{demo ? "Test password" : "Password"}<input id="demo-password" type="password" autoComplete={demo ? "off" : creating ? "new-password" : "current-password"} minLength={creating ? 12 : undefined} maxLength={256} required value={password} onChange={e => setPassword(e.target.value)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-3" /></label>
      {creating && <>
        <p className="text-xs text-zinc-400">Use at least 12 characters and a password you do not use elsewhere. This beta does not verify email addresses or offer password-reset emails. Double-check your email and keep your password safe.</p>
        <label className="block text-sm">Confirm password<input type="password" autoComplete="new-password" minLength={12} maxLength={256} required value={repeatPassword} onChange={e => setRepeatPassword(e.target.value)} className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-3" /></label>
      </>}
      {loginError && <p role="alert" className="text-red-300">{loginError}</p>}
      <button disabled={personal.busy} className={button + " disabled:opacity-50"} type="submit">{personal.busy ? "Please wait…" : demo ? "Sign in to demo" : creating ? "Create account" : "Sign in"}</button>
      {!demo && personal.signup && <button type="button" disabled={personal.busy} className="block text-sm text-emerald-300 underline disabled:opacity-50" onClick={() => { setCreating(!creating); setPassword(""); setRepeatPassword(""); setLoginError(""); setConfirmation(""); }}>{creating ? "Already have an account? Sign in" : "New here? Create an account"}</button>}
    </form> : <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 break-all text-zinc-300">{demo ? "Jay’s test profile" : personal.username} · {personal.picks.length} saved {personal.picks.length === 1 ? "pick" : "picks"}</p>
        <button type="button" disabled={personal.busy} onClick={personal.logout} className="rounded-lg border border-zinc-700 px-4 py-2 disabled:opacity-50">Sign out</button>
      </div>
      <p className="text-sm text-zinc-400">Saved snapshots do not update with live odds and are not independently verified. Results below are marked manually, not verified performance.{!demo && " Reopening or focusing the app refreshes picks from your account."}</p>
      {personal.picks.length === 0 && <div className="rounded-xl border border-dashed border-zinc-700 p-8 text-center">
        <p className="mb-4 text-zinc-300">No saved picks yet. Open a qualifying recommendation and choose Save pick.</p>
        <a className={button} href="#edge">Browse Daily Edge</a>
      </div>}
      <div className="grid gap-4 lg:grid-cols-2">{personal.picks.map(pick => <article key={pick.id} className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/50 p-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-300">{demo ? "Demo saved pick" : pick.demo ? "Sample pick — synthetic data" : "Saved model snapshot"} · {pick.result}</p>
        <h3 className="text-xl font-bold">{pick.player}</h3>
        <p className="text-sm text-zinc-400">vs {pick.opponent} · {pick.date}</p>
        <p className="text-lg font-semibold text-emerald-300">{pick.direction} {pick.line} rebounds at {formatAmericanOdds(pick.odds)}</p>
        <p className="text-sm text-zinc-300">Projected rebounds: {pick.projection} · {pick.bookmaker}</p>
        <p className="text-xs text-zinc-500">Saved {formatTimestamp(pick.savedAt)}</p>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <label className="text-sm text-zinc-400">{demo ? "Manual test result" : "Manual result"}<select disabled={personal.busy} aria-label={`Result for ${pick.player}`} value={pick.result} onChange={e => personal.grade(pick.id, e.target.value as PickResult)} className="mt-1 block rounded border border-zinc-700 bg-zinc-950 p-2 text-white">{["Pending", "Win", "Loss", "Push"].map(result => <option key={result}>{result}</option>)}</select></label>
          <button disabled={personal.busy} className="rounded px-3 py-2 text-sm text-red-300 hover:bg-red-950/30 disabled:opacity-50" type="button" onClick={() => { if (window.confirm(`Remove ${pick.player} from ${demo ? "saved demo picks" : "your account"}?`)) personal.remove(pick.id); }}>Remove pick</button>
        </div>
      </article>)}</div>
    </>}
  </div>;
}
