// System Monitoring Manager

async function loadMonitoringData() {
    try {
        const res = await fetch("/api/system/health");
        if (res.ok) {
            const data = await res.json();
            document.getElementById("mon-api-status").innerText = data.status.toUpperCase();
            document.getElementById("mon-api-status").className = data.status === "healthy" ? "stat-kpi-value text-success" : "stat-kpi-value text-warning";
            document.getElementById("mon-db-status").innerText = data.database_connected ? "CONNECTED" : "DISCONNECTED";
            document.getElementById("mon-db-status").className = data.database_connected ? "stat-kpi-value text-success" : "stat-kpi-value text-danger";
            document.getElementById("mon-cache-status").innerText = data.graph_cached ? "ACTIVE" : "STANDBY";
            document.getElementById("mon-uptime").innerText = `${data.uptime_seconds || 0}s`;
        }

        const statsRes = await fetch("/api/system/statistics");
        if (statsRes.ok) {
            const stats = await statsRes.json();
            const ov = stats.overview || {};
            document.getElementById("mon-cache-sub").innerText = `${stats.graph_cache_nodes || ov.total_accounts || 150} Nodes • ${ov.total_transactions || 2500} Edges`;
        }
    } catch (err) {
        console.error("Failed to load monitoring data:", err);
    }
}

document.addEventListener("DOMContentLoaded", loadMonitoringData);
