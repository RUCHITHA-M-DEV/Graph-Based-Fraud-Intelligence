# REST API Specification & Endpoint Documentation

This document describes all RESTful APIs and view endpoints exposed by the **Graph-Based Fraud Intelligence** platform (`src/app.py`).

**Base URL**: `http://127.0.0.1:5000`  
**Data Format**: JSON (`application/json`) / CSV (`text/csv`) / PDF (`application/pdf`)

---

## 1. Web Views (HTML)

| Path | Method | Description |
|---|---|---|
| `/` | `GET` | Main executive overview dashboard with KPI cards and dynamic charts. |
| `/transactions` | `GET` | Tabular transaction explorer with real-time multi-filter queries. |
| `/investigation` | `GET` | Detailed account forensic dossier and risk factor breakdown. |
| `/network` | `GET` | Interactive Cytoscape.js directed graph visualization workbench. |
| `/rings` | `GET` | Fraud ring and cyclic laundering topology explorer. |
| `/cases` | `GET` | Investigation case board, status updates, and note logging. |
| `/analytics` | `GET` | ML model performance metrics, feature importance, and distributions. |
| `/monitoring` | `GET` | Real-time system health, memory usage, and database telemetry. |

---

## 2. Dashboard Endpoints

### `GET /api/dashboard/kpis`
Returns high-level platform statistics and metrics.

**Response** (`200 OK`):
```json
{
  "total_transactions": 2500,
  "total_volume": 4125300.50,
  "flagged_transactions": 214,
  "flagged_volume": 1284500.00,
  "total_accounts": 150,
  "high_risk_accounts": 18,
  "detected_cycles": 6,
  "detected_fraud_rings": 3,
  "active_investigations": 5
}
```

### `GET /api/dashboard/charts`
Provides aggregated timeseries and category splits for Chart.js rendering.

**Response** (`200 OK`):
```json
{
  "risk_distribution": {
    "Low": 112,
    "Medium": 20,
    "High": 12,
    "Critical": 6
  },
  "hourly_volume": [
    {"hour": "00:00", "amount": 14200.0, "count": 12},
    {"hour": "01:00", "amount": 8900.0, "count": 7}
  ],
  "transaction_types": {
    "TRANSFER": 1400,
    "PAYMENT": 650,
    "CASH_OUT": 300,
    "DEBIT": 150
  }
}
```

### `GET /api/dashboard/alerts`
Fetches the 10 most recent high-severity suspicious transactions.

**Parameters**:
- `limit` (int, default=10): Maximum number of alerts.

---

## 3. Transaction Explorer Endpoints

### `GET /api/transactions`
Paginates through transactions with granular search and filtering.

**Parameters**:
- `search` (string): Account ID or transaction ID substring.
- `type` (string): `TRANSFER`, `PAYMENT`, `CASH_OUT`, `DEBIT`.
- `min_amount` (float): Minimum transaction value.
- `max_amount` (float): Maximum transaction value.
- `risk_category` (string): `Low`, `Medium`, `High`, `Critical`.
- `is_fraud` (int): Filter by known label (`0` or `1`).
- `limit` (int, default=50): Records per page.
- `offset` (int, default=0): Pagination offset.

**Response** (`200 OK`):
```json
{
  "count": 50,
  "total": 2500,
  "transactions": [
    {
      "transaction_id": "TXN_00000001",
      "sender_account": "ACC_0001",
      "receiver_account": "ACC_0045",
      "amount": 9500.00,
      "timestamp": "2026-11-01 10:14:22",
      "transaction_type": "TRANSFER",
      "rule_flags": ["SUSPICIOUS_STRUCTURING"],
      "anomaly_score": 0.78,
      "risk_score": 88.5,
      "risk_category": "Critical"
    }
  ]
}
```

### `GET /api/transaction/<transaction_id>`
Fetches complete details and engineered feature values for a specific transaction.

---

## 4. Account Profile & Risk Scoring Endpoints

### `GET /api/account/<account_id>`
Retrieves unified profile metrics, balance flows, and active risk scoring.

**Response** (`200 OK`):
```json
{
  "account_id": "ACC_0012",
  "total_sent": 85000.00,
  "total_received": 84200.00,
  "transaction_count": 28,
  "risk_score": 82.4,
  "risk_category": "High",
  "in_degree": 4,
  "out_degree": 5,
  "pagerank": 0.0142,
  "is_in_cycle": 1,
  "is_in_ring": 1,
  "risk_reasons": [
    "Part of 3-step circular transfer chain",
    "High PageRank score indicates systemic fund transit hub"
  ]
}
```

### `GET /api/account/<account_id>/risk`
Returns a breakdown of the 5 scoring components:
- Rule-based score (20%)
- Isolation Forest anomaly score (15%)
- Supervised Random Forest score (25%)
- Graph centrality score (20%)
- Ring & cycle topology score (20%)

---

## 5. Investigation Management Endpoints

### `GET /api/investigations`
Lists forensic investigation cases. Supports optional status filter (`?status=New`).

### `POST /api/investigations`
Opens a new forensic case for an account.

**Request Body**:
```json
{
  "account_id": "ACC_0012",
  "priority": "High",
  "assigned_to": "Investigator Jones",
  "reason": "Circular transfer cycle detected with total velocity > $50k"
}
```

**Response** (`201 Created`):
```json
{
  "investigation_id": "INV_0001",
  "account_id": "ACC_0012",
  "status": "New",
  "priority": "High",
  "created_at": "2026-11-06T00:15:00"
}
```

### `PATCH /api/investigation/<investigation_id>/status`
Updates case status (`New`, `Under Review`, `Escalated`, `Closed`).

**Request Body**:
```json
{
  "status": "Escalated"
}
```

### `POST /api/investigation/<investigation_id>/notes`
Appends timestamped notes from forensic analysts.

**Request Body**:
```json
{
  "note": "Subpoena requested for counterparty KYC records."
}
```

---

## 6. Report Export Endpoints

### `GET /api/reports/investigation/<investigation_id>/pdf`
Generates and downloads a two-page executive PDF investigation dossier with risk badges, metrics tables, transaction history, and forensic sign-off boxes.

### `GET /api/reports/account/<account_id>/csv`
Downloads an account-specific transaction history ledger as a CSV file.

### `GET /api/reports/investigations/csv`
Downloads all active and closed investigations as a CSV audit register.

---

## 7. Graph Engine Endpoints

### `POST /api/graph/build`
Triggers full graph construction and network analytics on a target CSV.

**Request Body** (optional):
```json
{
  "csv_path": "data/processed/processed_transactions.csv",
  "min_amount_cycle": 1000.0,
  "max_cycle_length": 4
}
```

### `GET /api/graph/visualization`
Exports nodes and edges formatted specifically for Cytoscape.js rendering.

**Parameters**:
- `account_id` (string): Center graph around specific account node.
- `min_amount` (float): Minimum transaction edge amount.
- `risk_category` (string): `Low`, `Medium`, `High`, `Critical`.
- `only_suspicious` (bool): If true, renders only nodes in cycles/rings.
- `limit` (int, default=200): Upper bound of edges returned.

**Response** (`200 OK`):
```json
{
  "elements": {
    "nodes": [
      {
        "data": {
          "id": "ACC_0001",
          "label": "ACC_0001",
          "risk_score": 85.0,
          "risk_category": "Critical",
          "is_in_cycle": true
        }
      }
    ],
    "edges": [
      {
        "data": {
          "id": "e_TXN_001",
          "source": "ACC_0001",
          "target": "ACC_0002",
          "amount": 25000.0,
          "is_cycle": true
        }
      }
    ]
  },
  "meta": {
    "total_nodes_rendered": 15,
    "total_edges_rendered": 18,
    "edge_limit_applied": false
  }
}
```

### `GET /api/graph/cycles`
Lists all detected circular transaction chains ($A \to B \to \dots \to A$).

### `GET /api/graph/fraud-rings`
Returns all identified fraud rings with member rosters, capital sum, and pattern labels.

---

## 8. System & Health Endpoints

### `GET /api/health` or `GET /api/system/health`
Health check for load balancers and container orchestrators.

**Response** (`200 OK`):
```json
{
  "status": "healthy",
  "uptime_seconds": 124.5,
  "database_connected": true,
  "graph_cached": true,
  "model_ready": true
}
```

### `GET /api/system/statistics`
Returns cache statistics, node and cycle cache lengths, and active database size.
