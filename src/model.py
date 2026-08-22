import numpy as np


class ReboundSimulator:
    # Fano factor bounds. A player with empirical Fano above HIGH_FANO_FLAG gets a
    # warning in the returned params so the UI can signal low confidence.
    FANO_MIN = 0.8
    FANO_MAX = 5.0
    HIGH_FANO_FLAG = 3.5

    def __init__(self, num_simulations=10000):
        self.num_simulations = num_simulations

    def fit_negative_binomial(self, mean, variance):
        """
        Method of moments for Negative Binomial (scipy parametrization n, p).
        Mean = n(1-p)/p,  Var = n(1-p)/p^2
        => p = Mean / Var,  n = Mean * p / (1-p)
        """
        if variance <= mean:
            # Poisson/under-dispersed fallback: force slight overdispersion.
            variance = mean * 1.01

        p = mean / variance
        n = mean * p / (1 - p)
        return n, p

    def simulate(self, projection_data, market_line=None, player_variance=None):
        """
        Monte Carlo simulation using Negative Binomial distribution.
        Uses the pure model projection (no market anchoring).
        Blends empirical (game-to-game) variance with a minutes-based heuristic.
        """
        model_mean = projection_data.get('projection', projection_data.get('mean_projection'))
        if model_mean is None:
            raise ValueError("Projection data missing 'projection' or 'mean_projection' key")

        final_mean = model_mean

        # Minutes-based heuristic Fano
        minutes = 30.0
        if 'components' in projection_data:
            minutes = projection_data['components'].get('Proj Minutes', 30.0)
        elif 'modifiers' in projection_data:
            minutes = projection_data['modifiers'].get('minutes', 30.0)

        heuristic_fano = 1.20
        if minutes > 34:
            heuristic_fano = 1.35
        elif minutes > 28:
            heuristic_fano = 1.28
        elif minutes < 20:
            heuristic_fano = 1.15

        # Volume-aware Fano floor: low-rebound players are bursty (0 one night, 5 the next).
        # The minutes heuristic alone gives 1.15 for a guard who averages 2 rebounds, which
        # is far too tight — it makes the NB look almost Poisson and creates artificially
        # high confidence on small-integer props. Floor rises as projection falls.
        if final_mean < 3.0:
            volume_fano_floor = 2.0
        elif final_mean < 5.0:
            volume_fano_floor = 1.6
        elif final_mean < 8.0:
            volume_fano_floor = 1.4
        else:
            volume_fano_floor = 1.2

        heuristic_fano = max(heuristic_fano, volume_fano_floor)

        # Empirical Fano: trust real game data if we have enough of it.
        fano_source = "heuristic"
        high_variance_flag = False
        if player_variance and player_variance.get('reb_variance') and player_variance.get('reb_mean'):
            reb_var = player_variance['reb_variance']
            reb_mean = player_variance['reb_mean']
            if reb_mean > 0:
                empirical_fano = reb_var / reb_mean
                if empirical_fano > self.HIGH_FANO_FLAG:
                    high_variance_flag = True
                empirical_fano = max(self.FANO_MIN, min(self.FANO_MAX, empirical_fano))
                # Even with real empirical data, enforce the volume floor so that a few
                # games of a bench player going 0-0-0-0-5 doesn't shrink the distribution.
                empirical_fano = max(empirical_fano, volume_fano_floor)
                fano_factor = (empirical_fano * 0.90) + (heuristic_fano * 0.10)
                fano_source = "empirical"
            else:
                fano_factor = heuristic_fano
        else:
            fano_factor = heuristic_fano

        variance = final_mean * fano_factor

        n, p = self.fit_negative_binomial(final_mean, variance)
        samples = np.random.negative_binomial(n, p, self.num_simulations)

        return {
            'mean_sim': np.mean(samples),
            'std_sim': np.std(samples),
            'samples': samples,
            'params': {
                'n': n,
                'p': p,
                'final_mean': final_mean,
                'model_mean': model_mean,
                'fano': round(fano_factor, 3),
                'fano_source': fano_source,
                'high_variance_flag': high_variance_flag,
            }
        }

    def get_probabilities(self, sim_result, line):
        from scipy.stats import nbinom
        
        samples = sim_result['samples']
        n = sim_result['params']['n']
        p = sim_result['params']['p']
        
        k_floor = int(np.floor(line))
        k_ceil = int(np.ceil(line))
        
        # scipy.stats.nbinom.cdf(k, n, p) = P(X <= k)
        cdf_floor = nbinom.cdf(k_floor, n, p)
        cdf_below = nbinom.cdf(k_ceil - 1, n, p) if k_ceil - 1 >= 0 else 0.0
        
        return {
            'over_probability': float(1.0 - cdf_floor),
            'under_probability': float(cdf_below),
            'push_probability': float(cdf_floor - cdf_below),
            'ci_68': np.percentile(samples, [16, 84]).tolist(),
            'ci_95': np.percentile(samples, [2.5, 97.5]).tolist(),
        }


if __name__ == "__main__":
    sim = ReboundSimulator()
    dummy_proj = {'mean_projection': 12.88}
    res = sim.simulate(dummy_proj)
    probs = sim.get_probabilities(res, 12.5)
    print(f"Mean Sim: {res['mean_sim']:.2f} (Input: {dummy_proj['mean_projection']})")
    print(f"Prob Over 12.5: {probs['over_probability']:.2%}")
    print(f"95% CI: {probs['ci_95']}")
