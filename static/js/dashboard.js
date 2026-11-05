// Dashboard Data & Charts Manager

let timelineChart = null;
let riskDistChart = null;
let suspiciousDonutChart = null;
let methodBarChart = null;

async function loadDashboardData() {
    try {
        // 1. Fetch Overview KPIs
        const overviewRes = await fetch("/api/dashboard/overview");
        if (overviewRes.ok) {
            const data = await overviewRes.json();
            document.getElementById("kpi-total-tx").innerText = data.total_transactions.toLocaleString();
            document.getElementById("kpi-total-volume").innerText = "$" + data.total_volume.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
            document.getElementById("kpi-suspicious-tx").innerText = data.suspicious_transactions.toLocaleString();
            
            const highRiskTotal = (data.high_risk_accounts || 0) + (data.critical_risk_accounts || 0);
            document.getElementById("kpi-high-risk-acc").innerText = highRiskTotal.toLocaleString();
            document.getElementById("kpi-fraud-rings").innerText = data.detected_fraud_rings.toLocaleString();
            document.getElementById("kpi-communities").innerText = data.total_communities.toLocaleString();

            const detectionRate = ((data.suspicious_transactions / (data.total_transactions || 1)) * 100).toFixed(1);
            document.getElementById("kpi-rate-sub").innerText = `${detectionRate}% of total flow`;
        }

        // 2. Fetch Charts Data
        const chartsRes = await fetch("/api/dashboard/charts");
        if (chartsRes.ok) {
            const chartData = await chartsRes.json();
            renderTimelineChart(chartData.timeline || []);
            renderRiskDistChart(chartData.risk_distribution || {});
            renderSuspiciousChart(chartData.timeline || []);
            renderMethodBarChart(chartData.detection_methods || {});
            renderTopRiskAccounts(chartData.top_risk_accounts || []);
        }

        // 3. Fetch Recent Flagged Activity
        const activityRes = await fetch("/api/dashboard/recent-activity");
        if (activityRes.ok) {
            const actData = await activityRes.json();
            renderRecentFlagged(actData.recent_flagged_transactions || []);
        }

    } catch (err) {
        console.error("Failed to load dashboard data:", err);
    }
}

function renderTimelineChart(timeline) {
    const ctx = document.getElementById("timelineChart").getContext("2d");
    const labels = timeline.map(t => t.tx_date.substring(5)); // MM-DD
    const volumes = timeline.map(t => t.volume);
    const suspiciousCounts = timeline.map(t => t.suspicious_count);

    if (timelineChart) timelineChart.destroy();

    timelineChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Daily Volume ($)",
                    data: volumes,
                    borderColor: "#3b82f6",
                    backgroundColor: "rgba(59, 130, 246, 0.1)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    yAxisID: "y"
                },
                {
                    label: "Flagged Transfers",
                    data: suspiciousCounts,
                    borderColor: "#f59e0b",
                    backgroundColor: "rgba(245, 158, 11, 0.8)",
                    borderWidth: 1.5,
                    type: "bar",
                    yAxisID: "y1"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8" } },
                y: {
                    position: "left",
                    grid: { color: "rgba(255, 255, 255, 0.05)" },
                    ticks: { color: "#94a3b8", callback: val => "$" + (val / 1000).toFixed(0) + "k" }
                },
                y1: {
                    position: "right",
                    grid: { drawOnChartArea: false },
                    ticks: { color: "#f59e0b", stepSize: 2 }
                }
            },
            plugins: {
                legend: { labels: { color: "#cbd5e1" } }
            }
        }
    });
}

function renderRiskDistChart(riskDist) {
    const ctx = document.getElementById("riskDistChart").getContext("2d");
    if (riskDistChart) riskDistChart.destroy();

    const labels = ["Low", "Medium", "High", "Critical"];
    const counts = labels.map(l => riskDist[l] || 0);

    riskDistChart = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: labels,
            datasets: [{
                data: counts,
                backgroundColor: ["#10b981", "#f59e0b", "#f97316", "#ef4444"],
                borderColor: "#151d2c",
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "right", labels: { color: "#cbd5e1" } }
            }
        }
    });
}

function renderSuspiciousChart(timeline) {
    const ctx = document.getElementById("suspiciousDonutChart").getContext("2d");
    if (suspiciousDonutChart) suspiciousDonutChart.destroy();

    const totalCount = timeline.reduce((acc, t) => acc + t.count, 0);
    const suspiciousCount = timeline.reduce((acc, t) => acc + t.suspicious_count, 0);
    const normalCount = Math.max(0, totalCount - suspiciousCount);

    suspiciousDonutChart = new Chart(ctx, {
        type: "pie",
        data: {
            labels: ["Legitimate Transactions", "Suspicious / Flagged"],
            datasets: [{
                data: [normalCount, suspiciousCount],
                backgroundColor: ["#3b82f6", "#ef4444"],
                borderColor: "#151d2c",
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "right", labels: { color: "#cbd5e1" } }
            }
        }
    });
}

function renderMethodBarChart(methods) {
    const ctx = document.getElementById("methodBarChart").getContext("2d");
    if (methodBarChart) methodBarChart.destroy();

    const labels = ["Rule Engine", "Isolation Forest", "Random Forest", "Correlated Both"];
    const values = [
        methods.rule_based_count || 0,
        methods.isolation_forest_count || 0,
        methods.random_forest_count || 0,
        methods.multi_model_count || 0,
    ];

    methodBarChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: labels,
            datasets: [{
                label: "Flags Generated",
                data: values,
                backgroundColor: ["#8b5cf6", "#06b6d4", "#3b82f6", "#ec4899"],
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { display: false }, ticks: { color: "#94a3b8" } },
                y: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8" } }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

function renderTopRiskAccounts(accounts) {
    const tbody = document.getElementById("top-risk-table-body");
    if (!accounts || accounts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center py-3 text-muted">No high risk accounts.</td></tr>`;
        return;
    }

    tbody.innerHTML = accounts.map(a => {
        let badgeClass = "badge-risk-low";
        if (a.risk_category === "Critical") badgeClass = "badge-risk-critical";
        else if (a.risk_category === "High") badgeClass = "badge-risk-high";
        else if (a.risk_category === "Medium") badgeClass = "badge-risk-medium";

        return `
            <tr>
                <td><a href="/investigation?account_id=${a.account_id}" class="fw-bold text-decoration-none text-white">${a.account_id}</a></td>
                <td><span class="fw-bold">${a.graph_risk_score.toFixed(1)}</span></td>
                <td><span class="${badgeClass}">${a.risk_category}</span></td>
                <td class="text-secondary">Out: ${a.out_degree} &bull; In: ${a.in_degree}</td>
                <td>
                    <a href="/investigation?account_id=${a.account_id}" class="btn btn-xs btn-outline-primary py-0 px-2 small">Inspect</a>
                </td>
            </tr>
        `;
    }).join("");
}

function renderRecentFlagged(txs) {
    const tbody = document.getElementById("recent-flagged-table-body");
    if (!txs || txs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center py-3 text-muted">No recent flagged transfers.</td></tr>`;
        return;
    }

    tbody.innerHTML = txs.map(t => {
        const amt = "$" + Number(t.amount).toLocaleString(undefined, {minimumFractionDigits: 2});
        return `
            <tr>
                <td><span class="badge bg-dark border border-secondary">${t.transaction_id}</span></td>
                <td class="small"><b>${t.sender_account}</b> &rarr; <b>${t.receiver_account}</b></td>
                <td class="fw-bold text-white">${amt}</td>
                <td class="text-secondary small">${t.timestamp.substring(5, 16)}</td>
                <td>
                    <span class="badge bg-danger-subtle text-danger border border-danger-subtle">ANOMALY</span>
                </td>
            </tr>
        `;
    }).join("");
}

// Initial Load
document.addEventListener("DOMContentLoaded", loadDashboardData);
