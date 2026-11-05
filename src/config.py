import os
from pathlib import Path

# Base Paths
SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MODELS_DIR = DATA_DIR / "models"
DB_DIR = DATA_DIR / "database"

# Ensure runtime directories exist
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

# File Paths
DEFAULT_CSV_PATH = RAW_DATA_DIR / "sample_transactions.csv"
PROCESSED_CSV_PATH = PROCESSED_DATA_DIR / "processed_transactions.csv"
RF_MODEL_PATH = MODELS_DIR / "random_forest_baseline.joblib"
ISO_FOREST_MODEL_PATH = MODELS_DIR / "isolation_forest.joblib"
DB_PATH = DB_DIR / "fraudgraph.db"

# Dataset Schema
REQUIRED_COLUMNS = [
    "transaction_id",
    "sender_account",
    "receiver_account",
    "amount",
    "timestamp",
    "transaction_type",
    "is_fraud"
]

TRANSACTION_TYPES = [
    "TRANSFER",
    "PAYMENT",
    "CASH_OUT",
    "DEBIT"
]

# Detection Rule Thresholds
HIGH_AMOUNT_THRESHOLD = 50000.0   # Outlier amount
STRUCTURING_MIN = 8500.0         # Just below standard $10,000 threshold
STRUCTURING_MAX = 9999.0
RAPID_TX_WINDOW_SECONDS = 900     # 15 minutes window for velocity bursts
RAPID_TX_MIN_COUNT = 3            # >= 3 transactions in window is rapid

# ML Model Settings
ISOLATION_FOREST_CONTAMINATION = 0.08
RANDOM_SEED = 42

# Feature Engineering Columns (no labels)
ENGINEERED_FEATURE_COLUMNS = [
    "amount",
    "log_amount",
    "sender_tx_count",
    "sender_avg_amount",
    "amount_to_avg_ratio",
    "tx_count_last_1h",
    "tx_count_last_24h",
    "time_since_prev_tx",
    "receiver_tx_count",
    "sender_unique_receivers",
    "is_night_tx",
    "is_type_transfer",
    "is_type_payment",
    "is_type_cash_out",
    "is_type_debit"
]

# Risk Score Bands
RISK_BANDS = {
    "LOW": (0, 39),
    "MEDIUM": (40, 69),
    "HIGH": (70, 100)
}

# Graph Analysis Settings
DEFAULT_MAX_CYCLE_LENGTH = 4
CYCLE_MIN_AMOUNT = 1000.0
CYCLE_TIME_WINDOW_HOURS = 72
DEFAULT_GRAPH_EDGE_LIMIT = 500
PAGERANK_ALPHA = 0.85
PAGERANK_MAX_ITER = 100


