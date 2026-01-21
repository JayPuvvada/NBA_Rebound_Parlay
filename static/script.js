document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('predict-form');
    const submitBtn = document.getElementById('submit-btn');
    const loader = document.getElementById('loader');
    const btnText = document.querySelector('.btn-text');
    const errorMsg = document.getElementById('error-msg');

    const resultsCard = document.getElementById('results-card');
    const emptyState = document.getElementById('empty-state');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // UI Loading State
        setLoading(true);
        errorMsg.classList.add('hidden');
        resultsCard.classList.add('hidden');
        emptyState.classList.remove('hidden'); // momentarily keep empty or hide it

        const formData = new FormData(form);
        const payload = {
            player: formData.get('player'),
            opponent: formData.get('opponent'),
            spread: formData.get('spread'),
            line: formData.get('line'),
            matchup: formData.get('matchup')
        };

        try {
            const response = await fetch('/predict', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Server error occurred');
            }

            // Success: Display Results
            displayResults(data);

        } catch (err) {
            errorMsg.textContent = err.message;
            errorMsg.classList.remove('hidden');
        } finally {
            setLoading(false);
        }
    });

    function setLoading(isLoading) {
        if (isLoading) {
            submitBtn.disabled = true;
            loader.style.display = 'block';
            btnText.textContent = 'Simulating...';
        } else {
            submitBtn.disabled = false;
            loader.style.display = 'none';
            btnText.textContent = 'Run Simulation';
        }
    }

    function displayResults(data) {
        // Toggle Sections
        emptyState.classList.add('hidden');
        resultsCard.classList.remove('hidden');

        // Header
        document.getElementById('res-player').textContent = data.player;
        document.getElementById('res-opp').textContent = `vs ${data.opponent} (${data.context})`;
        document.getElementById('res-proj').textContent = data.projection;

        // Analysis (Line provided)
        const analysisDiv = document.getElementById('analysis-container');
        if (data.analysis) {
            analysisDiv.classList.remove('hidden');

            // Rec Banner
            const banner = document.getElementById('res-rec-banner');
            document.getElementById('res-rec-text').textContent = data.analysis.recommendation;

            // Color Logic
            banner.style.color = '#fff';
            if (data.analysis.rec_color === 'green') {
                banner.style.background = 'rgba(16, 185, 129, 0.2)';
                banner.style.border = '1px solid rgba(16, 185, 129, 0.4)';
                banner.style.color = '#34d399';
            } else if (data.analysis.rec_color === 'yellow') {
                banner.style.background = 'rgba(245, 158, 11, 0.2)';
                banner.style.border = '1px solid rgba(245, 158, 11, 0.4)';
                banner.style.color = '#fbbf24';
            } else {
                banner.style.background = 'rgba(239, 68, 68, 0.2)';
                banner.style.border = '1px solid rgba(239, 68, 68, 0.4)';
                banner.style.color = '#f87171';
            }

            document.getElementById('res-over').textContent = data.analysis.over_prob + '%';
            document.getElementById('res-under').textContent = data.analysis.under_prob + '%';
            document.getElementById('res-edge').textContent = data.analysis.edge + '%';
        } else {
            analysisDiv.classList.add('hidden');
        }

        // Summary
        // Parse basic markdown bolding (**text**) -> <b>text</b>
        let summaryText = data.summary || "No summary available.";
        summaryText = summaryText.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
        document.getElementById('res-summary').innerHTML = summaryText;

        // Factors
        const factorsList = document.getElementById('res-factors');
        factorsList.innerHTML = '';
        if (data.components) {
            // Define keys that are multipliers requiring interpretation
            const multiplierKeys = ['Pace', 'Opp', 'DvP', 'Matchup', 'Env Mult (Final)'];

            for (const [key, val] of Object.entries(data.components)) {

                let displayVal = val;
                let label = "";
                let colorClass = "neutral";
                let isMultiplier = false;

                // 1. Handle Multipliers
                if (multiplierKeys.includes(key) || (typeof val === 'number' && val > 0.5 && val < 1.5 && key !== 'Base Rebs')) {
                    isMultiplier = true;
                    displayVal = val.toFixed(2); // Show 2 decimals

                    if (val >= 1.05) {
                        label = "🔥 Great Boost";
                        colorClass = "good-strong";
                    } else if (val >= 1.01) {
                        label = "✅ Favorable";
                        colorClass = "good";
                    } else if (val <= 0.95) {
                        label = "🛑 Very Tough";
                        colorClass = "bad-strong";
                    } else if (val <= 0.99) {
                        label = "⚠️ Difficult";
                        colorClass = "bad";
                    } else {
                        label = "➖ Neutral";
                        colorClass = "neutral";
                    }
                }
                // 2. Handle Raw Stats
                else if (typeof val === 'number') {
                    displayVal = val.toFixed(1);
                    label = ""; // No specific label for raw base stats
                }

                const div = document.createElement('div');
                div.className = 'factor-item';

                if (isMultiplier) {
                    div.innerHTML = `
                        <span class="factor-name">${key}</span>
                        <div class="factor-right">
                            <span class="factor-label ${colorClass}">${label}</span>
                            <span class="factor-val-faded">(${displayVal}x)</span>
                        </div>`;
                } else {
                    div.innerHTML = `
                        <span class="factor-name">${key}</span>
                        <span class="factor-val">${displayVal}</span>`;
                }

                factorsList.appendChild(div);
            }
        }

        // Injuries (Expanded Grid)
        const injBox = document.getElementById('res-injuries');
        injBox.innerHTML = ''; // Clear previous

        // 1. Specific Matchup/Impact Note (Previous logic legacy support)
        if (data.injuries.matchup || data.injuries.team) {
            const warningDiv = document.createElement('div');
            warningDiv.className = 'injury-warning-box';
            if (data.injuries.matchup) warningDiv.innerHTML += `<p>🚑 <strong>Matchup Alert:</strong> ${data.injuries.matchup}</p>`;
            if (data.injuries.team) warningDiv.innerHTML += `<p>🏥 <strong>Impact Alert:</strong> ${data.injuries.team}</p>`;
            injBox.appendChild(warningDiv);
        }

        // 2. Full Team Lists
        const injGrid = document.createElement('div');
        injGrid.className = 'injury-grid';

        // Helper to create list
        const createList = (title, list, colorClass) => {
            const col = document.createElement('div');
            col.className = 'injury-col';
            col.innerHTML = `<h4 class="${colorClass}">${title}</h4>`;
            if (list && list.length > 0) {
                const ul = document.createElement('ul');
                list.forEach(item => {
                    const li = document.createElement('li');
                    li.textContent = item;
                    ul.appendChild(li);
                });
                col.appendChild(ul);
            } else {
                col.innerHTML += `<p class="no-injuries">No active injuries reported.</p>`;
            }
            return col;
        };

        injGrid.appendChild(createList("Team Injuries", data.injuries.team_list, "text-red"));
        injGrid.appendChild(createList("Opponent Injuries", data.injuries.opp_list, "text-red"));

        injBox.appendChild(injGrid);
        injBox.classList.remove('hidden');
    }
});
