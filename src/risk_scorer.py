"""Unified Fraud Risk Scoring Engine for Graph-Based Fraud Intelligence.

Synthesizes multiple detection signals into an explainable composite risk score [0, 100]:
1. Rule-based suspicious indicators (weight: 20%)
2. Isolation Forest anomaly scores (weight: 15%)
3. Random Forest fraud probabilities (weight: 25%)
4. Graph structural centrality metrics (weight: 20%)
5. Network topology: Suspicious cycles & fraud rings (weight: 20%)

Risk Categories:
- 0–29:   Low Risk
- 30–59:  Medium Risk
- 60–79:  High Risk
- 80–100: Critical Risk
"""

from dataclasses import asdict, dataclass
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("fraudgraph.risk")

# Configurable Weights
DEFAULT_WEIGHTS = {
    "rules": 0.20,
    "isolation_forest": 0.15,
    "random_forest": 0.25,
    "graph_centrality": 0.20,
    "network_topology": 0.20,
}

# Configurable Category Bands
RISK_CATEGORIES = {
    "Low": (0.0, 29.99),
    "Medium": (30.0, 59.99),
    "High": (60.0, 79.99),
    "Critical": (80.0, 100.0),
}


def get_risk_category(score: float) -> str:
    """Classify a numeric score [0, 100] into Low, Medium, High, or Critical."""
    s = max(0.0, min(100.0, float(score)))
    for cat, (low, high) in RISK_CATEGORIES.items():
        if low <= s <= high:
            return cat
    return "Critical" if s >= 80.0 else "Low"


@dataclass
class RiskBreakdown:
    """Itemized breakdown of signal contributions to the final risk score."""
    rule_score: float = 0.0
    isolation_forest_score: float = 0.0
    random_forest_score: float = 0.0
    graph_centrality_score: float = 0.0
    network_topology_score: float = 0.0
    final_score: float = 0.0
    risk_category: str = "Low"
    explanations: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d["explanations"] is None:
            d["explanations"] = []
        return d


class UnifiedRiskEngine:
    """Central explainable risk assessment engine for accounts and transactions."""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        # Normalize weights to sum to 1.0
        total_w = sum(self.weights.values())
        if total_w > 0:
            self.weights = {k: v / total_w for k, v in self.weights.items()}

    def evaluate_account(
        self,
        account_id: str,
        account_record: Dict[str, Any],
        related_transactions: pd.DataFrame,
        is_in_cycle: bool = False,
        is_in_ring: bool = False,
        ring_risk_score: float = 0.0,
    ) -> RiskBreakdown:
        """
        Compute explainable unified risk score for an account.
        
        Safely handles missing model outputs without treating missingness as fraud.
        Never uses ground-truth 'is_fraud' labels.
        """
        explanations = []

        # 1. Rule-based contribution (Max rule severity of related transactions or account average)
        rule_score = 0.0
        if not related_transactions.empty and "rule_severity_score" in related_transactions.columns:
            rule_score = float(related_transactions["rule_severity_score"].max())
            if rule_score > 0:
                flagged_rules = []
                if "triggered_rules" in related_transactions.columns:
                    for tr in related_transactions["triggered_rules"].dropna():
                        if isinstance(tr, list):
                            flagged_rules.extend(tr)
                        elif isinstance(tr, str) and tr.startswith("["):
                            import ast
                            try:
                                flagged_rules.extend(ast.literal_eval(tr))
                            except Exception:
                                pass
                unique_rules = list(set(flagged_rules))
                rule_desc = f"Triggered {len(unique_rules)} rule(s): {', '.join(unique_rules[:3])}" if unique_rules else "Triggered transaction rules"
                explanations.append(rule_desc)

        # 2. Isolation Forest contribution (Normalized [0, 1] -> [0, 100])
        iso_score = 0.0
        if not related_transactions.empty and "iso_forest_anomaly_score" in related_transactions.columns:
            max_iso = float(related_transactions["iso_forest_anomaly_score"].max())
            iso_score = round(max(0.0, min(100.0, max_iso * 100.0)), 2)
            if iso_score >= 50.0:
                explanations.append(f"Elevated statistical anomaly score ({iso_score:.1f}%)")

        # 3. Random Forest fraud probability contribution ([0, 1] -> [0, 100])
        rf_score = 0.0
        if not related_transactions.empty and "rf_fraud_probability" in related_transactions.columns:
            max_rf = float(related_transactions["rf_fraud_probability"].max())
            rf_score = round(max(0.0, min(100.0, max_rf * 100.0)), 2)
            if rf_score >= 50.0:
                explanations.append(f"Supervised model flagged suspicious pattern ({rf_score:.1f}% probability)")

        # 4. Graph Centrality contribution (In/out degree hub behavior + PageRank)
        graph_cent_score = 0.0
        in_deg = account_record.get("in_degree", 0)
        out_deg = account_record.get("out_degree", 0)
        pr = account_record.get("pagerank", 0.0)

        cent_factors = 0.0
        if out_deg >= 15:
            cent_factors += 40.0
            explanations.append(f"High-volume dispersal hub (Out-degree: {out_deg})")
        elif in_deg >= 15:
            cent_factors += 35.0
            explanations.append(f"High-volume capital aggregator (In-degree: {in_deg})")

        if pr >= 0.009:
            cent_factors += 35.0
            explanations.append(f"Elevated PageRank network centrality ({pr:.5f})")

        total_vol = account_record.get("total_sent", 0.0) + account_record.get("total_received", 0.0)
        if total_vol > 50000.0:
            cent_factors += 25.0
            explanations.append(f"Substantial transaction capital (${total_vol:,.2f})")

        graph_cent_score = min(100.0, cent_factors)

        # 5. Network Topology contribution (Cycles & Fraud Rings)
        top_score = 0.0
        if is_in_ring:
            top_score = max(top_score, ring_risk_score if ring_risk_score > 0 else 85.0)
            explanations.append("Identified member of coordinated fraud ring")
        elif is_in_cycle:
            top_score = max(top_score, 75.0)
            explanations.append("Active participant in closed circular transfer flow (laundering cycle)")

        # Weighted Sum
        final_score = (
            self.weights["rules"] * rule_score
            + self.weights["isolation_forest"] * iso_score
            + self.weights["random_forest"] * rf_score
            + self.weights["graph_centrality"] * graph_cent_score
            + self.weights["network_topology"] * top_score
        )
        final_score = round(max(0.0, min(100.0, final_score)), 1)
        category = get_risk_category(final_score)

        if not explanations:
            explanations.append("Normal transaction activity within established baselines")

        return RiskBreakdown(
            rule_score=round(rule_score, 1),
            isolation_forest_score=round(iso_score, 1),
            random_forest_score=round(rf_score, 1),
            graph_centrality_score=round(graph_cent_score, 1),
            network_topology_score=round(top_score, 1),
            final_score=final_score,
            risk_category=category,
            explanations=explanations,
        )

    def evaluate_transaction(
        self,
        tx_row: pd.Series,
        sender_risk_score: float = 0.0,
        receiver_risk_score: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Compute transaction composite risk score [0, 100] incorporating counterparty risks.
        """
        rule_score = float(tx_row.get("rule_severity_score", 0.0))
        iso_val = float(tx_row.get("iso_forest_anomaly_score", 0.0))
        rf_val = float(tx_row.get("rf_fraud_probability", 0.0))

        iso_score = iso_val * 100.0
        rf_score = rf_val * 100.0
        counterparty_risk = (sender_risk_score + receiver_risk_score) / 2.0

        # Composite score
        tx_composite = (
            0.30 * rule_score
            + 0.20 * iso_score
            + 0.30 * rf_score
            + 0.20 * counterparty_risk
        )
        tx_composite = round(max(0.0, min(100.0, tx_composite)), 1)
        category = get_risk_category(tx_composite)

        patterns = []
        if rule_score > 0:
            patterns.append(str(tx_row.get("rule_reasons", "Rule alert")))
        if iso_val >= 0.60:
            patterns.append("Statistical anomaly")
        if rf_val >= 0.70:
            patterns.append("ML fraud pattern")
        if counterparty_risk >= 60.0:
            patterns.append("High-risk counterparty link")

        return {
            "transaction_id": tx_row["transaction_id"],
            "transaction_risk_score": tx_composite,
            "risk_category": category,
            "detected_patterns": "; ".join(patterns) if patterns else "Normal",
        }

    def score_and_persist(self, db_manager=None) -> Dict[str, Any]:
        """Compute unified risk scores for all accounts and transactions and persist to SQLite."""
        from src.database import DatabaseManager
        db = db_manager or DatabaseManager()

        with db.get_connection() as conn:
            tx_df = pd.read_sql_query("SELECT * FROM transactions;", conn)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts;")
            accounts = [dict(r) for r in cursor.fetchall()]
            cycles = db.get_cycles()
            rings = db.get_fraud_rings()

        if tx_df.empty or not accounts:
            logger.warning("No transactions or accounts found to score.")
            return {"accounts_scored": 0, "transactions_scored": 0}

        cycle_nodes = set()
        for c in cycles:
            cycle_nodes.update(c.get("accounts", []))

        ring_node_map = {}
        for r in rings:
            for acc in r.get("accounts", []):
                ring_node_map[acc] = r.get("risk_score", 85.0)

        # 1. Score Accounts
        updated_accounts = []
        account_scores_map = {}
        for acc in accounts:
            acc_id = acc["account_id"]
            related_tx = tx_df[(tx_df["sender_account"] == acc_id) | (tx_df["receiver_account"] == acc_id)]
            is_in_cyc = acc_id in cycle_nodes
            is_in_ring = acc_id in ring_node_map
            ring_score = ring_node_map.get(acc_id, 0.0)

            breakdown = self.evaluate_account(
                account_id=acc_id,
                account_record=acc,
                related_transactions=related_tx,
                is_in_cycle=is_in_cyc,
                is_in_ring=is_in_ring,
                ring_risk_score=ring_score,
            )

            acc["graph_risk_score"] = breakdown.final_score
            acc["risk_category"] = breakdown.risk_category
            acc["risk_reasons"] = breakdown.explanations
            updated_accounts.append(acc)
            account_scores_map[acc_id] = breakdown.final_score

        # 2. Score Transactions
        tx_scores = []
        for _, tx_row in tx_df.iterrows():
            s_acc = tx_row["sender_account"]
            r_acc = tx_row["receiver_account"]
            s_risk = account_scores_map.get(s_acc, 20.0)
            r_risk = account_scores_map.get(r_acc, 20.0)

            t_score = self.evaluate_transaction(
                tx_row=tx_row,
                sender_risk_score=s_risk,
                receiver_risk_score=r_risk,
            )
            tx_scores.append(t_score)

        # Persist to SQLite
        db.save_graph_analysis(
            accounts_data=updated_accounts,
            cycles_data=cycles,
            rings_data=rings,
        )
        db.save_transaction_risk_scores(tx_scores)

        logger.info(f"Persisted unified risk scores: {len(updated_accounts)} accounts, {len(tx_scores)} transactions.")
        return {
            "accounts_scored": len(updated_accounts),
            "transactions_scored": len(tx_scores),
        }


if __name__ == "__main__":
    engine = UnifiedRiskEngine()
    res = engine.score_and_persist()
    print("[✓] Unified risk scoring complete:", res)

