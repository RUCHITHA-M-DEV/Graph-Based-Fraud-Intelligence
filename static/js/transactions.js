// Transaction Intelligence Explorer Manager

let currentPage = 0;
const pageSize = 50;
let totalRecords = 0;
let currentTransactions = [];

async function loadTransactions() {
    const search = document.getElementById("filter-search").value.trim();
    const category = document.getElementById("filter-category").value;
    const minAmount = document.getElementById("filter-min-amount").value;
    const maxAmount = document.getElementById("filter-max-amount").value;
    const suspicious = document.getElementById("filter-suspicious").value;
    const sortBy = document.getElementById("sort-by").value;

    const params = new URLSearchParams();
    if (search) params.append("search", search);
    if (category) params.append("risk_category", category);
    if (minAmount) params.append("min_amount", minAmount);
    if (maxAmount) params.append("max_amount", maxAmount);
    if (suspicious) params.append("is_suspicious", suspicious);
    params.append("sort_by", sortBy);
    params.append("limit", pageSize);
    params.append("offset", currentPage * pageSize);

    const tbody = document.getElementById("transactions-table-body");
    tbody.innerHTML = `<tr><td colspan="10" class="text-center py-4 text-muted"><span class="spinner-border spinner-border-sm me-2"></span>Loading transactions...</td></tr>`;

    try {
        const res = await fetch(`/api/risk/transactions?${params.toString()}`);
        if (!res.ok) throw new Error("API request failed");
        const data = await res.json();

        totalRecords = data.total_records || 0;
        currentTransactions = data.transactions || [];
        renderTable(currentTransactions);
        updatePagination();
    } catch (err) {
        console.error("Failed to load transactions:", err);
        tbody.innerHTML = `<tr><td colspan="10" class="text-center py-4 text-danger">Failed to load transactions. Check backend connectivity.</td></tr>`;
    }
}

function renderTable(txs) {
    const tbody = document.getElementById("transactions-table-body");
    if (!txs || txs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="text-center py-4 text-muted">No transactions matched your filters.</td></tr>`;
        return;
    }

    tbody.innerHTML = txs.map((t, idx) => {
        let badgeClass = "badge-risk-low";
        if (t.risk_category === "Critical") badgeClass = "badge-risk-critical";
        else if (t.risk_category === "High") badgeClass = "badge-risk-high";
        else if (t.risk_category === "Medium") badgeClass = "badge-risk-medium";

        const amtStr = "$" + Number(t.amount).toLocaleString(undefined, {minimumFractionDigits: 2});
        const riskScore = Number(t.transaction_risk_score || 0).toFixed(1);
        const patterns = t.detected_patterns || (t.rule_flagged ? "Rule Flag" : "Normal");

        return `
            <tr>
                <td><span class="badge bg-dark border border-secondary">${t.transaction_id}</span></td>
                <td><a href="/investigation?account_id=${t.sender_account}" class="text-decoration-none text-white fw-bold">${t.sender_account}</a></td>
                <td><a href="/investigation?account_id=${t.receiver_account}" class="text-decoration-none text-white fw-bold">${t.receiver_account}</a></td>
                <td class="fw-bold text-white">${amtStr}</td>
                <td class="text-secondary small">${t.timestamp}</td>
                <td><span class="badge bg-secondary-subtle text-secondary">${t.transaction_type}</span></td>
                <td><span class="fw-bold">${riskScore}</span></td>
                <td><span class="${badgeClass}">${t.risk_category}</span></td>
                <td class="small text-truncate" style="max-width: 220px;" title="${patterns}">${patterns}</td>
                <td>
                    <button class="btn btn-xs btn-outline-primary py-0 px-2 small" onclick="openTxModal(${idx})">Inspect</button>
                </td>
            </tr>
        `;
    }).join("");
}

function updatePagination() {
    const start = totalRecords === 0 ? 0 : currentPage * pageSize + 1;
    const end = Math.min((currentPage + 1) * pageSize, totalRecords);
    document.getElementById("record-count-label").innerText = `${totalRecords.toLocaleString()} Total Records`;
    document.getElementById("pagination-info").innerText = `Showing ${start.toLocaleString()} - ${end.toLocaleString()} of ${totalRecords.toLocaleString()}`;

    document.getElementById("btn-prev-page").disabled = currentPage === 0;
    document.getElementById("btn-next-page").disabled = end >= totalRecords;
}

function applyFilters() {
    currentPage = 0;
    loadTransactions();
}

function prevPage() {
    if (currentPage > 0) {
        currentPage--;
        loadTransactions();
    }
}

function nextPage() {
    if ((currentPage + 1) * pageSize < totalRecords) {
        currentPage++;
        loadTransactions();
    }
}

function openTxModal(idx) {
    const tx = currentTransactions[idx];
    if (!tx) return;

    document.getElementById("txModalTitle").innerText = `Transaction ${tx.transaction_id}`;
    document.getElementById("modal-investigate-btn").href = `/investigation?account_id=${tx.sender_account}`;

    let badgeClass = "badge-risk-low";
    if (tx.risk_category === "Critical") badgeClass = "badge-risk-critical";
    else if (tx.risk_category === "High") badgeClass = "badge-risk-high";
    else if (tx.risk_category === "Medium") badgeClass = "badge-risk-medium";

    const modalBody = document.getElementById("txModalBody");
    modalBody.innerHTML = `
        <div class="row g-3">
            <div class="col-md-6">
                <div class="card-dark p-3">
                    <h6 class="text-secondary small text-uppercase">Transfer Flow</h6>
                    <div class="d-flex align-items-center justify-content-between my-2">
                        <div>
                            <div class="small text-secondary">Origin Account</div>
                            <div class="fw-bold fs-6">${tx.sender_account}</div>
                        </div>
                        <i class="bi bi-arrow-right text-primary fs-4"></i>
                        <div>
                            <div class="small text-secondary">Destination Account</div>
                            <div class="fw-bold fs-6">${tx.receiver_account}</div>
                        </div>
                    </div>
                    <div class="mt-3">
                        <div class="small text-secondary">Amount</div>
                        <div class="fs-4 fw-bold text-white">$${Number(tx.amount).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
                        <div class="small text-muted">${tx.timestamp} &bull; ${tx.transaction_type}</div>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card-dark p-3">
                    <h6 class="text-secondary small text-uppercase">Risk Assessment</h6>
                    <div class="d-flex align-items-center gap-3 my-2">
                        <div class="fs-3 fw-bold text-white">${Number(tx.transaction_risk_score || 0).toFixed(1)} <span class="fs-6 text-muted">/ 100</span></div>
                        <span class="${badgeClass}">${tx.risk_category}</span>
                    </div>
                    <hr class="border-secondary my-2">
                    <div class="small">
                        <div class="mb-1"><b>Rule Engine Alert:</b> ${tx.rule_flagged ? '<span class="text-warning">TRIGGERED</span>' : '<span class="text-success">PASS</span>'}</div>
                        <div class="mb-1"><b>Isolation Forest Anomaly Score:</b> ${(Number(tx.iso_forest_anomaly_score || 0) * 100).toFixed(1)}%</div>
                        <div class="mb-1"><b>Random Forest Fraud Probability:</b> ${(Number(tx.rf_fraud_probability || 0) * 100).toFixed(1)}%</div>
                    </div>
                </div>
            </div>
            <div class="col-12">
                <div class="card-dark p-3">
                    <h6 class="text-secondary small text-uppercase">Detected Suspicious Indicators</h6>
                    <p class="mb-0 text-light">${tx.detected_patterns || "Normal transaction characteristics."}</p>
                </div>
            </div>
        </div>
    `;

    const modal = new bootstrap.Modal(document.getElementById("txDetailModal"));
    modal.show();
}

function exportFilteredCSV() {
    window.location.href = `/api/reports/investigations/csv`;
}

// Initial Load
document.addEventListener("DOMContentLoaded", () => {
    // Check URL parameters (e.g. ?is_suspicious=true)
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has("is_suspicious")) {
        document.getElementById("filter-suspicious").value = urlParams.get("is_suspicious");
    }
    loadTransactions();
});
