import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

let server;
let BettingAnalysis;
let PredictResults;
let PlayerDetailPanel;
let PredictForm;
let bettingView;
before(async () => {
  server = await createServer({ server: { middlewareMode: true, watch: null, ws: false }, appType: "custom" });
  ({ BettingAnalysis } = await server.ssrLoadModule("/src/components/ui/BettingAnalysis.tsx"));
  ({ PredictResults } = await server.ssrLoadModule("/src/components/ui/PredictResults.tsx"));
  ({ PlayerDetailPanel } = await server.ssrLoadModule("/src/components/ui/PlayerDetailPanel.tsx"));
  ({ PredictForm } = await server.ssrLoadModule("/src/components/ui/PredictForm.tsx"));
  ({ bettingView } = await server.ssrLoadModule("/src/lib/betting.ts"));
});
after(async () => { await server?.close(); });

const data = {
  player: "Test Player", team: "DEN", opponent: "LAL", projection: 11.8,
  date: "2026-10-20", home_game: true, prediction_eligible: true,
  components: { "Proj Minutes": 34, "Raw Mult": 1.1, "DNP Rate": 0, Blowout: "None" },
  data_freshness: { injuries: { status: "available", stale: false } },
};
const metrics = {
  line: 10.5, direction: "OVER", actionable: true, evaluated_side: "OVER",
  american_odds: -110, over_probability: 0.6, under_probability: 0.4,
  push_probability: 0, confidence: 0.6, ev_roi: 0.145, kelly_fraction: 0.04,
  edge: 0.08, tier: "PLAY", prediction_interval_68: [7, 16],
  variance: { fano: 1.5, source: "empirical", high_variance: false },
  side_evaluations: {
    over: { direction: "OVER", confidence: 0.6, american_odds: -110, ev_roi: 0.145 },
    under: { direction: "UNDER", confidence: 0.4, american_odds: -115, ev_roi: -0.25 },
  },
};
function render(props = {}) {
  return renderToStaticMarkup(createElement(BettingAnalysis, { data, metrics, ...props }));
}

test("core display keeps price, probabilities, return, range and minutes without technical clutter", () => {
  const html = render();
  for (const text of ["OVER 10.5 at -110", "Model win probability", "Expected return", "central 68%", "Projected minutes"]) assert.ok(html.includes(text), text);
  for (const text of ["Kelly", "Fano", "Confidence", "Raw Mult", "Probability edge", "Implied probability", "prediction interval", "Model insights"]) assert.ok(!html.includes(text), text);
  assert.equal((html.match(/Model win probability/g) ?? []).length, 2);
  assert.ok(!html.includes("push probability"));
});

test("public lookup hides ledger saving and token controls", () => {
  const html = renderToStaticMarkup(createElement(PredictForm));
  assert.ok(html.includes("Check rebound prop"));
  assert.ok(html.includes("Over odds"));
  for (const text of ["Optional performance tracking", "Save a qualifying", "lookup-ledger-token", 'type="checkbox"', 'type="password"']) {
    assert.ok(!html.includes(text), text);
  }
});

test("unpriced analysis never invents odds or a recommendation", () => {
  const html = render({ metrics: { line: 10.5, over_probability: 0.6, under_probability: 0.4 } });
  assert.ok(html.includes("NO BET"));
  assert.ok(html.includes("No price supplied"));
  assert.equal((html.match(/No price/g) ?? []).length, 3);
  assert.ok(!html.includes("-110"));
  assert.ok(!html.includes("<strong>+"));
});

test("projection-only response keeps its numeric range without side cards", () => {
  const html = render({ metrics: null, range: { low: 7, high: 16, level: 0.68 } });
  assert.ok(html.includes("7–16 rebounds"));
  assert.ok(!html.includes("Model win probability"));
});

test("integer line shows push chance but half lines omit the zero-value metric", () => {
  assert.ok(render({ metrics: { ...metrics, line: 10, push_probability: 0.08 } }).includes("8.0% push probability"));
  assert.ok(!render().includes("push probability"));
});

test("failed data eligibility suppresses recommendation and return, preserving warnings", () => {
  const html = render({ data: { ...data, prediction_eligible: false, limitations: ["ESPN totals only"], metadata: { limitations: ["Schedule unverified"] } } });
  assert.ok(html.includes("NO BET"));
  assert.ok(html.includes("ESPN totals only"));
  assert.ok(html.includes("Schedule unverified"));
  assert.ok(!html.includes("OVER 10.5 at"));
  assert.ok(!html.includes("<strong>+"));
});

test("any negative eligibility or degraded source wins over an optimistic top-level flag", () => {
  assert.equal(bettingView({ ...data, metadata: { prediction_eligible: false } }, metrics).direction, null);
  assert.equal(bettingView({ ...data, data_freshness: { projection_inputs: { status: "degraded" } } }, metrics).direction, null);
  assert.equal(bettingView({ ...data, prediction_eligible: undefined }, metrics).direction, null);
});

test("a priced evaluated side is not a pick unless explicitly actionable", () => {
  for (const override of [{ actionable: false }, { direction: null }, { tier: "STALE_ODDS" }, { american_odds: null }, { line: null }]) {
    assert.equal(bettingView(data, { ...metrics, ...override }).direction, null);
  }
});

test("manual quote copy does not mislabel generated time as a sportsbook update", () => {
  const html = render({ manual: true, data: { ...data, generated_at: "2026-10-20T12:00:00Z" } });
  assert.ok(html.includes("Manually entered · not independently verified"));
  assert.ok(!html.includes("Quote updated"));
});

test("distinct side lines retain the matching side-specific probability", () => {
  const html = render({
    marketOdds: { over: { line: 10.5, odds: -110 }, under: { line: 12.5, odds: -115 } },
    metrics: { ...metrics, side_evaluations: { ...metrics.side_evaluations, under: { direction: "UNDER", confidence: 0.7, american_odds: -115, ev_roi: 0.1 } } },
  });
  assert.ok(html.includes("UNDER 12.5"));
  assert.ok(html.includes("70.0%"));
});

test("different line without matching evaluation does not borrow another line's probability", () => {
  const html = render({ marketOdds: { under: { line: 12.5, odds: -115 } }, metrics: { ...metrics, side_evaluations: undefined } });
  assert.ok(html.includes("UNDER 12.5"));
  assert.ok(!html.includes("40.0%"));
});

test("injury staleness, missing lists and high variance stay visible without Fano math", () => {
  const html = render({
    data: { ...data, injuries: { team_list: [], opp_list: [] }, data_freshness: { injuries: { status: "degraded", stale: true } } },
    metrics: { ...metrics, variance: { high_variance: true, fano: 4.5 } },
  });
  assert.ok(html.includes("Injury information is stale"));
  assert.ok(html.includes("varied widely"));
  assert.ok(html.includes("does not confirm a healthy roster"));
  assert.ok(!html.includes("Fano"));
});

test("both result entry points share the simplified display and preserve recording feedback", () => {
  const lookup = renderToStaticMarkup(createElement(PredictResults, { data: { ...data, analysis: metrics, recording: { requested: true, recorded: false, reason: "Authorization failed." } } }));
  const detail = renderToStaticMarkup(createElement(PlayerDetailPanel, { player: { ...data, ...metrics } }));
  assert.ok(lookup.includes("Authorization failed."));
  assert.ok(lookup.includes("does not place a bet"));
  for (const html of [lookup, detail]) {
    assert.ok(html.includes("Model recommendation"));
    assert.ok(!html.includes("Kelly"));
  }
});
