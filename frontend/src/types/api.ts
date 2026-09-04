export type Direction = "OVER" | "UNDER";

export type TierColor = "green" | "blue" | "purple" | "yellow" | "red" | "gray";

export interface Game {
  id?: string;
  game_id?: string;
  date?: string;
  home: string;
  away: string;
  start_time?: string | null;
  status?: number | string | null;
  status_text?: string | null;
  game_time?: string | null;
}

export interface GamesResponse {
  games: Game[];
  message?: string;
  date?: string;
  generated_at?: string;
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

export type ComponentValue = number | string;
export type ComponentBreakdown = Record<string, ComponentValue>;

export interface VarianceInfo {
  fano?: number | null;
  source?: "empirical" | "heuristic" | string | null;
  high_variance?: boolean;
  sample_size?: number | null;
  distribution?: string | null;
  standard_deviation?: number | null;
  simulation_sample_size?: number | null;
}

export interface SideEvaluation {
  direction: Direction;
  confidence: number;
  hit_rate?: number | null;
  hit_rate_games?: number | null;
  tier?: string | null;
  tier_color?: TierColor | string | null;
  american_odds?: number | null;
  implied_probability?: number | null;
  break_even_probability?: number | null;
  edge?: number | null;
  ev_roi?: number | null;
  kelly_fraction?: number | null;
}

/**
 * Probability, edge, ROI, hit-rate, and stake values are raw fractions on the
 * wire (0.61 means 61%). Presentation components are solely responsible for
 * converting them to percentages.
 */
export interface ProjectionMetrics {
  line?: number | null;
  direction?: Direction | null;
  actionable?: boolean;
  over_probability?: number | null;
  under_probability?: number | null;
  push_probability?: number | null;
  confidence?: number | null;
  edge?: number | null;
  implied_probability?: number | null;
  break_even_probability?: number | null;
  ev_roi?: number | null;
  kelly_fraction?: number | null;
  hit_rate?: number | null;
  hit_rate_games?: number | null;
  tier?: string | null;
  tier_color?: TierColor | string | null;
  american_odds?: number | null;
  odds_side?: Direction | null;
  evaluated_side?: Direction | null;
  bookmaker?: string | null;
  odds_source?: string | null;
  odds_updated_at?: string | null;
  generated_at?: string | null;
  variance?: VarianceInfo | null;
  side_evaluations?: Partial<Record<Lowercase<Direction>, SideEvaluation>>;
  prediction_interval_68?: number[];
  prediction_interval_95?: number[];
  prediction_interval_68_coverage?: number | null;
  prediction_interval_95_coverage?: number | null;
  interval_method?: string | null;
  probability_unit?: "fraction" | string;
  ev_roi_unit?: "fraction_per_unit_staked" | string;
  kelly_unit?: "bankroll_fraction" | string;

  // Temporary compatibility fields for responses produced before the API
  // contract was normalized. New server code should not emit these.
  recommendation?: string | null;
  rec_color?: string | null;
  fano?: number | null;
  fano_source?: string | null;
  high_variance_flag?: boolean;
}

export interface ProjectionBase {
  player: string;
  team?: string | null;
  team_id?: number | null;
  opponent: string;
  projection: number;
  home_game?: boolean;
  rest_note?: string;
  context?: string;
  injuries?: InjuryInfo;
  components?: ComponentBreakdown;
  trend?: TrendGame[];
  summary?: string | null;
  generated_at?: string | null;
  model_version?: string | null;
  data_freshness?: DataFreshness | string | null;
  metadata?: ProjectionMetadata | null;
  prediction_eligible?: boolean;
  limitations?: string[];
  schedule?: ScheduleVerification | null;
  date?: string;
  season?: string;
}

export interface DataFreshness {
  generated_at?: string | null;
  source?: string | null;
  as_of_date?: string | null;
  nba_stats_cutoff?: string | null;
  season?: string | null;
  injuries?: InjuryDataFreshness | null;
  prediction_eligible?: boolean;
  limitations?: string[];

  // Flat compatibility fields accepted from older deployments.
  stats_updated_at?: string | null;
  injuries_updated_at?: string | null;
  odds_updated_at?: string | null;
  stale?: boolean;
  note?: string | null;
}

export interface InjuryDataFreshness {
  status?: string | null;
  source?: string | null;
  fetched_at?: string | null;
  entry_count?: number | null;
  stale?: boolean | null;
}

export interface ProjectionMetadata {
  as_of_date?: string | null;
  data_cutoff?: string | null;
  historical_mode?: boolean;
  live_injuries_applied?: boolean;
  prediction_eligible?: boolean;
  limitations?: string[];
  opponent_rebound_source?: string | null;
  rebound_environment_baseline?: string | null;
  is_position_level_dvp?: boolean;
  pace_baseline?: string | null;
  miss_baseline?: string | null;
  trend_order?: string | null;
  team_source?: string | null;
  rate_sample_size?: number | null;
  variance_sample_size?: number | null;
  schedule_verified?: boolean;
  game_status?: number | string | null;
  recency_weights?: {
    season?: number;
    recent?: number;
    opponent_history?: number;
  } | null;
}

export interface ScheduleVerification {
  verified: boolean;
  game_id?: string | null;
  status?: number | string | null;
  status_text?: string | null;
}

export interface MarketQuote {
  line: number;
  odds: number;
  book?: string | null;
  source?: string | null;
  updated_at?: string | null;
}

export interface MarketOdds {
  over?: MarketQuote | null;
  under?: MarketQuote | null;
}

export interface CheatRange {
  low: number;
  high: number;
  nominal_coverage?: number;
  level?: number;
  actual_coverage?: number | null;
  method?: string | null;
}

export interface CheatRow extends ProjectionBase, ProjectionMetrics {
  player_id?: number;
  is_home?: boolean;
  game_date?: string | null;
  projection_unit?: string;
  range?: CheatRange;
  market_odds?: MarketOdds;
  rest_days?: number;
  opponent_rest_days?: number;
  spread?: number;
  spread_available?: boolean;
}

export interface CheatSheetEnvelope {
  projections: CheatRow[];
  game?: Game;
  date?: string;
  bookmaker?: string | null;
  odds_source?: string | null;
  odds?: CheatSheetOddsStatus;
  generated_at?: string | null;
  model_version?: string | null;
  season?: string | null;
  warnings?: string[];
  projection_status?: Record<string, Record<string, string | number | boolean | null>>;
}

export interface CheatSheetOddsStatus {
  available: boolean;
  fresh?: boolean | null;
  stale_quote_count?: number;
  max_actionable_age_seconds?: number;
  source?: string | null;
  fetched_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
}

export type CheatSheetResponse = CheatRow[] | CheatSheetEnvelope;

export type PredictAnalysis = ProjectionMetrics;

export interface SimulationRange {
  low: number;
  high: number;
  level: number;
  actual_coverage?: number | null;
  method?: string | null;
}

export interface PredictResponse extends ProjectionBase {
  home_game: boolean;
  analysis?: PredictAnalysis | null;
  range?: SimulationRange | string | null;
  recording?: PredictionRecording | null;
}

export interface PredictionRecording {
  requested: boolean;
  recorded: boolean;
  prediction_id: number | null;
  reason: string | null;
}

export interface PredictRequest {
  player: string;
  opponent: string;
  spread: number;
  line: number | null;
  over_odds: number | null;
  under_odds: number | null;
  bookmaker: string | null;
  matchup: string | null;
  date: string;
  home_game: boolean | null;
  record_prediction: boolean;
}

export interface ApiErrorPayload {
  error?: string;
  message?: string;
}
