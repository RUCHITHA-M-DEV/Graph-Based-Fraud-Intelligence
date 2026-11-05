"""Unit tests for Phase 4: Unified Risk Scoring Engine."""

import pandas as pd
import pytest

from src.risk_scorer import (
    DEFAULT_WEIGHTS,
    RiskBreakdown,
    UnifiedRiskEngine,
    get_risk_category,
)


def test_risk_category_bands():
    """Verify correct classification into Low, Medium, High, and Critical tiers."""
    assert get_risk_category(15.0) == "Low"
    assert get_risk_category(29.9) == "Low"
    assert get_risk_category(30.0) == "Medium"
    assert get_risk_category(59.9) == "Medium"
    assert get_risk_category(60.0) == "High"
    assert get_risk_category(79.9) == "High"
    assert get_risk_category(80.0) == "Critical"
    assert get_risk_category(100.0) == "Critical"


def test_weight_normalization():
    """Verify weights normalize to 1.0 even if non-standard weights are supplied."""
    custom_weights = {
        "rules": 2.0,
        "isolation_forest": 2.0,
        "random_forest": 2.0,
        "graph_centrality": 2.0,
        "network_topology": 2.0,
    }
    engine = UnifiedRiskEngine(weights=custom_weights)
    assert pytest.approx(sum(engine.weights.values()), 0.001) == 1.0
    assert pytest.approx(engine.weights["rules"], 0.001) == 0.20


def test_account_evaluation_with_ring():
    """Verify account risk increases significantly when part of a fraud ring."""
    engine = UnifiedRiskEngine()
    account_record = {
        "account_id": "ACC_RING_01",
        "in_degree": 16,
        "out_degree": 18,
        "pagerank": 0.012,
        "total_sent": 60000.0,
        "total_received": 58000.0,
    }
    tx_df = pd.DataFrame([
        {"rule_severity_score": 70.0, "iso_forest_anomaly_score": 0.85, "rf_fraud_probability": 0.95}
    ])

    breakdown = engine.evaluate_account(
        account_id="ACC_RING_01",
        account_record=account_record,
        related_transactions=tx_df,
        is_in_cycle=True,
        is_in_ring=True,
        ring_risk_score=95.0,
    )

    assert breakdown.final_score >= 80.0
    assert breakdown.risk_category == "Critical"
    assert len(breakdown.explanations) >= 3


def test_account_evaluation_clean_baseline():
    """Verify low risk score for normal account with no alerts."""
    engine = UnifiedRiskEngine()
    account_record = {
        "account_id": "ACC_NORMAL",
        "in_degree": 2,
        "out_degree": 2,
        "pagerank": 0.003,
        "total_sent": 500.0,
        "total_received": 450.0,
    }
    tx_df = pd.DataFrame([
        {"rule_severity_score": 0.0, "iso_forest_anomaly_score": 0.1, "rf_fraud_probability": 0.05}
    ])

    breakdown = engine.evaluate_account(
        account_id="ACC_NORMAL",
        account_record=account_record,
        related_transactions=tx_df,
        is_in_cycle=False,
        is_in_ring=False,
    )

    assert breakdown.final_score < 30.0
    assert breakdown.risk_category == "Low"


def test_transaction_evaluation():
    """Verify transaction composite scoring incorporating counterparty risks."""
    engine = UnifiedRiskEngine()
    tx_row = pd.Series({
        "transaction_id": "TX_TEST_01",
        "rule_severity_score": 60.0,
        "iso_forest_anomaly_score": 0.75,
        "rf_fraud_probability": 0.80,
    })

    res = engine.evaluate_transaction(tx_row, sender_risk_score=75.0, receiver_risk_score=80.0)

    assert res["transaction_id"] == "TX_TEST_01"
    assert res["transaction_risk_score"] >= 65.0
    assert res["risk_category"] in ("High", "Critical")
    assert "Statistical anomaly" in res["detected_patterns"]
