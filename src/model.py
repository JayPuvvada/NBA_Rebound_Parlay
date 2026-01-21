import numpy as np
from scipy import stats

class ReboundSimulator:
    def __init__(self, num_simulations=10000):
        self.num_simulations = num_simulations

    def fit_negative_binomial(self, mean, variance):
        """
        Method of moments for Negative Binomial.
        Mean = n * (1-p) / p  (using scipy nbinom notations usually n, p)
        Scipy: n = number of successes, p = probability of success. 
        Mean = n(1-p)/p
        Var = n(1-p)/p^2
        
        Solving for p:
        Var/Mean = 1/p => p = Mean/Var
        But Var > Mean for NB.
        So p = Mean / Variance
        
        Solving for n (r):
        Mean = n(1-p)/p 
        n = Mean * p / (1-p)
        """
        if variance <= mean:
            # Fallback to Poisson if under-dispersed or equal (though practically unlikely for sums of components)
            # Or force slight overdispersion
            variance = mean * 1.01

        p = mean / variance
        n = mean * p / (1 - p)
        return n, p

    def simulate(self, projection_data, market_line=None):
        """
        Simulates outcomes using Negative Binomial distribution.
        If market_line is provided, blends Model Projection with Market Line (Bayesian Update).
        """
        # Support both new 'projection' key and old 'mean_projection' key for backward compatibility
        model_mean = projection_data.get('projection', projection_data.get('mean_projection'))
        if model_mean is None:
            raise ValueError("Projection data missing 'projection' or 'mean_projection' key")

        # --- A. Market Anchoring (Posterior Mean) ---
        # If we have a market line, we treat it as a high-confidence prior.
        # This prevents the model from being "stubbornly wrong" if the market knows something (e.g. injury)
        
        if market_line:
            # Weighting: How much do we trust our model vs the market?
            # Start with 60% Model, 40% Market. 
            w_model = 0.60
            final_mean = (model_mean * w_model) + (market_line * (1 - w_model))
        else:
            final_mean = model_mean

        # --- B. Variance Calculation (Fano Factor) ---
        # Variance = Mean * FanoFactor
        # User request: "Expected minutes-based Fano factor"
        
        # Get Minutes
        minutes = 30.0 # Default
        if 'components' in projection_data:
            minutes = projection_data['components'].get('Proj Minutes', 30.0)
        elif 'modifiers' in projection_data:
            minutes = projection_data['modifiers'].get('minutes', 30.0)
            
        # Logic: Higher minutes = Slightly higher Fano Factor (more time for variance to accumulate?)
        # Actually in Poisson processes, Var=Mean. Overdispersion comes from 'p' shifting.
        # We'll use a curve: 
        # Low Min (<20): 1.15 (Less time for crazy outliers)
        # High Min (>34): 1.35 (Fatigue, role variation, "hot hand" potential)
        
        fano_factor = 1.20 # Base
        if minutes > 34: fano_factor = 1.35
        elif minutes > 28: fano_factor = 1.28
        elif minutes < 20: fano_factor = 1.15
        
        variance = final_mean * fano_factor
        
        # Additional custom variance factor from inputs (if any)
        if 'variance_factor' in projection_data:
            variance *= projection_data['variance_factor']

        # Fit NB
        n, p = self.fit_negative_binomial(final_mean, variance)

        # Run Sim
        samples = np.random.negative_binomial(n, p, self.num_simulations)

        return {
            'mean_sim': np.mean(samples),
            'std_sim': np.std(samples),
            'samples': samples,
            'params': {'n': n, 'p': p, 'final_mean': final_mean, 'model_mean': model_mean, 'fano': fano_factor}
        }

    def get_probabilities(self, sim_result, line):
        samples = sim_result['samples']
        over_prob = np.mean(samples > line)
        under_prob = np.mean(samples < line)
        push_prob = np.mean(samples == line) # For integer lines
        
        # O/U is usually X.5, so push is 0. 
        # If Line is X.0, Push exists.
        
        # Calculate Intervals
        ci_68 = np.percentile(samples, [16, 84])
        ci_95 = np.percentile(samples, [2.5, 97.5])
        
        return {
            'over_probability': over_prob,
            'under_probability': under_prob,
            'push_probability': push_prob,
            'ci_68': ci_68.tolist(),
            'ci_95': ci_95.tolist()
        }

if __name__ == "__main__":
    sim = ReboundSimulator()
    # Test
    dummy_proj = {'mean_projection': 12.88, 'variance_factor': 1.05}
    res = sim.simulate(dummy_proj)
    probs = sim.get_probabilities(res, 12.5)
    
    print(f"Mean Sim: {res['mean_sim']:.2f} (Input: {dummy_proj['mean_projection']})")
    print(f"Prob Over 12.5: {probs['over_probability']:.2%}")
    print(f"95% CI: {probs['ci_95']}")
