"""Financial Transaction Graph Analysis and Fraud Ring Detection Engine.

Provides:
1. TransactionGraph: Directed multigraph representation of banking accounts and transfers.
2. Centrality & Community Detection: Degree centrality, PageRank, WCC, and Louvain communities.
3. Bounded Cycle Detection: Detects circular money transfers (A -> B -> C -> A) with canonical deduplication.
4. Fraud Ring Detection: Synthesizes cycles and tight transaction topologies into scored fraud rings.
5. Graph-Based Risk Scoring: Multi-factor explainable account risk scoring [0, 100].
6. Cytoscape.js Formatter: Prepares filtered, paginated JSON graph visualizer data.
"""

from collections import defaultdict
from datetime import datetime, timedelta
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import numpy as np
import pandas as pd

from src.config import (
    CYCLE_MIN_AMOUNT,
    DEFAULT_GRAPH_EDGE_LIMIT,
    DEFAULT_MAX_CYCLE_LENGTH,
    PAGERANK_ALPHA,
    PAGERANK_MAX_ITER,
    RISK_BANDS,
)

logger = logging.getLogger("fraudgraph.graph")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class TransactionGraph:
    """Constructs and manages directed financial transaction graphs in NetworkX."""

    def __init__(self, df: pd.DataFrame):
        self.raw_df = df.copy()
        self.G = nx.DiGraph()
        self.multi_edges: List[Dict[str, Any]] = []
        self._build_graph()

    def _build_graph(self) -> None:
        """
        Build directed transaction graph from DataFrame.
        
        Nodes = Bank Accounts
        Directed Edges = Financial Transactions (sender -> receiver)
        """
        for _, row in self.raw_df.iterrows():
            sender = str(row["sender_account"])
            receiver = str(row["receiver_account"])
            amount = float(row["amount"])
            tx_id = str(row["transaction_id"])
            timestamp = str(row["timestamp"])
            tx_type = str(row.get("transaction_type", "TRANSFER"))
            is_fraud = int(row.get("is_fraud", 0))
            is_flagged = bool(
                row.get("rule_flagged", 0)
                or row.get("iso_forest_pred", 0)
                or row.get("rf_fraud_pred", 0)
            )

            # Initialize nodes if not present
            for node in (sender, receiver):
                if not self.G.has_node(node):
                    self.G.add_node(
                        node,
                        account_id=node,
                        total_sent=0.0,
                        total_received=0.0,
                        tx_count_out=0,
                        tx_count_in=0,
                    )

            # Update node aggregates
            self.G.nodes[sender]["total_sent"] += amount
            self.G.nodes[sender]["tx_count_out"] += 1
            self.G.nodes[receiver]["total_received"] += amount
            self.G.nodes[receiver]["tx_count_in"] += 1

            # Edge record for multigraph support
            edge_data = {
                "transaction_id": tx_id,
                "source": sender,
                "target": receiver,
                "amount": amount,
                "timestamp": timestamp,
                "transaction_type": tx_type,
                "is_fraud": is_fraud,
                "is_flagged": is_flagged,
            }
            self.multi_edges.append(edge_data)

            # Update collapsed DiGraph edge
            if self.G.has_edge(sender, receiver):
                self.G[sender][receiver]["weight"] += 1
                self.G[sender][receiver]["total_amount"] += amount
                self.G[sender][receiver]["transactions"].append(edge_data)
            else:
                self.G.add_edge(
                    sender,
                    receiver,
                    weight=1,
                    total_amount=amount,
                    transactions=[edge_data],
                )

        # Compute derived node metrics
        for node in self.G.nodes:
            sent = self.G.nodes[node]["total_sent"]
            received = self.G.nodes[node]["total_received"]
            out_cnt = self.G.nodes[node]["tx_count_out"]
            in_cnt = self.G.nodes[node]["tx_count_in"]

            self.G.nodes[node]["net_flow"] = round(received - sent, 2)
            self.G.nodes[node]["total_sent"] = round(sent, 2)
            self.G.nodes[node]["total_received"] = round(received, 2)
            self.G.nodes[node]["avg_tx_sent"] = round(sent / max(1, out_cnt), 2)
            self.G.nodes[node]["avg_tx_received"] = round(received / max(1, in_cnt), 2)
            self.G.nodes[node]["in_degree"] = self.G.in_degree(node)
            self.G.nodes[node]["out_degree"] = self.G.out_degree(node)
            self.G.nodes[node]["total_degree"] = self.G.in_degree(node) + self.G.out_degree(node)

        logger.info(
            f"Graph constructed: {self.G.number_of_nodes()} accounts, "
            f"{len(self.multi_edges)} transaction edges."
        )


class GraphAnalyzer:
    """Implements graph topology algorithms, cycle finding, and fraud ring detection."""

    def __init__(self, tx_graph: TransactionGraph):
        self.tx_graph = tx_graph
        self.G = tx_graph.G
        self.multi_edges = tx_graph.multi_edges

    # ---------------------------------------------------------------------
    # A. Degree Centrality & PageRank
    # ---------------------------------------------------------------------

    def calculate_centralities(self) -> Dict[str, Dict[str, float]]:
        """
        Calculate in-degree, out-degree, and total degree centrality.
        
        In-Degree: Accounts that receive funds from many counterparties (Potential money aggregation/collector).
        Out-Degree: Accounts that disperse funds to many counterparties (Potential smurfing/mule distributor).
        Total Degree: Overall connectedness of the account in the transaction network.
        """
        in_deg_cent = nx.in_degree_centrality(self.G)
        out_deg_cent = nx.out_degree_centrality(self.G)
        total_deg_cent = nx.degree_centrality(self.G)

        centralities = {}
        for node in self.G.nodes:
            centralities[node] = {
                "in_degree_centrality": round(float(in_deg_cent.get(node, 0.0)), 4),
                "out_degree_centrality": round(float(out_deg_cent.get(node, 0.0)), 4),
                "total_degree_centrality": round(float(total_deg_cent.get(node, 0.0)), 4),
            }
        return centralities

    def calculate_pagerank(self, alpha: float = PAGERANK_ALPHA) -> Dict[str, float]:
        """
        Calculate PageRank scores to uncover structurally central accounts.
        
        Accounts receiving transfers from other influential or high-volume accounts
        receive higher PageRank scores.
        """
        if self.G.number_of_nodes() == 0:
            return {}
        try:
            pr = nx.pagerank(self.G, alpha=alpha, max_iter=PAGERANK_MAX_ITER, weight="weight")
            return {node: round(float(score), 6) for node, score in pr.items()}
        except Exception as e:
            logger.warning(f"PageRank fallback due to: {e}")
            n = max(1, self.G.number_of_nodes())
            return {node: round(1.0 / n, 6) for node in self.G.nodes}

    # ---------------------------------------------------------------------
    # B. Connected Components & Community Detection
    # ---------------------------------------------------------------------

    def calculate_weakly_connected_components(self) -> Dict[str, int]:
        """
        Identify disjoint subgraphs of interacting accounts using Weakly Connected Components (WCC).
        
        Why WCC instead of Strongly Connected Components (SCC)?
        Financial money flows are predominantly directional (A -> B -> C). Strongly connected
        components require every node to reach every other node, which ignores entire trees,
        star topologies, and fan-out laundering chains. WCC reveals all accounts with any
        transitory relationship within the same connected cluster.
        """
        wcc_mapping = {}
        components = sorted(nx.weakly_connected_components(self.G), key=len, reverse=True)
        for comp_id, comp_nodes in enumerate(components, start=1):
            for node in comp_nodes:
                wcc_mapping[node] = comp_id
        return wcc_mapping

    def calculate_communities(self) -> Dict[str, int]:
        """
        Group closely interacting accounts using the Louvain community detection algorithm.
        
        Constructs an undirected projection weighted by transaction frequency to find
        tightly coupled account clusters.
        """
        if self.G.number_of_nodes() == 0:
            return {}

        G_undir = nx.Graph()
        for u, v, data in self.G.edges(data=True):
            w = data.get("weight", 1)
            if G_undir.has_edge(u, v):
                G_undir[u][v]["weight"] += w
            else:
                G_undir.add_edge(u, v, weight=w)

        community_mapping = {}
        try:
            communities = list(nx.community.louvain_communities(G_undir, weight="weight", seed=42))
            for comm_id, members in enumerate(communities, start=1):
                for node in members:
                    community_mapping[node] = comm_id
        except Exception as e:
            logger.warning(f"Community detection fallback: {e}")
            for idx, node in enumerate(self.G.nodes, start=1):
                community_mapping[node] = idx

        return community_mapping

    # ---------------------------------------------------------------------
    # C. Bounded Cycle Detection
    # ---------------------------------------------------------------------

    def detect_cycles(
        self,
        max_length: int = DEFAULT_MAX_CYCLE_LENGTH,
        min_amount: float = CYCLE_MIN_AMOUNT,
        time_window_hours: Optional[float] = None,
        max_cycles: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Detect circular money flows (e.g. A -> B -> C -> A) up to max_length hops.

        Algorithm Features:
        - Bounded DFS search preventing unbounded exponential cycle explosions.
        - Canonical deduplication: A cycle is explored only when its starting node is the
          lexicographical minimum, guaranteeing each elementary cycle is recorded exactly once.
        - Minimum transaction amount filtering to isolate significant capital flows.
        - Extracts exact transaction IDs and amounts powering the circular path.
        """
        t0 = time.time()
        # Filter sub-graph of edges meeting minimum amount
        eligible_edges = [
            (e["source"], e["target"])
            for e in self.multi_edges
            if e["amount"] >= min_amount and e["source"] != e["target"]
        ]

        H = nx.DiGraph()
        for u, v in eligible_edges:
            H.add_edge(u, v)

        nodes = sorted(list(H.nodes()))
        node_order = {node: i for i, node in enumerate(nodes)}

        raw_cycles: List[List[str]] = []
        for start_node in nodes:
            start_idx = node_order[start_node]
            # Stack stores: (current_node, current_path, visited_nodes)
            stack = [(start_node, [start_node], {start_node})]

            while stack:
                curr, path, visited = stack.pop()
                curr_depth = len(path)

                for neighbor in H.successors(curr):
                    if neighbor == start_node and curr_depth >= 2:
                        raw_cycles.append(list(path))
                        if len(raw_cycles) >= max_cycles:
                            break
                    elif neighbor not in visited and curr_depth < max_length:
                        # Enforce that all intermediate nodes have higher index than start_node
                        if node_order.get(neighbor, -1) > start_idx:
                            stack.append((neighbor, path + [neighbor], visited | {neighbor}))

                if len(raw_cycles) >= max_cycles:
                    break
            if len(raw_cycles) >= max_cycles:
                break

        # Enrich detected cycles with transaction details
        detected_cycles = []
        for idx, cycle_nodes in enumerate(raw_cycles, start=1):
            cycle_txs = []
            cycle_amounts = []
            cycle_timestamps = []

            for i in range(len(cycle_nodes)):
                u = cycle_nodes[i]
                v = cycle_nodes[(i + 1) % len(cycle_nodes)]
                # Find matching transactions for hop u -> v
                matching_txs = [
                    e for e in self.multi_edges
                    if e["source"] == u and e["target"] == v and e["amount"] >= min_amount
                ]
                if matching_txs:
                    # Pick transaction with highest amount or most relevant
                    best_tx = max(matching_txs, key=lambda x: x["amount"])
                    cycle_txs.append(best_tx)
                    cycle_amounts.append(best_tx["amount"])
                    try:
                        cycle_timestamps.append(datetime.strptime(best_tx["timestamp"], "%Y-%m-%d %H:%M:%S"))
                    except Exception:
                        pass

            # Optional time window constraint check
            if time_window_hours and len(cycle_timestamps) >= 2:
                time_span = (max(cycle_timestamps) - min(cycle_timestamps)).total_seconds() / 3600.0
                if time_span > time_window_hours:
                    continue

            total_amt = round(sum(cycle_amounts), 2)
            min_amt = round(min(cycle_amounts), 2) if cycle_amounts else 0.0
            max_amt = round(max(cycle_amounts), 2) if cycle_amounts else 0.0

            detected_cycles.append({
                "cycle_id": f"CYC_{idx:04d}",
                "length": len(cycle_nodes),
                "accounts": cycle_nodes,
                "transactions": cycle_txs,
                "total_amount": total_amt,
                "min_amount": min_amt,
                "max_amount": max_amt,
            })

        logger.info(
            f"Cycle detection completed in {time.time() - t0:.3f}s: "
            f"{len(detected_cycles)} cycles identified (min_amount=${min_amount:,.2f})."
        )
        return detected_cycles

    # ---------------------------------------------------------------------
    # D. Fraud Ring Detection
    # ---------------------------------------------------------------------

    def detect_fraud_rings(
        self,
        cycles: List[Dict[str, Any]],
        min_ring_risk: float = 30.0,
    ) -> List[Dict[str, Any]]:
        """
        Identify potential fraud rings by synthesizing circular money flows and tight clusters.
        
        Ring Risk Scoring Formula:
        - Presence of verified closed cycle: +35 pts
        - Short cycle length (3-4 hops indicating rapid layering): +15 pts
        - High transaction volume (total capital > $25,000): +20 pts
        - High transaction velocity (burst spacing): +15 pts
        - Direct involvement of flagged transactions from Phase 2: +15 pts
        """
        rings = []
        ring_idx = 1
        seen_account_groups: Set[Tuple[str, ...]] = set()

        for cyc in cycles:
            accounts = sorted(cyc["accounts"])
            acc_tuple = tuple(accounts)
            if acc_tuple in seen_account_groups:
                continue
            seen_account_groups.add(acc_tuple)

            patterns = ["circular_money_flow"]
            reasons = [f"{len(accounts)}-hop closed money transfer cycle detected"]
            score = 35.0

            # 1. Hop length factor
            if len(accounts) in (3, 4):
                patterns.append("rapid_layering_structure")
                reasons.append("Tight 3-4 hop laundering structure")
                score += 15.0

            # 2. Total amount transferred in cycle
            if cyc["total_amount"] >= 50000.0:
                patterns.append("high_capital_flow")
                reasons.append(f"Substantial transaction capital (${cyc['total_amount']:,.2f})")
                score += 20.0
            elif cyc["total_amount"] >= 20000.0:
                patterns.append("elevated_capital_flow")
                reasons.append(f"Elevated capital volume (${cyc['total_amount']:,.2f})")
                score += 10.0

            # 3. Inter-transaction timing velocity
            txs = cyc.get("transactions", [])
            timestamps = []
            for t in txs:
                try:
                    timestamps.append(datetime.strptime(t["timestamp"], "%Y-%m-%d %H:%M:%S"))
                except Exception:
                    pass

            if len(timestamps) >= 2:
                timestamps.sort()
                hours_span = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0
                if hours_span <= 24.0:
                    patterns.append("high_velocity_cycle")
                    reasons.append(f"Fast execution: completed within {hours_span:.1f} hours")
                    score += 15.0

            # 4. Phase 2 trigger correlation
            flagged_in_ring = any(t.get("is_flagged", False) for t in txs)
            if flagged_in_ring:
                patterns.append("ml_rule_anomaly_correlation")
                reasons.append("Contains transactions flagged by Phase 2 rules/ML")
                score += 15.0

            final_score = min(100.0, round(score, 1))

            category = "Low"
            for cat, (low, high) in RISK_BANDS.items():
                if low <= final_score <= high:
                    category = cat.capitalize()
                    break

            if final_score >= min_ring_risk:
                rings.append({
                    "ring_id": f"RING_{ring_idx:03d}",
                    "account_count": len(accounts),
                    "transaction_count": len(txs),
                    "total_amount": cyc["total_amount"],
                    "risk_score": final_score,
                    "risk_category": category,
                    "detected_patterns": patterns,
                    "accounts": cyc["accounts"],
                    "explanation": "; ".join(reasons),
                })
                ring_idx += 1

        logger.info(f"Identified {len(rings)} potential fraud rings.")
        return rings

    # ---------------------------------------------------------------------
    # E. Graph-Based Account Risk Scoring
    # ---------------------------------------------------------------------

    def calculate_account_risk_scores(
        self,
        cycles: List[Dict[str, Any]],
        rings: List[Dict[str, Any]],
        centralities: Dict[str, Dict[str, float]],
        pagerank: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """
        Synthesize graph topological features into an explainable [0, 100] account risk score.
        
        Scoring Matrix:
        - Cycle Involvement: Account is an active node in a circular transfer (+30 pts)
        - Fraud Ring Membership: Account belongs to an identified fraud ring (+25 pts)
        - Hub Centrality: High out-degree/in-degree (top 10 percentile) (+20 pts)
        - PageRank Anomaly: In the top 5 percentile of network influence (+15 pts)
        - High Velocity/Outlier Flow: Net flow or high volume sent (+10 pts)
        """
        # Map node to cycles and rings
        cycle_nodes: Set[str] = set()
        for c in cycles:
            cycle_nodes.update(c["accounts"])

        ring_nodes: Set[str] = set()
        for r in rings:
            ring_nodes.update(r["accounts"])

        # Percentile thresholds for degrees and PageRank
        out_degrees = [self.G.out_degree(n) for n in self.G.nodes] or [0]
        in_degrees = [self.G.in_degree(n) for n in self.G.nodes] or [0]
        pr_values = list(pagerank.values()) or [0.0]

        high_out_deg = float(np.percentile(out_degrees, 90)) if out_degrees else 5
        high_in_deg = float(np.percentile(in_degrees, 90)) if in_degrees else 5
        high_pr = float(np.percentile(pr_values, 95)) if pr_values else 0.01

        account_scores = []
        for node in self.G.nodes:
            node_data = self.G.nodes[node]
            score = 0.0
            reasons = []

            is_in_cycle = node in cycle_nodes
            is_in_ring = node in ring_nodes

            # 1. Cycle involvement
            if is_in_cycle:
                score += 30.0
                reasons.append("Participant in circular transaction laundering cycle")

            # 2. Fraud ring membership
            if is_in_ring:
                score += 25.0
                reasons.append("Identified member of a coordinated fraud ring")

            # 3. Hub / High Degree behavior
            out_d = node_data.get("out_degree", 0)
            in_d = node_data.get("in_degree", 0)
            if out_d >= high_out_deg and out_d > 10:
                score += 20.0
                reasons.append(f"High-frequency dispersal hub (Out-degree: {out_d})")
            elif in_d >= high_in_deg and in_d > 10:
                score += 15.0
                reasons.append(f"High-frequency capital aggregator (In-degree: {in_d})")

            # 4. PageRank structural importance
            pr_score = pagerank.get(node, 0.0)
            if pr_score >= high_pr and pr_score > 0.008:
                score += 15.0
                reasons.append(f"Elevated PageRank structural influence ({pr_score:.5f})")

            # 5. Imbalanced capital flow
            total_sent = node_data.get("total_sent", 0.0)
            total_recv = node_data.get("total_received", 0.0)
            if total_sent > 50000.0 or total_recv > 50000.0:
                score += 10.0
                reasons.append(f"High cumulative transaction volume (${max(total_sent, total_recv):,.2f})")

            final_score = min(100.0, round(score, 1))

            category = "Low"
            for cat, (low, high) in RISK_BANDS.items():
                if low <= final_score <= high:
                    category = cat.capitalize()
                    break

            cents = centralities.get(node, {})
            account_scores.append({
                "account_id": node,
                "in_degree": in_d,
                "out_degree": out_d,
                "total_degree": in_d + out_d,
                "in_degree_centrality": cents.get("in_degree_centrality", 0.0),
                "out_degree_centrality": cents.get("out_degree_centrality", 0.0),
                "pagerank": pr_score,
                "total_sent": total_sent,
                "total_received": total_recv,
                "net_flow": node_data.get("net_flow", 0.0),
                "graph_risk_score": final_score,
                "risk_category": category,
                "risk_reasons": reasons if reasons else ["Normal baseline transaction pattern"],
                "is_in_cycle": is_in_cycle,
                "is_in_ring": is_in_ring,
            })

        account_scores.sort(key=lambda x: x["graph_risk_score"], reverse=True)
        return account_scores

    # ---------------------------------------------------------------------
    # F. Cytoscape.js Visualization Payload
    # ---------------------------------------------------------------------

    def export_cytoscape_payload(
        self,
        account_scores: List[Dict[str, Any]],
        cycles: List[Dict[str, Any]],
        filter_account: Optional[str] = None,
        min_amount: Optional[float] = None,
        risk_category: Optional[str] = None,
        only_suspicious: bool = False,
        limit: int = DEFAULT_GRAPH_EDGE_LIMIT,
    ) -> Dict[str, Any]:
        """
        Format graph nodes and edges into JSON format ready for Cytoscape.js.
        
        Supports interactive filtering by account ID, risk category, min amount,
        and bounds total elements to keep frontend rendering lightweight and snappy.
        """
        score_map = {acc["account_id"]: acc for acc in account_scores}

        # Build cycle edge lookup for highlighting
        cycle_edges_set = set()
        for cyc in cycles:
            nodes = cyc["accounts"]
            for i in range(len(nodes)):
                cycle_edges_set.add((nodes[i], nodes[(i + 1) % len(nodes)]))

        # Filter edges
        selected_edges = []
        for e in self.multi_edges:
            # Min amount filter
            if min_amount is not None and e["amount"] < min_amount:
                continue

            u, v = e["source"], e["target"]
            u_acc = score_map.get(u, {})
            v_acc = score_map.get(v, {})

            # Ego network filter
            if filter_account and filter_account not in (u, v):
                continue

            # Risk category filter
            if risk_category:
                cat = risk_category.capitalize()
                if u_acc.get("risk_category") != cat and v_acc.get("risk_category") != cat:
                    continue

            is_cycle_edge = (u, v) in cycle_edges_set
            is_suspicious = (
                is_cycle_edge
                or e.get("is_flagged", False)
                or u_acc.get("risk_category") in ("High", "Medium")
                or v_acc.get("risk_category") in ("High", "Medium")
            )

            if only_suspicious and not is_suspicious:
                continue

            selected_edges.append({
                "data": {
                    "id": e["transaction_id"],
                    "source": u,
                    "target": v,
                    "amount": e["amount"],
                    "timestamp": e["timestamp"],
                    "transaction_type": e["transaction_type"],
                    "is_cycle_edge": is_cycle_edge,
                    "is_flagged": e.get("is_flagged", False),
                }
            })

            if len(selected_edges) >= limit:
                break

        # Collect relevant nodes from selected edges
        included_node_ids = set()
        for edge_item in selected_edges:
            included_node_ids.add(edge_item["data"]["source"])
            included_node_ids.add(edge_item["data"]["target"])

        # If a single account is searched and has no edges within filters, include it
        if filter_account and filter_account in score_map and not included_node_ids:
            included_node_ids.add(filter_account)

        nodes = []
        for node_id in included_node_ids:
            acc = score_map.get(node_id, {})
            nodes.append({
                "data": {
                    "id": node_id,
                    "label": node_id,
                    "risk_score": acc.get("graph_risk_score", 0.0),
                    "risk_category": acc.get("risk_category", "Low"),
                    "in_degree": acc.get("in_degree", 0),
                    "out_degree": acc.get("out_degree", 0),
                    "total_sent": acc.get("total_sent", 0.0),
                    "total_received": acc.get("total_received", 0.0),
                    "is_in_cycle": acc.get("is_in_cycle", False),
                    "is_in_ring": acc.get("is_in_ring", False),
                    "community_id": acc.get("community_id", 0),
                }
            })

        return {
            "elements": {
                "nodes": nodes,
                "edges": selected_edges,
            },
            "meta": {
                "total_nodes_rendered": len(nodes),
                "total_edges_rendered": len(selected_edges),
                "edge_limit_applied": len(selected_edges) >= limit,
            },
        }

    # ---------------------------------------------------------------------
    # G. Orchestration Pipeline
    # ---------------------------------------------------------------------

    def run_full_analysis(
        self,
        min_amount_cycle: float = CYCLE_MIN_AMOUNT,
        max_cycle_length: int = DEFAULT_MAX_CYCLE_LENGTH,
    ) -> Dict[str, Any]:
        """Execute complete graph analysis pipeline and return enriched data."""
        logger.info("Executing graph topology algorithms...")

        centralities = self.calculate_centralities()
        pagerank = self.calculate_pagerank()
        wcc_mapping = self.calculate_weakly_connected_components()
        community_mapping = self.calculate_communities()

        logger.info("Detecting suspicious transaction cycles...")
        cycles = self.detect_cycles(
            max_length=max_cycle_length,
            min_amount=min_amount_cycle,
        )

        logger.info("Identifying coordinated fraud rings...")
        rings = self.detect_fraud_rings(cycles=cycles)

        logger.info("Calculating graph-based account risk scores...")
        accounts_data = self.calculate_account_risk_scores(
            cycles=cycles,
            rings=rings,
            centralities=centralities,
            pagerank=pagerank,
        )

        # Attach community and component IDs
        for acc in accounts_data:
            node = acc["account_id"]
            acc["community_id"] = community_mapping.get(node, 0)
            acc["component_id"] = wcc_mapping.get(node, 0)

        return {
            "accounts": accounts_data,
            "cycles": cycles,
            "fraud_rings": rings,
            "metrics": {
                "total_nodes": self.G.number_of_nodes(),
                "total_edges": len(self.multi_edges),
                "total_components": len(set(wcc_mapping.values())),
                "total_communities": len(set(community_mapping.values())),
                "total_cycles": len(cycles),
                "total_rings": len(rings),
            },
        }


# -------------------------------------------------------------------------
# CLI Entrypoint
# -------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from src.config import PROCESSED_CSV_PATH
    from src.database import DatabaseManager

    parser = argparse.ArgumentParser(description="FraudGraph Lite Graph Analysis Engine")
    parser.add_argument("--input", type=str, default=str(PROCESSED_CSV_PATH), help="Input processed CSV")
    parser.add_argument("--min-amount", type=float, default=CYCLE_MIN_AMOUNT, help="Min amount filter for cycle detection")
    parser.add_argument("--max-cycle-len", type=int, default=DEFAULT_MAX_CYCLE_LENGTH, help="Max cycle search length")

    args = parser.parse_args()

    print(f"[*] Loading transaction graph from: {args.input}")
    df = pd.read_csv(args.input)
    tx_graph = TransactionGraph(df)
    analyzer = GraphAnalyzer(tx_graph)

    analysis = analyzer.run_full_analysis(
        min_amount_cycle=args.min_amount,
        max_cycle_length=args.max_cycle_len,
    )

    # Persist to SQLite
    db = DatabaseManager()
    db.save_transactions(df)
    db.save_graph_analysis(
        accounts_data=analysis["accounts"],
        cycles_data=analysis["cycles"],
        rings_data=analysis["fraud_rings"],
    )

    metrics = analysis["metrics"]
    print("\n" + "=" * 65)
    print("         FRAUDGRAPH LITE - PHASE 3 GRAPH ANALYSIS REPORT        ")
    print("=" * 65)
    print("\n[+] NETWORK TOPOLOGY OVERVIEW:")
    print(f"    - Total Account Nodes:       {metrics['total_nodes']}")
    print(f"    - Total Transaction Edges:   {metrics['total_edges']}")
    print(f"    - Weakly Connected Clusters: {metrics['total_components']}")
    print(f"    - Louvain Communities:       {metrics['total_communities']}")
    print(f"    - Suspicious Cycles Found:   {metrics['total_cycles']}")
    print(f"    - Coordinated Fraud Rings:   {metrics['total_rings']}")

    rings = analysis["fraud_rings"]
    if rings:
        print(f"\n[+] IDENTIFIED FRAUD RINGS ({len(rings)}):")
        for r in rings:
            acc_str = ", ".join(r["accounts"])
            print(f"    * Ring [{r['ring_id']}]: Accounts [{acc_str}]")
            print(f"        Risk Score: {r['risk_score']} ({r['risk_category']}) | Volume: ${r['total_amount']:,.2f}")
            print(f"        Patterns:   {', '.join(r['detected_patterns'])}")
            print(f"        Details:    {r['explanation']}")

    top_accounts = analysis["accounts"][:5]
    print("\n[+] TOP 5 HIGHEST RISK ACCOUNTS:")
    for acc in top_accounts:
        print(f"    * Account: {acc['account_id']} | Risk Score: {acc['graph_risk_score']} ({acc['risk_category']})")
        print(f"        In-Degree: {acc['in_degree']} | Out-Degree: {acc['out_degree']} | PageRank: {acc['pagerank']:.6f}")
        print(f"        Reasons:   {'; '.join(acc['risk_reasons'])}")

    print("\n" + "=" * 65)

