import { bettingView } from "./betting";
import type { ProjectionBase, ProjectionMetrics } from "@/types/api";

export const PICKS_KEY = "nba.personal-demo.picks.v1";
export const SESSION_KEY = "nba.personal-demo.session.v1";
export type PickResult = "Pending" | "Win" | "Loss" | "Push";
export interface SavedPick {
  id: string;
  player: string;
  opponent: string;
  date: string;
  projection: number;
  direction: "OVER" | "UNDER";
  line: number;
  odds: number;
  bookmaker: string;
  savedAt: string;
  result: PickResult;
  demo: boolean;
}

export function demoEnabled(flag: unknown, hostname: string) {
  return flag === "true" && ["localhost", "127.0.0.1", "[::1]"].includes(hostname);
}

// Public demo credentials, deliberately NOT authentication or server access.
export function demoCredentials(username: string, password: string) {
  return username.trim() === "jay" && password === "demo123";
}

export function snapshotPick(data: ProjectionBase, metrics: ProjectionMetrics, demo = true): SavedPick {
  const { direction } = bettingView(data, metrics);
  if (!direction || !data.date || !Number.isFinite(data.projection)) {
    throw new Error("Only a qualifying, dated model recommendation can be saved.");
  }
  const line = metrics.line!;
  const odds = metrics.american_odds!;
  return {
    id: JSON.stringify([data.player, data.opponent, data.date, direction, line, odds, metrics.bookmaker || "Entered price", demo ? "sample" : "model"]),
    player: data.player, opponent: data.opponent, date: data.date,
    projection: data.projection, direction, line, odds,
    bookmaker: metrics.bookmaker || "Entered price", savedAt: new Date().toISOString(),
    result: "Pending", demo,
  };
}

export function readPicks(storage: Pick<Storage, "getItem">): SavedPick[] {
  const raw = storage.getItem(PICKS_KEY);
  if (raw === null) return [];
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value) || !value.every(p => p &&
    [p.id, p.player, p.opponent, p.date, p.bookmaker, p.savedAt].every(v => typeof v === "string") &&
    [p.projection, p.line, p.odds].every(v => typeof v === "number" && Number.isFinite(v)) &&
    ["OVER", "UNDER"].includes(p.direction) &&
    ["Pending", "Win", "Loss", "Push"].includes(p.result) && p.demo === true)) {
    throw new Error("Invalid saved-pick data");
  }
  return value;
}

export function writePicks(storage: Pick<Storage, "setItem">, picks: SavedPick[], signedIn: boolean) {
  if (!signedIn) throw new Error("Sign in to the test profile first.");
  storage.setItem(PICKS_KEY, JSON.stringify(picks));
}
