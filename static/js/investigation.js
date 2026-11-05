// Account Investigation Workbench Manager

let currentAccountId = "";
let currentCaseId = "";

async function searchAccount(targetId) {
    const accId = targetId || document.getElementById("account-search-input").value.trim().toUpperCase();
    if (!accId) return;

    currentAccountId = accId;
    document.getElementById("account-search-input").value = accId;

    try {
        const res = await fetch(`/api/risk/accounts/${accId}`);
        if (!res.ok) {
            alert(`Account '${accId}' not found in the transaction graph.`);
            return;
        }

        const data = await res.json();
        const account = data.account;
        const neighbors = data.neighbors;

        renderAccountDetails(account, neighbors);
        await loadAccountCase(accId);

        document.getElementById("investigation-empty-state").style.display = "none";
        document.getElementById("investigation-content").style.display = "block";

        document.getElementById("btn-export-csv").disabled = false;
        document.getElementById("btn-view-network").classList.remove("disabled");
        document.getElementById("btn-view-network").href = `/network?account_id=${accId}`;

    } catch (err) {
        console.error("Failed to inspect account:", err);
    }
}

function quickInspect(accId) {
    document.getElementById("account-search-input").value = accId;
    searchAccount(accId);
}

function renderAccountDetails(account, neighbors) {
    const score = Number(account.graph_risk_score || 0);
    const category = account.risk_category || "Low";

    document.getElementById("acc-risk-score").innerText = score.toFixed(1);
    const badge = document.getElementById("acc-risk-badge");
    badge.innerText = category;
    badge.className = `badge-risk-${category.toLowerCase()}`;

    const sent = Number(account.total_sent || 0);
    const recv = Number(account.total_received || 0);
    const net = recv - sent;

    document.getElementById("acc-net-flow").innerText = "$" + net.toLocaleString(undefined, {minimumFractionDigits: 2});
    document.getElementById("acc-flow-sub").innerText = `Sent: $${sent.toLocaleString(undefined, {minimumFractionDigits: 2})} • Recv: $${recv.toLocaleString(undefined, {minimumFractionDigits: 2})}`;

    const outD = account.out_degree || 0;
    const inD = account.in_degree || 0;
    document.getElementById("acc-total-degree").innerText = outD + inD;
    document.getElementById("acc-degree-sub").innerText = `Dispersal: ${outD} • Aggregation: ${inD}`;

    const isRing = account.is_in_ring;
    const isCycle = account.is_in_cycle;
    const ringStatus = document.getElementById("acc-ring-status");
    if (isRing) {
        ringStatus.innerText = "FRAUD RING";
        ringStatus.className = "stat-kpi-value text-danger";
    } else if (isCycle) {
        ringStatus.innerText = "CYCLE NODE";
        ringStatus.className = "stat-kpi-value text-warning";
    } else {
        ringStatus.innerText = "NORMAL";
        ringStatus.className = "stat-kpi-value text-success";
    }
    document.getElementById("acc-ring-sub").innerText = `Cycle: ${isCycle ? 'YES' : 'NO'} • Ring: ${isRing ? 'YES' : 'NO'}`;

    // Render Reasons
    const reasonsList = document.getElementById("acc-reasons-list");
    const reasons = account.risk_reasons || [];
    reasonsList.innerHTML = reasons.map(r => `
        <li class="list-group-item bg-transparent text-light border-secondary-subtle px-0 d-flex align-items-center gap-2">
            <i class="bi bi-exclamation-triangle-fill text-warning"></i>
            <span>${r}</span>
        </li>
    `).join("");

    // Render Counterparties
    const tbody = document.getElementById("counterparties-table-body");
    const outNeighbors = neighbors.outgoing_neighbors || [];
    const inNeighbors = neighbors.incoming_neighbors || [];
    const allNeighbors = [];

    outNeighbors.forEach(n => allNeighbors.push({
        account: n.receiver_account,
        type: "Outbound (Sent to)",
        count: n.count,
        volume: n.volume
    }));
    inNeighbors.forEach(n => allNeighbors.push({
        account: n.sender_account,
        type: "Inbound (Received from)",
        count: n.count,
        volume: n.volume
    }));

    document.getElementById("counterparty-count-label").innerText = `${allNeighbors.length} Counterparties`;

    if (allNeighbors.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center py-3 text-muted">No counterparties recorded.</td></tr>`;
        return;
    }

    tbody.innerHTML = allNeighbors.map(n => `
        <tr>
            <td><a href="/investigation?account_id=${n.account}" class="text-decoration-none fw-bold text-white">${n.account}</a></td>
            <td><span class="badge ${n.type.startsWith('Outbound') ? 'bg-primary-subtle text-primary' : 'bg-success-subtle text-success'}">${n.type}</span></td>
            <td>${n.count}</td>
            <td class="fw-bold text-white">$${Number(n.volume).toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
            <td>
                <a href="/investigation?account_id=${n.account}" class="btn btn-xs btn-outline-secondary py-0 px-2 small">Inspect</a>
            </td>
        </tr>
    `).join("");
}

async function loadAccountCase(accId) {
    currentCaseId = "";
    document.getElementById("btn-export-pdf").disabled = true;

    try {
        const res = await fetch(`/api/investigations`);
        if (res.ok) {
            const data = await res.json();
            const cases = data.cases || [];
            const activeCase = cases.find(c => c.account_id === accId);

            if (activeCase) {
                currentCaseId = activeCase.investigation_id;
                document.getElementById("case-status-badge").innerText = `${activeCase.investigation_id}: ${activeCase.status.toUpperCase()}`;
                document.getElementById("case-status-badge").className = "badge bg-primary";
                document.getElementById("case-status-select").value = activeCase.status;
                document.getElementById("btn-export-pdf").disabled = false;

                // Load case details with notes
                const caseRes = await fetch(`/api/investigations/${activeCase.investigation_id}`);
                if (caseRes.ok) {
                    const caseData = await caseRes.json();
                    renderCaseNotes(caseData.notes || []);
                }
            } else {
                document.getElementById("case-status-badge").innerText = "NO ACTIVE CASE";
                document.getElementById("case-status-badge").className = "badge bg-secondary";
                document.getElementById("case-notes-container").innerHTML = `<div class="text-muted small text-center py-4">No active case for this account. Click 'Open Case' below.</div>`;
            }
        }
    } catch (err) {
        console.error("Failed to load case data:", err);
    }
}

function renderCaseNotes(notes) {
    const container = document.getElementById("case-notes-container");
    if (!notes || notes.length === 0) {
        container.innerHTML = `<div class="text-muted small text-center py-4">No notes logged yet.</div>`;
        return;
    }

    container.innerHTML = notes.map(n => `
        <div class="card-dark p-2 mb-2 border-secondary-subtle">
            <div class="d-flex justify-content-between small text-muted mb-1">
                <span class="fw-bold text-secondary">${n.author || 'Analyst'}</span>
                <span>${(n.created_at || '').substring(0, 16)}</span>
            </div>
            <div class="small text-light">${n.note_text}</div>
        </div>
    `).join("");
}

async function openNewCaseForAccount() {
    if (!currentAccountId) return;
    try {
        const res = await fetch(`/api/investigations`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                account_id: currentAccountId,
                reason: `Manual investigation initiated from workbench`
            })
        });

        if (res.ok) {
            const newCase = await res.json();
            alert(`Investigation case ${newCase.investigation_id} opened!`);
            await loadAccountCase(currentAccountId);
        } else {
            alert("Failed to open case.");
        }
    } catch (err) {
        console.error("Error creating case:", err);
    }
}

async function saveNoteAndStatus() {
    if (!currentCaseId) {
        alert("Please open a case first before adding notes.");
        return;
    }

    const noteText = document.getElementById("note-input").value.trim();
    const newStatus = document.getElementById("case-status-select").value;

    try {
        // 1. Update status
        await fetch(`/api/investigations/${currentCaseId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: newStatus })
        });

        // 2. Add note if provided
        if (noteText) {
            await fetch(`/api/investigations/${currentCaseId}/notes`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ note_text: noteText })
            });
            document.getElementById("note-input").value = "";
        }

        alert("Investigation updated successfully.");
        await loadAccountCase(currentAccountId);

    } catch (err) {
        console.error("Failed to update case:", err);
    }
}

function exportAccountCSV() {
    if (!currentAccountId) return;
    window.location.href = `/api/reports/account/${currentAccountId}/csv`;
}

function exportAccountPDF() {
    if (!currentCaseId) {
        alert("A case must be opened for this account before exporting a PDF dossier.");
        return;
    }
    window.location.href = `/api/reports/investigation/${currentCaseId}/pdf`;
}

// Initial Load
document.addEventListener("DOMContentLoaded", () => {
    const urlParams = new URLSearchParams(window.location.search);
    const accParam = urlParams.get("account_id");
    if (accParam) {
        searchAccount(accParam);
    }
});
