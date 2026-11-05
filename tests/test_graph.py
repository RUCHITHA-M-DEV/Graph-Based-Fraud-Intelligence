"""Unit tests for Phase 3: Graph Analysis & Fraud Ring Detection."""

import json
import tempfile
import numpy as np
import pandas as pd
import pytest

from src.app import create_app
from src.database import DatabaseManager
from src.graph_analyzer import GraphAnalyzer, TransactionGraph


@pytest.fixture
def sample_tx_df():
    """Fixture providing a controlled financial network with normal and ring transfers."""
    return pd.DataFrame([
        # 3-node Fraud Ring: A -> B -> C -> A
        {"transaction_id": "TX_R1", "sender_account": "ACC_A", "receiver_account": "ACC_B",
         "amount": 25000.0, "timestamp": "2026-10-01 10:00:00", "transaction_type": "TRANSFER", "is_fraud": 1},
        {"transaction_id": "TX_R2", "sender_account": "ACC_B", "receiver_account": "ACC_C",
         "amount": 24500.0, "timestamp": "2026-10-01 11:00:00", "transaction_type": "TRANSFER", "is_fraud": 1},
        {"transaction_id": "TX_R3", "sender_account": "ACC_C", "receiver_account": "ACC_A",
         "amount": 24000.0, "timestamp": "2026-10-01 12:00:00", "transaction_type": "TRANSFER", "is_fraud": 1},
        # Normal peripheral transactions
        {"transaction_id": "TX_N1", "sender_account": "ACC_D", "receiver_account": "ACC_E",
         "amount": 150.0, "timestamp": "2026-10-01 13:00:00", "transaction_type": "PAYMENT", "is_fraud": 0},
        {"transaction_id": "TX_N2", "sender_account": "ACC_E", "receiver_account": "ACC_F",
         "amount": 75.0, "timestamp": "2026-10-01 14:00:00", "transaction_type": "TRANSFER", "is_fraud": 0},
        {"transaction_id": "TX_N3", "sender_account": "ACC_F", "receiver_account": "ACC_D",
         "amount": 50.0, "timestamp": "2026-10-01 15:00:00", "transaction_type": "DEBIT", "is_fraud": 0},
    ])


@pytest.fixture
def temp_db(tmp_path):
    """Fixture providing isolated temporary SQLite database."""
    db_file = tmp_path / "test_fraudgraph.db"
    return DatabaseManager(db_path=db_file)


def test_graph_construction_and_node_aggregates(sample_tx_df):
    """Verify directed graph construction, edge count, and node financial flows."""
    tx_graph = TransactionGraph(sample_tx_df)
    G = tx_graph.G

    assert G.number_of_nodes() == 6
    assert G.number_of_edges() == 6

    # Node ACC_A sent 25k, received 24k
    acc_a = G.nodes["ACC_A"]
    assert acc_a["total_sent"] == 25000.0
    assert acc_a["total_received"] == 24000.0
    assert acc_a["out_degree"] == 1
    assert acc_a["in_degree"] == 1
    assert acc_a["total_degree"] == 2


def test_degree_centrality_and_pagerank(sample_tx_df):
    """Verify degree centralities and PageRank computation."""
    tx_graph = TransactionGraph(sample_tx_df)
    analyzer = GraphAnalyzer(tx_graph)

    centralities = analyzer.calculate_centralities()
    pagerank = analyzer.calculate_pagerank()

    assert len(centralities) == 6
    assert len(pagerank) == 6
    for node in tx_graph.G.nodes:
        assert "in_degree_centrality" in centralities[node]
        assert "out_degree_centrality" in centralities[node]
        assert pagerank[node] > 0.0


def test_connected_components_and_communities(sample_tx_df):
    """Verify weakly connected components and community detection."""
    tx_graph = TransactionGraph(sample_tx_df)
    analyzer = GraphAnalyzer(tx_graph)

    wcc = analyzer.calculate_weakly_connected_components()
    communities = analyzer.calculate_communities()

    # The sample has two disjoint 3-cycles: {A, B, C} and {D, E, F}
    assert wcc["ACC_A"] == wcc["ACC_B"] == wcc["ACC_C"]
    assert wcc["ACC_D"] == wcc["ACC_E"] == wcc["ACC_F"]
    assert wcc["ACC_A"] != wcc["ACC_D"]
    assert len(set(wcc.values())) == 2
    assert len(set(communities.values())) >= 2


def test_cycle_detection_and_duplicate_prevention(sample_tx_df):
    """Verify cycle detection, minimum amount filtering, and canonical deduplication."""
    tx_graph = TransactionGraph(sample_tx_df)
    analyzer = GraphAnalyzer(tx_graph)

    # 1. With min_amount=10000, only the fraud ring {A, B, C} should be detected
    high_val_cycles = analyzer.detect_cycles(max_length=4, min_amount=10000.0)
    assert len(high_val_cycles) == 1
    assert set(high_val_cycles[0]["accounts"]) == {"ACC_A", "ACC_B", "ACC_C"}
    assert high_val_cycles[0]["total_amount"] == 73500.0

    # 2. With min_amount=10, both 3-cycles should be detected without duplicates
    all_cycles = analyzer.detect_cycles(max_length=4, min_amount=10.0)
    assert len(all_cycles) == 2
    detected_account_sets = [set(c["accounts"]) for c in all_cycles]
    assert {"ACC_A", "ACC_B", "ACC_C"} in detected_account_sets
    assert {"ACC_D", "ACC_E", "ACC_F"} in detected_account_sets


def test_fraud_ring_detection_and_scoring(sample_tx_df):
    """Verify fraud ring scoring and pattern categorization."""
    tx_graph = TransactionGraph(sample_tx_df)
    analyzer = GraphAnalyzer(tx_graph)

    cycles = analyzer.detect_cycles(max_length=4, min_amount=10000.0)
    rings = analyzer.detect_fraud_rings(cycles=cycles)

    assert len(rings) == 1
    ring = rings[0]
    assert ring["account_count"] == 3
    assert ring["risk_score"] >= 70.0  # High risk due to closed cycle + large capital
    assert ring["risk_category"] == "High"
    assert "circular_money_flow" in ring["detected_patterns"]


def test_graph_risk_scoring_explainability(sample_tx_df):
    """Verify multi-factor account risk scoring produces valid explainable reasons."""
    tx_graph = TransactionGraph(sample_tx_df)
    analyzer = GraphAnalyzer(tx_graph)
    analysis = analyzer.run_full_analysis(min_amount_cycle=10000.0)

    account_scores = analysis["accounts"]
    score_dict = {acc["account_id"]: acc for acc in account_scores}

    # Accounts A, B, C belong to the high-value ring
    for node in ("ACC_A", "ACC_B", "ACC_C"):
        acc = score_dict[node]
        assert acc["graph_risk_score"] >= 55.0
        assert acc["is_in_cycle"] is True
        assert acc["is_in_ring"] is True
        assert len(acc["risk_reasons"]) >= 2

    # Normal accounts D, E, F should have low risk
    for node in ("ACC_D", "ACC_E", "ACC_F"):
        acc = score_dict[node]
        assert acc["risk_category"] == "Low"


def test_empty_transaction_dataset():
    """Verify graceful handling of empty DataFrame."""
    empty_df = pd.DataFrame(columns=[
        "transaction_id", "sender_account", "receiver_account", "amount", "timestamp"
    ])
    tx_graph = TransactionGraph(empty_df)
    analyzer = GraphAnalyzer(tx_graph)
    analysis = analyzer.run_full_analysis()

    assert analysis["metrics"]["total_nodes"] == 0
    assert analysis["metrics"]["total_edges"] == 0
    assert len(analysis["accounts"]) == 0
    assert len(analysis["cycles"]) == 0
    assert len(analysis["fraud_rings"]) == 0


def test_database_persistence(temp_db, sample_tx_df):
    """Verify SQLite persistence and query retrieval."""
    tx_graph = TransactionGraph(sample_tx_df)
    analyzer = GraphAnalyzer(tx_graph)
    analysis = analyzer.run_full_analysis(min_amount_cycle=10000.0)

    temp_db.save_transactions(sample_tx_df)
    temp_db.save_graph_analysis(
        accounts_data=analysis["accounts"],
        cycles_data=analysis["cycles"],
        rings_data=analysis["fraud_rings"],
    )

    overview = temp_db.get_overview()
    assert overview["total_accounts"] == 6
    assert overview["total_transactions"] == 6
    assert overview["detected_cycles"] == 1
    assert overview["detected_fraud_rings"] == 1

    acc = temp_db.get_account("ACC_A")
    assert acc is not None
    assert acc["account_id"] == "ACC_A"
    assert acc["is_in_ring"] == 1

    neighbors = temp_db.get_account_neighbors("ACC_A")
    assert len(neighbors["outgoing_neighbors"]) == 1
    assert neighbors["outgoing_neighbors"][0]["receiver_account"] == "ACC_B"


def test_flask_api_endpoints(temp_db, sample_tx_df, tmp_path):
    """Verify Flask REST endpoints with test client."""
    # Save processed CSV for test app
    test_csv = tmp_path / "test_processed.csv"
    sample_tx_df.to_csv(test_csv, index=False)

    app = create_app(db_manager=temp_db)
    client = app.test_client()

    # 1. Health check
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "healthy"

    # 2. Build graph via POST
    build_res = client.post("/api/graph/build", json={
        "csv_path": str(test_csv),
        "min_amount_cycle": 10000.0,
        "max_cycle_length": 4,
    })
    assert build_res.status_code == 201
    assert "metrics" in build_res.get_json()

    # 3. Overview
    overview_res = client.get("/api/graph/overview")
    assert overview_res.status_code == 200
    assert overview_res.get_json()["total_accounts"] == 6

    # 4. Account profile
    acc_res = client.get("/api/graph/account/ACC_A")
    assert acc_res.status_code == 200
    assert acc_res.get_json()["account_id"] == "ACC_A"

    # 5. Invalid account profile (404)
    invalid_acc_res = client.get("/api/graph/account/NON_EXISTENT_ACC")
    assert invalid_acc_res.status_code == 404

    # 6. Cycles
    cycles_res = client.get("/api/graph/cycles")
    assert cycles_res.status_code == 200
    assert cycles_res.get_json()["count"] == 1

    # 7. Fraud rings
    rings_res = client.get("/api/graph/fraud-rings")
    assert rings_res.status_code == 200
    assert rings_res.get_json()["count"] == 1

    # 8. Risk scores
    risk_res = client.get("/api/graph/risk-scores")
    assert risk_res.status_code == 200
    assert risk_res.get_json()["count"] > 0

    # 9. Cytoscape visualization
    vis_res = client.get("/api/graph/visualization?only_suspicious=true")
    assert vis_res.status_code == 200
    vis_data = vis_res.get_json()
    assert "elements" in vis_data
    assert len(vis_data["elements"]["nodes"]) > 0

