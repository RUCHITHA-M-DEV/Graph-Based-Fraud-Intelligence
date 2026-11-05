"""Unit tests for Phase 4: Investigation Management & Reporting."""

import pytest

from src.database import DatabaseManager
from src.investigation import InvestigationManager
from src.reporter import ReportGenerator


@pytest.fixture
def test_env(tmp_path):
    """Provides isolated DB, investigation manager, and reporter."""
    db_file = tmp_path / "test_investigation.db"
    db = DatabaseManager(db_path=db_file)

    # Insert a dummy account
    accounts_data = [{
        "account_id": "ACC_SUSPECT",
        "in_degree": 10,
        "out_degree": 12,
        "total_degree": 22,
        "graph_risk_score": 85.0,
        "risk_category": "Critical",
        "risk_reasons": ["Laundering ring participant"],
        "is_in_cycle": True,
        "is_in_ring": True,
    }]
    db.save_graph_analysis(accounts_data=accounts_data, cycles_data=[], rings_data=[])

    inv_mgr = InvestigationManager(db)
    reporter = ReportGenerator(db)
    return db, inv_mgr, reporter


def test_investigation_lifecycle(test_env):
    """Verify case opening, status updates, and note tracking."""
    db, inv_mgr, _ = test_env

    # 1. Open Case
    case = inv_mgr.create_case("ACC_SUSPECT", reason="Multiple sub-threshold smurfing alerts")
    inv_id = case["investigation_id"]

    assert inv_id.startswith("INV_")
    assert case["account_id"] == "ACC_SUSPECT"
    assert case["status"] == "New"
    assert case["risk_score"] == 85.0
    assert case["risk_category"] == "Critical"

    # 2. Add Note
    note = inv_mgr.add_note(inv_id, "Found correlated mule transfers in October", author="Lead Analyst")
    assert note["investigation_id"] == inv_id
    assert note["author"] == "Lead Analyst"

    # 3. Update Status
    updated = inv_mgr.update_case_status(inv_id, "Under Review")
    assert updated["status"] == "Under Review"
    assert len(updated["notes"]) >= 2  # Opening note + manual note + status audit note


def test_invalid_status_rejection(test_env):
    """Verify ValueError is raised on non-compliant case statuses."""
    db, inv_mgr, _ = test_env
    case = inv_mgr.create_case("ACC_SUSPECT")

    with pytest.raises(ValueError):
        inv_mgr.update_case_status(case["investigation_id"], "INVALID_STATUS")


def test_non_existent_account_rejection(test_env):
    """Verify KeyError is raised when opening a case for an unknown account."""
    db, inv_mgr, _ = test_env
    with pytest.raises(KeyError):
        inv_mgr.create_case("ACC_UNKNOWN_999")


def test_pdf_and_csv_report_generation(test_env):
    """Verify ReportLab PDF output and CSV data generation."""
    db, inv_mgr, reporter = test_env

    case = inv_mgr.create_case("ACC_SUSPECT", reason="Regulatory compliance audit")
    inv_mgr.add_note(case["investigation_id"], "Verified with AML threshold logs")

    # Generate PDF
    pdf_bytes = reporter.generate_investigation_pdf(case["investigation_id"])
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")

    # Generate CSV
    csv_str = reporter.export_investigations_csv()
    assert "investigation_id,account_id" in csv_str
    assert case["investigation_id"] in csv_str
