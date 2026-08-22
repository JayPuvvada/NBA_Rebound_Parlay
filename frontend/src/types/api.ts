export interface Game {
  home: string;
  away: string;
}

export interface TrendGame {
  date: string;
  rebounds: number;
  opponent: string;
  minutes?: number;
}

export interface InjuryInfo {
  matchup?: string | null;
  team?: string | null;
  team_list?: string[];
  opp_list?: string[];
}

export interface ComponentBreakdown {
  [key: string]: number;
}

export interface CheatRow {
  player: string;
  team: string;
  opponent: string;
  projection: number;
  line: number | "-";
  direction: "OVER" | "UNDER" | "-";
  tier: string;
  rest_note: string;
  context: string;
  components: ComponentBreakdown;
  trend: TrendGame[];
  edge_raw: number;
  over_prob?: number;
  under_prob?: number;
  confidence?: number;
  summary?: string;
}

export interface PredictAnalysis {
  line: number;
  over_prob: number;
  under_prob: number;
  confidence: number;
  recommendation: string;
  rec_color: string;
  edge: number;
  hit_rate: number;
  hit_rate_games: number;
  fano: number;
  fano_source: string;
  high_variance_flag: boolean;
  american_odds: number;
  implied_prob: number;
  true_edge: number;
}

export interface PredictResponse {
  player: string;
  opponent: string;
  projection: number;
  home_game: boolean;
  context: string;
  injuries: InjuryInfo;
  components: ComponentBreakdown;
  trend: TrendGame[];
  analysis?: PredictAnalysis;
  summary?: string;
  range?: string;
  error?: string;
}
