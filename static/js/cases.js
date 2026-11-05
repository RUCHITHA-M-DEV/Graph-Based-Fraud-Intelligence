// Case Management Center Manager

async function loadCases() {
    const status = document.getElementById("case-filter-status").value;
    const risk = document.getElementById("case-filter-risk").value;

    const params = new URLSearchParams();
    if (status) params.append("status", status);
    if (risk) params.append("risk_category", risk);
    params.append("limit", "100");

    const tbody = document.getElementById("cases-table-body");
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4 text-muted"><span class="spinner-border spinner-border-sm me-2"></span>Loading case ledger...</td></tr>`;

    try {
        const res = await fetch(`/api/investigations?${params.toString()}`);
        if (!res.ok) throw new Error("Failed to fetch cases");
        const data = await res.json();
        const cases = data.cases || [];

        document.getElementById("cases-count-label").innerText = `${cases.length} Total Cases`;

        if (cases.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4 text-muted">No investigation cases found. Click 'Open New Case' above.</td></tr>`;
            return;
        }

        tbody.innerHTML = cases.map(c => {
            let badgeClass = "badge-risk-low";
            if (c.risk_category === "Critical") badgeClass = "badge-risk-critical";
            else if (c.risk_category === "High") badgeClass = "badge-risk-high";
            else if (c.risk_category === "Medium") badgeClass = "badge-risk-medium";

            let statusBadge = "bg-secondary";
            if (c.status === "Escalated") statusBadge = "bg-danger";
            else if (c.status === "Under Review") statusBadge = "bg-warning text-dark";
            else if (c.status === "Closed") statusBadge = "bg-success";
            else if (c.status === "New") statusBadge = "bg-primary";

            return `
                <tr>
                    <td><span class="badge bg-dark border border-secondary">${c.investigation_id}</span></td>
                    <td><a href="/investigation?account_id=${c.account_id}" class="text-decoration-none fw-bold text-white">${c.account_id}</a></td>
                    <td><span class="fw-bold">${Number(c.risk_score || 0).toFixed(1)}</span></td>
                    <td><span class="${badgeClass}">${c.risk_category}</span></td>
                    <td><span class="badge ${statusBadge}">${c.status}</span></td>
                    <td class="small text-truncate" style="max-width: 250px;" title="${c.reason}">${c.reason}</td>
                    <td class="text-secondary small">${(c.created_at || '').substring(0, 10)}</td>
                    <td>
                        <div class="btn-group btn-group-sm">
                            <a href="/investigation?account_id=${c.account_id}" class="btn btn-outline-primary py-0 px-2 small">Workbench</a>
                            <a href="/api/reports/investigation/${c.investigation_id}/pdf" class="btn btn-outline-danger py-0 px-2 small" title="Download Official PDF Dossier">
                                <i class="bi bi-file-earmark-pdf"></i> PDF
                            </a>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");

    } catch (err) {
        console.error("Error loading cases:", err);
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4 text-danger">Failed to load cases.</td></tr>`;
    }
}

function openNewCaseModal() {
    const modal = new bootstrap.Modal(document.getElementById("newCaseModal"));
    modal.show();
}

async function submitNewCase() {
    const accountId = document.getElementById("modal-case-account").value.trim().toUpperCase();
    const reason = document.getElementById("modal-case-reason").value.trim();

    if (!accountId) {
        alert("Account ID is required.");
        return;
    }

    try {
        const res = await fetch(`/api/investigations`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                account_id: accountId,
                reason: reason || "Manual compliance opening"
            })
        });

        if (res.ok) {
            bootstrap.Modal.getInstance(document.getElementById("newCaseModal")).hide();
            document.getElementById("modal-case-account").value = "";
            document.getElementById("modal-case-reason").value = "";
            loadCases();
        } else {
            const err = await res.json();
            alert(`Error: ${err.message || 'Failed to open case'}`);
        }
    } catch (err) {
        console.error("Error creating case:", err);
    }
}

function exportCasesCSV() {
    window.location.href = `/api/reports/investigations/csv`;
}

document.addEventListener("DOMContentLoaded", loadCases);
