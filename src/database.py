"""SQLite Database Manager for FraudGraph Lite.

Handles persistence and querying for:
- Accounts and their graph topological metrics
- Detected suspicious transaction cycles
- Identified fraud rings and risk explanations
- Processed transaction records
"""

from contextlib import contextmanager
from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

import pandas as pd

from src.config import DB_PATH

logger = logging.getLogger("fraudgraph.database")


class DatabaseManager:
    """Manages SQLite schema and data access operations for FraudGraph Lite."""

    def __init__(self, db_path: Union[str, Path] = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for SQLite connections with foreign keys enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initialize database schema with required tables and indexes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Accounts Table (Graph Node Metrics & Risk Scores)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                in_degree INTEGER DEFAULT 0,
                out_degree INTEGER DEFAULT 0,
                total_degree INTEGER DEFAULT 0,
                in_degree_centrality REAL DEFAULT 0.0,
                out_degree_centrality REAL DEFAULT 0.0,
                pagerank REAL DEFAULT 0.0,
                community_id INTEGER DEFAULT 0,
                component_id INTEGER DEFAULT 0,
                total_sent REAL DEFAULT 0.0,
                total_received REAL DEFAULT 0.0,
                net_flow REAL DEFAULT 0.0,
                graph_risk_score REAL DEFAULT 0.0,
                risk_category TEXT DEFAULT 'Low',
                risk_reasons TEXT DEFAULT '[]',
                is_in_cycle INTEGER DEFAULT 0,
                is_in_ring INTEGER DEFAULT 0,
                updated_at TEXT
            );
            """)

            # 2. Detected Cycles Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS detected_cycles (
                cycle_id TEXT PRIMARY KEY,
                length INTEGER NOT NULL,
                accounts_json TEXT NOT NULL,
                transactions_json TEXT NOT NULL,
                total_amount REAL DEFAULT 0.0,
                min_amount REAL DEFAULT 0.0,
                max_amount REAL DEFAULT 0.0,
                detected_at TEXT
            );
            """)

            # 3. Fraud Rings Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS fraud_rings (
                ring_id TEXT PRIMARY KEY,
                account_count INTEGER NOT NULL,
                transaction_count INTEGER NOT NULL,
                total_amount REAL DEFAULT 0.0,
                risk_score REAL DEFAULT 0.0,
                risk_category TEXT DEFAULT 'Low',
                detected_patterns_json TEXT NOT NULL,
                accounts_json TEXT NOT NULL,
                explanation TEXT NOT NULL,
                detected_at TEXT
            );
            """)

            # 4. Transactions Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                sender_account TEXT NOT NULL,
                receiver_account TEXT NOT NULL,
                amount REAL NOT NULL,
                timestamp TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                is_fraud INTEGER DEFAULT 0,
                pattern_type TEXT,
                rule_flagged INTEGER DEFAULT 0,
                rule_severity_score REAL DEFAULT 0.0,
                iso_forest_pred INTEGER DEFAULT 0,
                iso_forest_anomaly_score REAL DEFAULT 0.0,
                rf_fraud_pred INTEGER DEFAULT 0,
                rf_fraud_probability REAL DEFAULT 0.0
            );
            """)

            # 5. Investigations Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS investigations (
                investigation_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                risk_score REAL DEFAULT 0.0,
                risk_category TEXT DEFAULT 'Low',
                status TEXT DEFAULT 'New',
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            );
            """)

            # 6. Investigation Notes Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS investigation_notes (
                note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                investigation_id TEXT NOT NULL,
                author TEXT NOT NULL,
                note_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id)
            );
            """)

            # 7. Transaction Risk Scores Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaction_risk_scores (
                transaction_id TEXT PRIMARY KEY,
                transaction_risk_score REAL DEFAULT 0.0,
                risk_category TEXT DEFAULT 'Low',
                detected_patterns TEXT DEFAULT '',
                FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
            );
            """)

            # Indexes for high query performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender_account);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_receiver ON transactions(receiver_account);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_acc_risk ON accounts(graph_risk_score);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_acc_category ON accounts(risk_category);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_acc_community ON accounts(community_id);")

            logger.info("Database schema initialized successfully.")

    def save_transactions(self, df: pd.DataFrame) -> int:
        """Insert or replace transactions from processed DataFrame."""
        if df.empty:
            return 0

        cols = [
            "transaction_id", "sender_account", "receiver_account", "amount",
            "timestamp", "transaction_type", "is_fraud", "pattern_type",
            "rule_flagged", "rule_severity_score", "iso_forest_pred",
            "iso_forest_anomaly_score", "rf_fraud_pred", "rf_fraud_probability"
        ]
        available_cols = [c for c in cols if c in df.columns]

        rows = []
        for _, row in df[available_cols].iterrows():
            record = {}
            for c in cols:
                val = row.get(c, None)
                if pd.isna(val):
                    val = 0 if "pred" in c or "flag" in c or c == "is_fraud" else None
                record[c] = val
            rows.append(tuple(record[c] for c in cols))

        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        query = f"INSERT OR REPLACE INTO transactions ({col_names}) VALUES ({placeholders});"

        with self.get_connection() as conn:
            conn.executemany(query, rows)

        logger.info(f"Saved {len(rows)} transactions to SQLite.")
        return len(rows)

    def save_graph_analysis(
        self,
        accounts_data: List[Dict[str, Any]],
        cycles_data: List[Dict[str, Any]],
        rings_data: List[Dict[str, Any]],
    ) -> None:
        """Atomically persist accounts, cycles, and fraud rings."""
        now = datetime.now().isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Accounts
            account_rows = []
            for acc in accounts_data:
                account_rows.append((
                    acc["account_id"],
                    acc.get("in_degree", 0),
                    acc.get("out_degree", 0),
                    acc.get("total_degree", 0),
                    acc.get("in_degree_centrality", 0.0),
                    acc.get("out_degree_centrality", 0.0),
                    acc.get("pagerank", 0.0),
                    acc.get("community_id", 0),
                    acc.get("component_id", 0),
                    acc.get("total_sent", 0.0),
                    acc.get("total_received", 0.0),
                    acc.get("net_flow", 0.0),
                    acc.get("graph_risk_score", 0.0),
                    acc.get("risk_category", "Low"),
                    json.dumps(acc.get("risk_reasons", [])),
                    1 if acc.get("is_in_cycle", False) else 0,
                    1 if acc.get("is_in_ring", False) else 0,
                    now,
                ))

            cursor.executemany("""
            INSERT OR REPLACE INTO accounts (
                account_id, in_degree, out_degree, total_degree,
                in_degree_centrality, out_degree_centrality, pagerank,
                community_id, component_id, total_sent, total_received,
                net_flow, graph_risk_score, risk_category, risk_reasons,
                is_in_cycle, is_in_ring, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, account_rows)

            # 2. Cycles
            cursor.execute("DELETE FROM detected_cycles;")
            cycle_rows = []
            for cyc in cycles_data:
                cycle_rows.append((
                    cyc["cycle_id"],
                    cyc["length"],
                    json.dumps(cyc["accounts"]),
                    json.dumps(cyc.get("transactions", [])),
                    cyc.get("total_amount", 0.0),
                    cyc.get("min_amount", 0.0),
                    cyc.get("max_amount", 0.0),
                    now,
                ))

            cursor.executemany("""
            INSERT INTO detected_cycles (
                cycle_id, length, accounts_json, transactions_json,
                total_amount, min_amount, max_amount, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, cycle_rows)

            # 3. Fraud Rings
            cursor.execute("DELETE FROM fraud_rings;")
            ring_rows = []
            for ring in rings_data:
                ring_rows.append((
                    ring["ring_id"],
                    ring["account_count"],
                    ring["transaction_count"],
                    ring.get("total_amount", 0.0),
                    ring.get("risk_score", 0.0),
                    ring.get("risk_category", "Low"),
                    json.dumps(ring.get("detected_patterns", [])),
                    json.dumps(ring.get("accounts", [])),
                    ring.get("explanation", ""),
                    now,
                ))

            cursor.executemany("""
            INSERT INTO fraud_rings (
                ring_id, account_count, transaction_count, total_amount,
                risk_score, risk_category, detected_patterns_json,
                accounts_json, explanation, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, ring_rows)

        logger.info(
            f"Saved graph analysis: {len(accounts_data)} accounts, "
            f"{len(cycles_data)} cycles, {len(rings_data)} rings."
        )

    def get_overview(self) -> Dict[str, Any]:
        """Return system overview metrics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Account counts
            cursor.execute("""
            SELECT 
                COUNT(*) as total_accounts,
                SUM(CASE WHEN risk_category = 'High' THEN 1 ELSE 0 END) as high_risk_accounts,
                SUM(CASE WHEN risk_category = 'Medium' THEN 1 ELSE 0 END) as medium_risk_accounts,
                SUM(CASE WHEN risk_category = 'Low' THEN 1 ELSE 0 END) as low_risk_accounts,
                COUNT(DISTINCT community_id) as total_communities,
                COUNT(DISTINCT component_id) as total_components
            FROM accounts;
            """)
            acc_row = cursor.fetchone()

            # Transaction counts
            cursor.execute("""
            SELECT 
                COUNT(*) as total_transactions,
                COALESCE(SUM(amount), 0.0) as total_volume,
                SUM(CASE WHEN rule_flagged = 1 OR iso_forest_pred = 1 OR rf_fraud_pred = 1 THEN 1 ELSE 0 END) as suspicious_transactions
            FROM transactions;
            """)
            tx_row = cursor.fetchone()

            # Cycles and Rings counts
            cursor.execute("SELECT COUNT(*) FROM detected_cycles;")
            cycles_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM fraud_rings;")
            rings_count = cursor.fetchone()[0]

        return {
            "total_accounts": acc_row["total_accounts"] if acc_row else 0,
            "high_risk_accounts": acc_row["high_risk_accounts"] or 0,
            "medium_risk_accounts": acc_row["medium_risk_accounts"] or 0,
            "low_risk_accounts": acc_row["low_risk_accounts"] or 0,
            "total_communities": acc_row["total_communities"] or 0,
            "total_components": acc_row["total_components"] or 0,
            "total_transactions": tx_row["total_transactions"] if tx_row else 0,
            "total_volume": round(float(tx_row["total_volume"] or 0.0), 2) if tx_row else 0.0,
            "suspicious_transactions": tx_row["suspicious_transactions"] or 0,
            "detected_cycles": cycles_count,
            "detected_fraud_rings": rings_count,
        }

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Fetch account record by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE account_id = ?;", (account_id,))
            row = cursor.fetchone()
            if not row:
                return None

            data = dict(row)
            data["risk_reasons"] = json.loads(data["risk_reasons"])
            return data

    def get_account_neighbors(self, account_id: str) -> Dict[str, Any]:
        """Fetch all counterparties interacting with given account."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Outgoing transfers
            cursor.execute("""
            SELECT receiver_account, COUNT(*) as count, SUM(amount) as volume
            FROM transactions
            WHERE sender_account = ?
            GROUP BY receiver_account;
            """, (account_id,))
            outgoing = [dict(r) for r in cursor.fetchall()]

            # Incoming transfers
            cursor.execute("""
            SELECT sender_account, COUNT(*) as count, SUM(amount) as volume
            FROM transactions
            WHERE receiver_account = ?
            GROUP BY sender_account;
            """, (account_id,))
            incoming = [dict(r) for r in cursor.fetchall()]

        return {
            "account_id": account_id,
            "outgoing_neighbors": outgoing,
            "incoming_neighbors": incoming,
        }

    def get_cycles(self, min_length: Optional[int] = None, max_length: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return detected suspicious cycles."""
        query = "SELECT * FROM detected_cycles WHERE 1=1"
        params = []
        if min_length is not None:
            query += " AND length >= ?"
            params.append(min_length)
        if max_length is not None:
            query += " AND length <= ?"
            params.append(max_length)
        query += " ORDER BY total_amount DESC;"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = []
            for r in cursor.fetchall():
                item = dict(r)
                item["accounts"] = json.loads(item["accounts_json"])
                item["transactions"] = json.loads(item["transactions_json"])
                results.append(item)
            return results

    def get_fraud_rings(self) -> List[Dict[str, Any]]:
        """Return all detected fraud rings."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM fraud_rings ORDER BY risk_score DESC;")
            results = []
            for r in cursor.fetchall():
                item = dict(r)
                item["accounts"] = json.loads(item["accounts_json"])
                item["detected_patterns"] = json.loads(item["detected_patterns_json"])
                results.append(item)
            return results

    def get_communities(self) -> List[Dict[str, Any]]:
        """Return communities aggregated with member statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT 
                community_id,
                COUNT(*) as account_count,
                AVG(graph_risk_score) as avg_risk_score,
                SUM(total_sent + total_received) as total_volume,
                SUM(CASE WHEN risk_category = 'High' THEN 1 ELSE 0 END) as high_risk_count
            FROM accounts
            GROUP BY community_id
            ORDER BY high_risk_count DESC, account_count DESC;
            """)
            communities = []
            for r in cursor.fetchall():
                comm_id = r["community_id"]
                # get member account ids
                cursor.execute(
                    "SELECT account_id, risk_category, graph_risk_score FROM accounts WHERE community_id = ?;",
                    (comm_id,)
                )
                members = [dict(m) for m in cursor.fetchall()]
                comm_dict = dict(r)
                comm_dict["avg_risk_score"] = round(float(comm_dict["avg_risk_score"] or 0.0), 2)
                comm_dict["total_volume"] = round(float(comm_dict["total_volume"] or 0.0), 2)
                comm_dict["members"] = members
                communities.append(comm_dict)
            return communities

    def get_risk_scores(self, risk_category: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Return account risk scores with optional category filter."""
        query = "SELECT * FROM accounts"
        params = []
        if risk_category:
            query += " WHERE risk_category = ?"
            params.append(risk_category.capitalize())
        query += " ORDER BY graph_risk_score DESC LIMIT ?;"
        params.append(limit)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = []
            for r in cursor.fetchall():
                item = dict(r)
                item["risk_reasons"] = json.loads(item["risk_reasons"])
                results.append(item)
            return results

    # ---------------------------------------------------------------------
    # Investigation Management
    # ---------------------------------------------------------------------

    def create_investigation(self, account_id: str, reason: str, author: str = "Compliance Officer") -> str:
        """Open a new investigation case for an account."""
        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Fetch current account risk snapshot
            cursor.execute("SELECT graph_risk_score, risk_category FROM accounts WHERE account_id = ?;", (account_id,))
            acc_row = cursor.fetchone()
            score = acc_row["graph_risk_score"] if acc_row else 50.0
            category = acc_row["risk_category"] if acc_row else "Medium"

            # Generate ID: INV_0001
            cursor.execute("SELECT COUNT(*) FROM investigations;")
            inv_num = cursor.fetchone()[0] + 1
            inv_id = f"INV_{inv_num:04d}"

            cursor.execute("""
            INSERT INTO investigations (investigation_id, account_id, risk_score, risk_category, status, reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'New', ?, ?, ?);
            """, (inv_id, account_id, score, category, reason, now, now))

            # Initial opening note
            cursor.execute("""
            INSERT INTO investigation_notes (investigation_id, author, note_text, created_at)
            VALUES (?, ?, ?, ?);
            """, (inv_id, author, f"Case opened. Trigger: {reason}", now))

            return inv_id

    def get_investigations(self, status: Optional[str] = None, risk_category: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List investigation cases with optional status/risk filtering."""
        query = "SELECT * FROM investigations WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if risk_category:
            query += " AND risk_category = ?"
            params.append(risk_category.capitalize())
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_investigation(self, investigation_id: str) -> Optional[Dict[str, Any]]:
        """Fetch investigation details along with notes."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM investigations WHERE investigation_id = ?;", (investigation_id,))
            row = cursor.fetchone()
            if not row:
                return None
            case = dict(row)

            cursor.execute("SELECT * FROM investigation_notes WHERE investigation_id = ? ORDER BY created_at ASC;", (investigation_id,))
            case["notes"] = [dict(n) for n in cursor.fetchall()]
            return case

    def update_investigation_status(self, investigation_id: str, new_status: str, author: str = "Compliance Officer") -> bool:
        """Update investigation status and append audit note."""
        allowed = {"New", "Under Review", "Escalated", "Closed"}
        if new_status not in allowed:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of: {allowed}")

        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM investigations WHERE investigation_id = ?;", (investigation_id,))
            row = cursor.fetchone()
            if not row:
                return False
            old_status = row["status"]

            cursor.execute("""
            UPDATE investigations SET status = ?, updated_at = ? WHERE investigation_id = ?;
            """, (new_status, now, investigation_id))

            cursor.execute("""
            INSERT INTO investigation_notes (investigation_id, author, note_text, created_at)
            VALUES (?, ?, ?, ?);
            """, (investigation_id, author, f"Status updated from '{old_status}' to '{new_status}'", now))
            return True

    def add_investigation_note(self, investigation_id: str, note_text: str, author: str = "Compliance Officer") -> Dict[str, Any]:
        """Add commentary note to an investigation."""
        now = datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM investigations WHERE investigation_id = ?;", (investigation_id,))
            if not cursor.fetchone():
                raise KeyError(f"Investigation '{investigation_id}' not found.")

            cursor.execute("""
            INSERT INTO investigation_notes (investigation_id, author, note_text, created_at)
            VALUES (?, ?, ?, ?);
            """, (investigation_id, author, note_text, now))

            cursor.execute("""
            UPDATE investigations SET updated_at = ? WHERE investigation_id = ?;
            """, (now, investigation_id))

            return {
                "investigation_id": investigation_id,
                "author": author,
                "note_text": note_text,
                "created_at": now,
            }

    # ---------------------------------------------------------------------
    # Transaction Filtering & Pagination
    # ---------------------------------------------------------------------

    def save_transaction_risk_scores(self, scores: List[Dict[str, Any]]) -> None:
        """Persist calculated transaction risk scores."""
        rows = [
            (s["transaction_id"], s["transaction_risk_score"], s["risk_category"], s.get("detected_patterns", ""))
            for s in scores
        ]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
            INSERT OR REPLACE INTO transaction_risk_scores (transaction_id, transaction_risk_score, risk_category, detected_patterns)
            VALUES (?, ?, ?, ?);
            """, rows)

    def get_transactions_paginated(
        self,
        search: Optional[str] = None,
        risk_category: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        is_suspicious: Optional[bool] = None,
        sort_by: str = "timestamp",
        sort_order: str = "DESC",
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Search, filter, and paginate transactions with risk metadata."""
        allowed_sort = {"timestamp", "amount", "transaction_risk_score", "transaction_id"}
        order_col = sort_by if sort_by in allowed_sort else "timestamp"
        order_dir = "ASC" if sort_order.upper() == "ASC" else "DESC"

        query_base = """
        FROM transactions t
        LEFT JOIN transaction_risk_scores tr ON t.transaction_id = tr.transaction_id
        WHERE 1=1
        """
        params = []

        if search:
            query_base += " AND (t.transaction_id LIKE ? OR t.sender_account LIKE ? OR t.receiver_account LIKE ?)"
            s_param = f"%{search.strip()}%"
            params.extend([s_param, s_param, s_param])

        if risk_category:
            query_base += " AND tr.risk_category = ?"
            params.append(risk_category.capitalize())

        if min_amount is not None:
            query_base += " AND t.amount >= ?"
            params.append(min_amount)

        if max_amount is not None:
            query_base += " AND t.amount <= ?"
            params.append(max_amount)

        if is_suspicious is True:
            query_base += " AND (t.rule_flagged = 1 OR t.iso_forest_pred = 1 OR t.rf_fraud_pred = 1)"
        elif is_suspicious is False:
            query_base += " AND (t.rule_flagged = 0 AND t.iso_forest_pred = 0 AND t.rf_fraud_pred = 0)"

        count_query = f"SELECT COUNT(*) {query_base};"
        data_query = f"""
        SELECT 
            t.transaction_id, t.sender_account, t.receiver_account, t.amount,
            t.timestamp, t.transaction_type, t.rule_flagged, t.rule_severity_score,
            t.iso_forest_pred, t.iso_forest_anomaly_score, t.rf_fraud_pred,
            t.rf_fraud_probability,
            COALESCE(tr.transaction_risk_score, t.rule_severity_score, 0.0) as transaction_risk_score,
            COALESCE(tr.risk_category, 'Low') as risk_category,
            COALESCE(tr.detected_patterns, '') as detected_patterns
        {query_base}
        ORDER BY {order_col} {order_dir}
        LIMIT ? OFFSET ?;
        """
        data_params = list(params) + [limit, offset]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(count_query, params)
            total_records = cursor.fetchone()[0]

            cursor.execute(data_query, data_params)
            rows = [dict(r) for r in cursor.fetchall()]

        return {
            "total_records": total_records,
            "limit": limit,
            "offset": offset,
            "transactions": rows,
        }

    def get_dashboard_charts(self) -> Dict[str, Any]:
        """Aggregate data specifically for Chart.js dashboard charts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Transactions over time (daily volume & count)
            cursor.execute("""
            SELECT 
                SUBSTR(timestamp, 1, 10) as tx_date,
                COUNT(*) as count,
                SUM(amount) as volume,
                SUM(CASE WHEN rule_flagged = 1 OR iso_forest_pred = 1 OR rf_fraud_pred = 1 THEN 1 ELSE 0 END) as suspicious_count
            FROM transactions
            GROUP BY tx_date
            ORDER BY tx_date ASC;
            """)
            timeline = [dict(r) for r in cursor.fetchall()]

            # 2. Risk category distribution (Accounts)
            cursor.execute("""
            SELECT risk_category, COUNT(*) as count
            FROM accounts
            GROUP BY risk_category;
            """)
            risk_dist = {r["risk_category"]: r["count"] for r in cursor.fetchall()}

            # 3. Detection method comparison
            cursor.execute("""
            SELECT 
                SUM(rule_flagged) as rule_based_count,
                SUM(iso_forest_pred) as isolation_forest_count,
                SUM(rf_fraud_pred) as random_forest_count,
                SUM(CASE WHEN rule_flagged = 1 AND (iso_forest_pred = 1 OR rf_fraud_pred = 1) THEN 1 ELSE 0 END) as multi_model_count
            FROM transactions;
            """)
            method_row = cursor.fetchone()

            # 4. Top high-risk accounts
            cursor.execute("""
            SELECT account_id, graph_risk_score, risk_category, total_sent, total_received, out_degree, in_degree
            FROM accounts
            ORDER BY graph_risk_score DESC
            LIMIT 8;
            """)
            top_accounts = [dict(r) for r in cursor.fetchall()]

        return {
            "timeline": timeline,
            "risk_distribution": risk_dist,
            "detection_methods": dict(method_row) if method_row else {},
            "top_risk_accounts": top_accounts,
        }

    def get_recent_flagged_transactions(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Return recently flagged transactions for feed widgets."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT transaction_id, sender_account, receiver_account, amount, timestamp,
                   rule_severity_score, iso_forest_anomaly_score, rf_fraud_probability
            FROM transactions
            WHERE rule_flagged = 1 OR iso_forest_pred = 1 OR rf_fraud_pred = 1
            ORDER BY timestamp DESC
            LIMIT ?;
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

