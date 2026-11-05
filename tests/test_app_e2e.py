"""End-to-end test suite for Flask Web Application, Views, and REST APIs."""

import pytest
from src.app import create_app
from src.database import DatabaseManager


@pytest.fixture
def test_client(tmp_path):
    """Provides test client connected to isolated DB with populated dummy data."""
    db_file = tmp_path / "test_app_e2e.db"
    db = DatabaseManager(db_path=db_file)

    accounts_data = [
        {
            "account_id": "ACC_0001",
            "in_degree": 5,
            "out_degree": 6,
            "total_degree": 11,
            "in_degree_centrality": 0.05,
            "out_degree_centrality": 0.06,
            "pagerank": 0.012,
            "community_id": 1,
            "component_id": 1,
            "total_sent": 25000.0,
            "total_received": 24000.0,
            "net_flow": -1000.0,
            "graph_risk_score": 85.0,
            "risk_category": "Critical",
            "risk_reasons": ["Laundering ring participant"],
            "is_in_cycle": True,
            "is_in_ring": True,
        }
    ]
    cycles_data = [{
        "cycle_id": "CYC_0001",
        "length": 3,
        "accounts": ["ACC_0001", "ACC_0002", "ACC_0003"],
        "transactions": [],
        "total_amount": 75000.0,
        "min_amount": 24000.0,
        "max_amount": 25500.0,
    }]
    rings_data = [{
        "ring_id": "RING_001",
        "account_count": 3,
        "transaction_count": 9,
        "total_amount": 75000.0,
        "risk_score": 95.0,
        "risk_category": "Critical",
        "detected_patterns": ["circular_transfers"],
        "accounts": ["ACC_0001", "ACC_0002", "ACC_0003"],
        "explanation": "3-hop laundering ring",
    }]

    db.save_graph_analysis(accounts_data, cycles_data, rings_data)

    app = create_app(db_manager=db)
    app.config["TESTING"] = True
    return app.test_client(), db


def test_page_views(test_client):
    """Verify all HTML template pages render with 200 OK status."""
    client, _ = test_client

    routes = [
        "/",
        "/transactions",
        "/investigation",
        "/account/ACC_0001",
        "/network",
        "/rings",
        "/cases",
        "/analytics",
        "/monitoring",
    ]
    for r in routes:
        res = client.get(r)
        assert res.status_code == 200, f"Page view '{r}' failed with status {res.status_code}"


def test_dashboard_apis(test_client):
    """Verify overview, charts, and recent activity APIs."""
    client, _ = test_client

    # Overview
    res = client.get("/api/dashboard/overview")
    assert res.status_code == 200
    data = res.get_json()
    assert "total_accounts" in data
    assert "detected_fraud_rings" in data

    # Charts
    res_charts = client.get("/api/dashboard/charts")
    assert res_charts.status_code == 200
    charts_data = res_charts.get_json()
    assert "timeline" in charts_data
    assert "risk_distribution" in charts_data

    # Recent Activity
    res_act = client.get("/api/dashboard/recent-activity")
    assert res_act.status_code == 200
    act_data = res_act.get_json()
    assert "recent_flagged_transactions" in act_data


def test_risk_and_transactions_api(test_client):
    """Verify account risk list and paginated transactions."""
    client, _ = test_client

    res = client.get("/api/risk/accounts")
    assert res.status_code == 200
    assert "accounts" in res.get_json()

    res_acc = client.get("/api/risk/accounts/ACC_0001")
    assert res_acc.status_code == 200
    assert res_acc.get_json()["account"]["account_id"] == "ACC_0001"

    # Non-existent account -> 404
    res_not_found = client.get("/api/risk/accounts/NON_EXISTENT")
    assert res_not_found.status_code == 404

    # Transactions paginated
    res_tx = client.get("/api/risk/transactions?limit=10")
    assert res_tx.status_code == 200
    assert "transactions" in res_tx.get_json()


def test_investigations_api_workflow(test_client):
    """Verify case opening, note logging, and status update via API."""
    client, _ = test_client

    # Open case
    res = client.post("/api/investigations", json={
        "account_id": "ACC_0001",
        "reason": "Suspicious rapid layering"
    })
    assert res.status_code == 201
    case = res.get_json()
    inv_id = case["investigation_id"]

    # Add Note
    res_note = client.post(f"/api/investigations/{inv_id}/notes", json={
        "note_text": "Examined counterparty connections"
    })
    assert res_note.status_code == 201

    # Update Status
    res_status = client.put(f"/api/investigations/{inv_id}", json={
        "status": "Escalated"
    })
    assert res_status.status_code == 200
    assert res_status.get_json()["status"] == "Escalated"

    # Download PDF dossier
    res_pdf = client.get(f"/api/reports/investigation/{inv_id}/pdf")
    assert res_pdf.status_code == 200
    assert res_pdf.mimetype == "application/pdf"
    assert len(res_pdf.data) > 1000


def test_system_health_and_monitoring_api(test_client):
    """Verify system health and runtime statistics endpoints."""
    client, _ = test_client

    res_health = client.get("/api/system/health")
    assert res_health.status_code == 200
    assert res_health.get_json()["database_connected"] is True

    res_stats = client.get("/api/system/statistics")
    assert res_stats.status_code == 200
    assert "overview" in res_stats.get_json()
