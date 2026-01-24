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

            // Color Logic & Tier Handling
            banner.style.color = '#fff';
            let bg = 'rgba(239, 68, 68, 0.2)'; // Red default
            let border = 'rgba(239, 68, 68, 0.4)';
            let text = '#f87171';

            if (data.analysis.rec_color === 'green') {
                bg = 'rgba(16, 185, 129, 0.2)';
                border = 'rgba(16, 185, 129, 0.4)';
                text = '#34d399';
            } else if (data.analysis.rec_color === 'blue') { // Safe Play
                bg = 'rgba(59, 130, 246, 0.2)';
                border = 'rgba(59, 130, 246, 0.4)';
                text = '#60a5fa';
            } else if (data.analysis.rec_color === 'purple') { // Trend Lean
                bg = 'rgba(139, 92, 246, 0.2)';
                border = 'rgba(139, 92, 246, 0.4)';
                text = '#a78bfa';
            } else if (data.analysis.rec_color === 'yellow') {
                bg = 'rgba(245, 158, 11, 0.2)';
                border = 'rgba(245, 158, 11, 0.4)';
                text = '#fbbf24';
            }

            banner.style.background = bg;
            banner.style.border = `1px solid ${border}`;
            banner.style.color = text;

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

        // Render Chart
        if (data.trend && data.trend.length > 0) {
            renderTrendChart(data.trend, data.analysis ? data.analysis.line : null);
        }

        // Factors (Existing logic...)
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

    let chartInstance = null;

    function renderTrendChart(trendData, line) {
        const ctx = document.getElementById('trendChart').getContext('2d');

        if (chartInstance) {
            chartInstance.destroy(); // Destroy previous chart to avoid overlays
        }

        // Prepare Data
        // trendData = [{date, rebounds, opponent, minutes}, ...] (Oldest to Newest)
        const labels = trendData.map(d => `${d.opponent}`); // X Axis: Opponent Code
        const dataPoints = trendData.map(d => d.rebounds);

        // Colors: Green if above line, Red if below (only if line exists)
        const bgColors = dataPoints.map(val => {
            if (line === null) return 'rgba(54, 162, 235, 0.6)'; // Blue default
            return val > line ? 'rgba(34, 197, 94, 0.7)' : 'rgba(239, 68, 68, 0.7)';
        });

        chartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Rebounds',
                    data: dataPoints,
                    backgroundColor: bgColors,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `Rebounds: ${ctx.raw} (${trendData[ctx.dataIndex].date})`
                        }
                    },
                    annotation: {
                        annotations: line ? {
                            line1: {
                                type: 'line',
                                yMin: line,
                                yMax: line,
                                borderColor: 'rgba(255, 255, 255, 0.5)',
                                borderWidth: 2,
                                borderDash: [5, 5],
                            }
                        } : {}
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        ticks: { color: '#ccc' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#ccc' }
                    }
                }
            }
        });
    }

    // --- CHEAT SHEET LOGIC ---
    const csBtn = document.getElementById('cheat-sheet-btn');
    const csModal = document.getElementById('cs-modal');
    const closeModal = document.getElementById('close-modal');
    const csBody = document.getElementById('cs-body');
    const csLoading = document.getElementById('cs-loading');

    // New Inputs
    const csRunBtn = document.getElementById('cs-run-btn');
    const csDateInput = document.getElementById('cs-date');
    const csTeamInput = document.getElementById('cs-team');
    const csBookInput = document.getElementById('cs-book');

    if (csBtn) {
        csBtn.addEventListener('click', () => {
            csModal.classList.remove('hidden');
            // Set default date to today if empty
            if (csDateInput && !csDateInput.value) {
                const today = new Date().toISOString().split('T')[0];
                csDateInput.value = today;
            }
        });

        if (closeModal) {
            closeModal.addEventListener('click', () => {
                csModal.classList.add('hidden');
            });
        }

        // Window click to close
        window.addEventListener('click', (e) => {
            if (e.target === csModal) {
                csModal.classList.add('hidden');
            }
        });

        // Run Button Listener
        if (csRunBtn) {
            csRunBtn.addEventListener('click', async () => {
                const date = csDateInput.value;
                const team = csTeamInput.value;
                const book = csBookInput.value;

                if (!date || !team) {
                    alert("Please select a Date and a Team.");
                    return;
                }

                await loadCheatSheet(date, team, book);
            });
        }
    }

    async function loadCheatSheet(date, team, book) {
        if (!csLoading) return;

        csLoading.classList.remove('hidden');
        if (csBody) csBody.innerHTML = '';

        try {
            const res = await fetch(`/cheat-sheet?date=${date}&team=${team}&book=${book}`);
            const data = await res.json();

            csLoading.classList.add('hidden');

            if (data.error) {
                csBody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:red;">${data.error}</td></tr>`;
                return;
            }

            if (data.length === 0) {
                csBody.innerHTML = `<tr><td colspan="6" style="text-align:center;">No players found.</td></tr>`;
                return;
            }

            data.forEach((row, idx) => {
                const tr = document.createElement('tr');
                tr.className = 'player-row';
                tr.dataset.idx = idx;

                // Tier Color Class
                let tierClass = "";
                if (row.tier.includes("STRONG")) tierClass = "tier-strong";
                else if (row.tier.includes("PLAY")) tierClass = "tier-play";
                else if (row.tier.includes("SAFE")) tierClass = "tier-safe";
                else if (row.tier.includes("LEAN")) tierClass = "tier-lean";
                else tierClass = "tier-avoid";

                // Direction styling
                let dirClass = row.direction === "OVER" ? "dir-over" : "dir-under";

                tr.innerHTML = `
                    <td>
                        <div style="font-weight:bold;">${row.player} <span style="font-size:0.7rem; color:#6b7280;">▼</span></div>
                        <div style="font-size:0.8rem; color:#9ca3af;">${row.team}</div>
                    </td>
                    <td>vs ${row.opponent} <span style="font-size:0.7rem;">(${row.rest_note})</span></td>
                    <td style="font-size:1.1rem; font-weight:bold; color:#a5b4fc;">${row.projection}</td>
                    <td>${row.line}</td>
                    <td class="${dirClass}" style="font-weight:bold;">${row.direction}</td>
                    <td class="${tierClass}">${row.tier}</td>
                `;

                // Click handler for detail expansion
                tr.addEventListener('click', () => {
                    togglePlayerDetail(row, tr, idx);
                });

                csBody.appendChild(tr);
            });

        } catch (err) {
            console.error(err);
            csLoading.classList.add('hidden');
            csBody.innerHTML = `<tr><td colspan="6">Error loading data. Check console.</td></tr>`;
        }
    }

    // Track currently open detail row
    let openDetailIdx = null;

    function togglePlayerDetail(row, tr, idx) {
        // If clicking same row, close it
        const existingDetail = document.querySelector('.player-detail-row');
        if (existingDetail) {
            existingDetail.remove();
            if (openDetailIdx === idx) {
                openDetailIdx = null;
                return;
            }
        }

        openDetailIdx = idx;

        // Create detail row
        const detailTr = document.createElement('tr');
        detailTr.className = 'player-detail-row';

        const detailTd = document.createElement('td');
        detailTd.colSpan = 6;
        detailTd.innerHTML = renderDetailPanel(row);

        detailTr.appendChild(detailTd);
        tr.insertAdjacentElement('afterend', detailTr);

        // Render mini trend chart if trend data exists
        if (row.trend && row.trend.length > 0) {
            setTimeout(() => {
                renderMiniTrendChart(row.trend, row.line, row.player_id);
            }, 100);
        }
    }

    function renderDetailPanel(row) {
        // Probabilities section
        let probsHtml = '';
        if (row.line !== '-') {
            const edge = row.edge_raw ? (row.edge_raw * 100).toFixed(1) : '0';
            probsHtml = `
                <div class="detail-probs">
                    <div class="prob-item">
                        <span class="prob-label">Over Prob</span>
                        <span class="prob-val dir-over">${row.over_prob}%</span>
                    </div>
                    <div class="prob-item">
                        <span class="prob-label">Under Prob</span>
                        <span class="prob-val dir-under">${row.under_prob}%</span>
                    </div>
                    <div class="prob-item">
                        <span class="prob-label">Edge</span>
                        <span class="prob-val" style="color:#fbbf24;">${edge}%</span>
                    </div>
                </div>
            `;
        }

        // Trend chart placeholder
        let trendHtml = '';
        if (row.trend && row.trend.length > 0) {
            trendHtml = `
                <div class="detail-trend">
                    <div class="trend-title">Last ${row.trend.length} Games</div>
                    <div style="height: 120px;">
                        <canvas id="mini-chart-${row.player_id}"></canvas>
                    </div>
                </div>
            `;
        }

        return `
            <div class="detail-panel">
                <div class="detail-header">
                    <span class="detail-player">${row.player}</span>
                    <span class="detail-matchup">${row.team} vs ${row.opponent} • Proj: ${row.projection} | Line: ${row.line}</span>
                </div>
                <div class="detail-body-simple">
                    ${probsHtml}
                    ${trendHtml}
                </div>
            </div>
        `;
    }

    // Store mini chart instances
    const miniCharts = {};

    function renderMiniTrendChart(trendData, line, playerId) {
        const canvasId = `mini-chart-${playerId}`;
        const canvas = document.getElementById(canvasId);
        if (!canvas) {
            console.log('Canvas not found:', canvasId);
            return;
        }

        const ctx = canvas.getContext('2d');

        // Destroy existing chart if present
        if (miniCharts[canvasId]) {
            miniCharts[canvasId].destroy();
        }

        const labels = trendData.map(d => d.opponent);
        const dataPoints = trendData.map(d => d.rebounds);
        const lineVal = typeof line === 'number' ? line : null;

        const bgColors = dataPoints.map(val => {
            if (lineVal === null) return 'rgba(165, 180, 252, 0.7)';
            return val > lineVal ? 'rgba(34, 197, 94, 0.7)' : 'rgba(248, 113, 113, 0.7)';
        });

        miniCharts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: dataPoints,
                    backgroundColor: bgColors,
                    borderRadius: 3,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    annotation: {
                        annotations: lineVal ? {
                            line1: {
                                type: 'line',
                                yMin: lineVal,
                                yMax: lineVal,
                                borderColor: 'rgba(255, 255, 255, 0.5)',
                                borderWidth: 1,
                                borderDash: [3, 3],
                            }
                        } : {}
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#888', font: { size: 10 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#888', font: { size: 9 } }
                    }
                }
            }
        });
    }

});
