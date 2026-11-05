// Cytoscape.js Financial Network Visualizer

let cy = null;

async function loadGraphVisualization() {
    const accountFilter = document.getElementById("graph-account-filter").value.trim().toUpperCase();
    const riskFilter = document.getElementById("graph-risk-filter").value;
    const minAmount = document.getElementById("graph-min-amount").value;
    const suspiciousOnly = document.getElementById("graph-suspicious-toggle").checked;

    const params = new URLSearchParams();
    if (accountFilter) params.append("account_id", accountFilter);
    if (riskFilter) params.append("risk_category", riskFilter);
    if (minAmount) params.append("min_amount", minAmount);
    if (suspiciousOnly) params.append("only_suspicious", "true");
    params.append("limit", "400"); // Bound to ensure responsive rendering

    document.getElementById("graph-loading").style.display = "flex";

    try {
        const res = await fetch(`/api/graph/visualization?${params.toString()}`);
        if (!res.ok) throw new Error("Failed to load visualization payload");
        const payload = await res.json();

        initCytoscape(payload.elements);
    } catch (err) {
        console.error("Graph render error:", err);
    } finally {
        document.getElementById("graph-loading").style.display = "none";
    }
}

function initCytoscape(elements) {
    if (cy) {
        cy.destroy();
    }

    cy = cytoscape({
        container: document.getElementById("cy-container"),
        elements: elements,
        style: [
            // Node Styling
            {
                selector: "node",
                style: {
                    "label": "data(id)",
                    "color": "#f8fafc",
                    "font-size": "10px",
                    "font-weight": "bold",
                    "text-valign": "center",
                    "text-halign": "center",
                    "width": "34px",
                    "height": "34px",
                    "border-width": 2,
                    "border-color": "#ffffff",
                    "background-color": function(ele) {
                        const cat = ele.data("risk_category");
                        if (cat === "Critical") return "#ef4444";
                        if (cat === "High") return "#f97316";
                        if (cat === "Medium") return "#f59e0b";
                        return "#10b981";
                    }
                }
            },
            // Highlighting cycle members
            {
                selector: "node[?is_in_cycle]",
                style: {
                    "border-color": "#fbbf24",
                    "border-width": 4,
                    "shadow-blur": 15,
                    "shadow-color": "#fbbf24",
                    "shadow-opacity": 0.8
                }
            },
            // Node Selected State
            {
                selector: "node:selected",
                style: {
                    "border-color": "#38bdf8",
                    "border-width": 5,
                    "width": "42px",
                    "height": "42px"
                }
            },
            // Edge Styling
            {
                selector: "edge",
                style: {
                    "width": function(ele) {
                        const amt = ele.data("amount") || 100;
                        return Math.max(1.5, Math.min(8.0, Math.log10(amt)));
                    },
                    "curve-style": "bezier",
                    "target-arrow-shape": "triangle",
                    "target-arrow-color": "#475569",
                    "line-color": "#475569",
                    "arrow-scale": 0.8,
                    "opacity": 0.7
                }
            },
            // Flagged Edges
            {
                selector: "edge[?is_flagged]",
                style: {
                    "line-color": "#ef4444",
                    "target-arrow-color": "#ef4444",
                    "opacity": 0.95
                }
            },
            // Cycle Edges (Laundering Hops)
            {
                selector: "edge[?is_cycle_edge]",
                style: {
                    "line-color": "#fbbf24",
                    "target-arrow-color": "#fbbf24",
                    "line-style": "dashed",
                    "line-dash-pattern": [6, 3],
                    "width": 3.5,
                    "opacity": 1.0
                }
            },
            // Edge Selected State
            {
                selector: "edge:selected",
                style: {
                    "line-color": "#38bdf8",
                    "target-arrow-color": "#38bdf8",
                    "width": 5
                }
            }
        ],
        layout: {
            name: "cose",
            idealEdgeLength: 100,
            nodeOverlap: 20,
            refresh: 20,
            fit: true,
            padding: 40,
            randomize: false,
            componentSpacing: 100,
            nodeRepulsion: 400000,
            edgeElasticity: 100,
            nestingFactor: 5,
            gravity: 80,
            numIter: 400,
            initialTemp: 200,
            coolingFactor: 0.95,
            minTemp: 1.0
        }
    });

    // Node Click Event
    cy.on("tap", "node", function(evt) {
        const node = evt.target;
        showNodeInspector(node.data());
    });

    // Edge Click Event
    cy.on("tap", "edge", function(evt) {
        const edge = evt.target;
        showEdgeInspector(edge.data());
    });
}

function showNodeInspector(data) {
    document.getElementById("inspector-type-badge").innerText = "ACCOUNT";
    document.getElementById("inspector-type-badge").className = "badge bg-primary";

    let badgeClass = "badge-risk-low";
    if (data.risk_category === "Critical") badgeClass = "badge-risk-critical";
    else if (data.risk_category === "High") badgeClass = "badge-risk-high";
    else if (data.risk_category === "Medium") badgeClass = "badge-risk-medium";

    const content = document.getElementById("inspector-content");
    content.innerHTML = `
        <div class="mb-3">
            <div class="small text-secondary">Account Identifier</div>
            <h5 class="fw-bold text-white mb-0">${data.id}</h5>
        </div>
        <div class="card-dark p-2 mb-3">
            <div class="d-flex justify-content-between align-items-center">
                <span class="small text-secondary">Unified Risk Score</span>
                <span class="${badgeClass}">${data.risk_category}</span>
            </div>
            <div class="fs-4 fw-bold text-white mt-1">${Number(data.risk_score || 0).toFixed(1)} / 100</div>
        </div>
        <div class="small mb-3">
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Out-Degree (Dispersal):</span>
                <span class="fw-bold">${data.out_degree || 0}</span>
            </div>
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">In-Degree (Aggregation):</span>
                <span class="fw-bold">${data.in_degree || 0}</span>
            </div>
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Total Sent:</span>
                <span class="fw-bold">$${Number(data.total_sent || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
            </div>
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Total Received:</span>
                <span class="fw-bold">$${Number(data.total_received || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
            </div>
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Cycle Participant:</span>
                <span class="fw-bold ${data.is_in_cycle ? 'text-warning' : 'text-secondary'}">${data.is_in_cycle ? 'YES' : 'NO'}</span>
            </div>
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Fraud Ring Member:</span>
                <span class="fw-bold ${data.is_in_ring ? 'text-danger' : 'text-secondary'}">${data.is_in_ring ? 'YES' : 'NO'}</span>
            </div>
        </div>
        <a href="/investigation?account_id=${data.id}" class="btn btn-sm btn-outline-primary w-100">
            Open Account Dossier
        </a>
    `;
}

function showEdgeInspector(data) {
    document.getElementById("inspector-type-badge").innerText = "TRANSFER";
    document.getElementById("inspector-type-badge").className = "badge bg-warning text-dark";

    const content = document.getElementById("inspector-content");
    content.innerHTML = `
        <div class="mb-3">
            <div class="small text-secondary">Transaction ID</div>
            <h6 class="fw-bold text-white mb-0">${data.id}</h6>
        </div>
        <div class="card-dark p-2 mb-3">
            <div class="small text-secondary">Transfer Amount</div>
            <div class="fs-4 fw-bold text-white mt-1">$${Number(data.amount || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
            <div class="small text-muted">${data.timestamp} &bull; ${data.transaction_type}</div>
        </div>
        <div class="small mb-3">
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Origin (Sender):</span>
                <a href="/investigation?account_id=${data.source}" class="text-decoration-none fw-bold text-white">${data.source}</a>
            </div>
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Destination (Receiver):</span>
                <a href="/investigation?account_id=${data.target}" class="text-decoration-none fw-bold text-white">${data.target}</a>
            </div>
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Cycle Laundering Hop:</span>
                <span class="fw-bold ${data.is_cycle_edge ? 'text-warning' : 'text-secondary'}">${data.is_cycle_edge ? 'YES' : 'NO'}</span>
            </div>
            <div class="d-flex justify-content-between mb-1">
                <span class="text-secondary">Flagged Anomaly:</span>
                <span class="fw-bold ${data.is_flagged ? 'text-danger' : 'text-success'}">${data.is_flagged ? 'ALERT' : 'NORMAL'}</span>
            </div>
        </div>
    `;
}

function resetGraphView() {
    if (cy) {
        cy.fit(undefined, 30);
    }
}

// Initial Load
document.addEventListener("DOMContentLoaded", () => {
    const urlParams = new URLSearchParams(window.location.search);
    const accParam = urlParams.get("account_id");
    if (accParam) {
        document.getElementById("graph-account-filter").value = accParam;
    }
    loadGraphVisualization();
});
