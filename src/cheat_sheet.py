"""
Cheat-sheet projection pipeline. Extracted from app.py so it can be tested
independently of the Flask layer.
"""
from src.utils import normalize_name, get_logger
from src.recommendation import weighted_hit_rate, tier_from_signals, edge_from_odds

log = get_logger('cheat_sheet')


def project_team(loader, engineer, simulator, team_id, team_abbr, opp_abbr,
                 is_home, team_rest, opp_rest, player_odds, date_str=None):
    """
    Build projections for every rostered player on one team.
    Returns a list of dicts sorted by projection desc.
    """
    roster = loader.get_team_roster(team_id)
    if roster.empty:
        return []

    results = []
    for _, row in roster.iterrows():
        pid = row['PLAYER_ID']
        pname = row['PLAYER']
        try:
            proj_data = engineer.compute_composite_projection(
                pid, opp_abbr, spread=0,
                home_game=is_home,
                days_rest=team_rest,
                opp_days_rest=opp_rest,
            )
            if not proj_data or 'error' in proj_data:
                continue

            mean_proj = proj_data['projection']

            # Match odds by normalized player name.
            odds_entry = player_odds.get(normalize_name(pname), {})
            line = odds_entry.get('line')
            odds_val = odds_entry.get('odds')

            direction = '-'
            tier = '-'
            over_prob = None
            under_prob = None
            confidence = None
            edge = None

            if line is not None:
                player_var = proj_data.get('player_variance')
                sim_res = simulator.simulate(proj_data, market_line=line, player_variance=player_var)
                probs = simulator.get_probabilities(sim_res, line)
                over_prob = probs['over_probability']
                under_prob = probs['under_probability']
                confidence = max(over_prob, under_prob)
                direction = 'OVER' if over_prob > under_prob else 'UNDER'

                trend = proj_data.get('trend_data', [])
                hit_rate, n_games = weighted_hit_rate(trend, line, direction)
                floor_val = probs['ci_68'][0]
                tier, _ = tier_from_signals(confidence, direction, line, floor_val, hit_rate, n_games,
                                            mean_proj=mean_proj)

                edge = edge_from_odds(confidence, int(odds_val) if odds_val is not None else None)['edge']

            rest_note = 'Home' if is_home else 'Away'
            if team_rest == 0:
                rest_note += ' B2B'

            entry = {
                'player': pname,
                'team': team_abbr,
                'opponent': opp_abbr,
                'projection': round(mean_proj, 1),
                'line': line if line is not None else '-',
                'direction': direction,
                'tier': tier,
                'rest_note': rest_note,
                'context': proj_data.get('matchup_context', ''),
                'components': proj_data.get('components', {}),
                'trend': proj_data.get('trend_data', []),
                'edge_raw': edge if edge is not None else 0,
            }

            # Summary narrative needs the fields we just computed.
            proj_data_for_summary = dict(proj_data)
            proj_data_for_summary.update({
                'player': pname,
                'projection': mean_proj,
                'tier': tier,
                'direction': direction,
                'confidence': confidence,
                'edge': edge,
            })
            entry['summary'] = engineer.generate_pick_summary(proj_data_for_summary, line)

            if confidence is not None:
                entry['confidence'] = round(confidence * 100, 1)
            # Record prediction to ledger
            if line is not None and tier not in ('AVOID', 'LOW_VOLUME', '-'):
                try:
                    from src.ledger import PredictionLedger
                    ledger = PredictionLedger()
                    ledger.record_prediction(
                        game_date=date_str or '1970-01-01',
                        player=pname,
                        team=team_abbr,
                        opponent=opp_abbr,
                        is_home=is_home,
                        projection=mean_proj,
                        line=line,
                        american_odds=int(odds_val) if odds_val is not None else -110,
                        direction=direction,
                        tier=tier,
                        confidence=confidence,
                        over_prob=over_prob,
                        under_prob=under_prob,
                        ev_roi=edge if edge is not None else 0.0
                    )
                except Exception as e:
                    log.warning(f"Failed to record ledger: {e}")

            results.append(entry)

        except Exception as err:
            log.warning(f"Skipping {pname}: {err}")
            continue

    results.sort(key=lambda x: x['projection'], reverse=True)
    return results
