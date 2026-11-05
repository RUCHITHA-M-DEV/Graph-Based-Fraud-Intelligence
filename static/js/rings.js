// Fraud Rings Manager

async function loadFraudRings() {
    const container = document.getElementById("fraud-rings-container");
    container.innerHTML = `<div class="col-12 text-center py-5 text-muted"><span class="spinner-border spinner-border-sm me-2"></span>Loading fraud rings...</div>`;

    try {
        const res = await fetch(`/api/graph/fraud-rings`);
        if (!res.ok) throw new Error("Failed to fetch fraud rings");
        const data = await res.json();
        const rings = data.fraud_rings || [];

        if (rings.length === 0) {
            container.innerHTML = `<div class="col-12 text-center py-5 text-muted">No coordinated fraud rings detected in current transaction network.</div>`;
            return;
        }

        container.innerHTML = rings.map(r => {
            let badgeClass = "badge-risk-critical";
            if (r.risk_category === "High") badgeClass = "badge-risk-high";
            else if (r.risk_category === "Medium") badgeClass = "badge-risk-medium";

            const accounts = r.accounts || [];
            const patterns = r.detected_patterns || [];
            const volumeStr = "$" + Number(r.total_amount || 0).toLocaleString(undefined, {minimumFractionDigits: 2});

            return `
                <div class="col-lg-6">
                    <div class="card-dark p-3 h-100 border-secondary">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <div class="d-flex align-items-center gap-2">
                                <span class="badge bg-danger fs-6">${r.ring_id}</span>
                                <h6 class="fw-bold text-white mb-0">${accounts.length}-Node Laundering Syndicate</h6>
                            </div>
                            <span class="${badgeClass}">${r.risk_category} (${Number(r.risk_score).toFixed(1)})</span>
                        </div>

                        <div class="small text-secondary mb-3">${r.explanation}</div>

                        <div class="card-dark p-2 mb-3 bg-dark">
                            <div class="row g-2 text-center">
                                <div class="col-4">
                                    <div class="text-secondary small">Accounts</div>
                                    <div class="fw-bold fs-6 text-white">${accounts.length}</div>
                                </div>
                                <div class="col-4">
                                    <div class="text-secondary small">Transfers</div>
                                    <div class="fw-bold fs-6 text-white">${r.transaction_count}</div>
                                </div>
                                <div class="col-4">
                                    <div class="text-secondary small">Total Volume</div>
                                    <div class="fw-bold fs-6 text-white">${volumeStr}</div>
                                </div>
                            </div>
                        </div>

                        <div class="mb-3">
                            <div class="small text-secondary mb-1">Participating Accounts:</div>
                            <div class="d-flex flex-wrap gap-1">
                                ${accounts.map(acc => `
                                    <a href="/investigation?account_id=${acc}" class="badge bg-secondary-subtle text-secondary text-decoration-none border border-secondary">${acc}</a>
                                `).join("")}
                            </div>
                        </div>

                        <div class="mb-3">
                            <div class="small text-secondary mb-1">Detected Typologies:</div>
                            <div class="d-flex flex-wrap gap-1">
                                ${patterns.map(pat => `
                                    <span class="badge bg-warning-subtle text-warning border border-warning-subtle small">${pat.replace(/_/g, ' ')}</span>
                                `).join("")}
                            </div>
                        </div>

                        <div class="mt-auto d-flex gap-2">
                            <a href="/network?account_id=${accounts[0]}" class="btn btn-sm btn-outline-primary flex-grow-1">
                                <i class="bi bi-diagram-3 me-1"></i> View Ring Network
                            </a>
                            <button class="btn btn-sm btn-primary" onclick="investigateRing('${accounts[0]}', '${r.ring_id}')">
                                <i class="bi bi-briefcase me-1"></i> Open Case
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join("");

    } catch (err) {
        console.error("Error loading rings:", err);
        container.innerHTML = `<div class="col-12 text-center py-5 text-danger">Failed to load fraud rings. Check backend status.</div>`;
    }
}

async function investigateRing(accountId, ringId) {
    try {
        const res = await fetch(`/api/investigations`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                account_id: accountId,
                reason: `Identified member of coordinated fraud ring ${ringId}`
            })
        });
        if (res.ok) {
            const data = await res.json();
            alert(`Investigation case ${data.investigation_id} opened for fraud ring member ${accountId}!`);
            window.location.href = `/investigation?account_id=${accountId}`;
        }
    } catch (err) {
        console.error("Error creating case:", err);
    }
}

document.addEventListener("DOMContentLoaded", loadFraudRings);
