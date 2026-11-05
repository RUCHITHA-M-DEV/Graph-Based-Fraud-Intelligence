"""Fraud Detection and Transaction Preprocessing Engine for FraudGraph Lite.

Provides:
1. DataPreprocessor: Validates schema, cleans records, handles missing/corrupt values.
2. FeatureEngineer: Extracts behavioral and velocity features without label leakage.
3. RuleBasedDetector: Rule engine detecting amount anomalies, structuring, bursts, and repeats.
4. IsolationForestDetector: Unsupervised anomaly detection with normalized scores.
5. SupervisedFraudModel: Random Forest classifier with class imbalance handling.
6. ModelEvaluator & FraudDetectionPipeline: Comprehensive multi-model evaluation and orchestration.
"""

import argparse
from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.config import (
    DEFAULT_CSV_PATH,
    ENGINEERED_FEATURE_COLUMNS,
    HIGH_AMOUNT_THRESHOLD,
    ISO_FOREST_MODEL_PATH,
    ISOLATION_FOREST_CONTAMINATION,
    MODELS_DIR,
    PROCESSED_CSV_PATH,
    RANDOM_SEED,
    RAPID_TX_MIN_COUNT,
    RAPID_TX_WINDOW_SECONDS,
    REQUIRED_COLUMNS,
    RF_MODEL_PATH,
    STRUCTURING_MAX,
    STRUCTURING_MIN,
    TRANSACTION_TYPES,
)

logger = logging.getLogger("fraudgraph.detector")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# -------------------------------------------------------------------------
# 1. Data Preprocessing
# -------------------------------------------------------------------------

@dataclass
class PreprocessingSummary:
    """Summary of data cleaning and quality filtering operations."""
    total_raw_rows: int = 0
    final_cleaned_rows: int = 0
    duplicate_rows_removed: int = 0
    missing_critical_values_removed: int = 0
    invalid_amounts_removed: int = 0
    invalid_timestamps_removed: int = 0
    self_transfers_removed: int = 0

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


class DataPreprocessor:
    """Validates transaction schema, handles corrupt values, and sanitizes input data."""

    def __init__(self, required_columns: Optional[List[str]] = None):
        self.required_columns = required_columns or REQUIRED_COLUMNS

    def load_data(self, source: Union[str, Path, pd.DataFrame]) -> pd.DataFrame:
        """Load data from CSV file path or return copy of provided DataFrame."""
        if isinstance(source, (str, Path)):
            path = Path(source)
            if not path.exists():
                raise FileNotFoundError(f"Transaction CSV not found at: {path}")
            return pd.read_csv(path)
        elif isinstance(source, pd.DataFrame):
            return source.copy()
        else:
            raise TypeError(f"Unsupported data source type: {type(source)}")

    def validate_and_clean(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, PreprocessingSummary]:
        """
        Validate schema, cleanse invalid rows, and generate audit summary.

        Cleansing actions:
        - Validate required columns presence.
        - Remove duplicate transaction_ids or identical rows.
        - Drop rows with null sender_account, receiver_account, or amount.
        - Coerce and validate amount (> 0.00).
        - Parse ISO timestamps and drop unparseable rows.
        - Filter out invalid self-transfers (sender == receiver).
        """
        summary = PreprocessingSummary(total_raw_rows=len(df))

        # 1. Validate required columns
        for col in self.required_columns:
            if col not in df.columns:
                raise ValueError(f"Missing required dataset column: '{col}'")

        cleaned = df.copy()

        # 2. Handle duplicates
        initial_count = len(cleaned)
        cleaned = cleaned.drop_duplicates(subset=["transaction_id"], keep="first")
        summary.duplicate_rows_removed = initial_count - len(cleaned)

        # 3. Handle missing critical fields
        initial_count = len(cleaned)
        cleaned = cleaned.dropna(subset=["sender_account", "receiver_account", "amount", "timestamp"])
        summary.missing_critical_values_removed = initial_count - len(cleaned)

        # Clean transaction_type: fill missing with 'TRANSFER' and ensure uppercase string
        cleaned["transaction_type"] = (
            cleaned["transaction_type"]
            .fillna("TRANSFER")
            .astype(str)
            .str.upper()
        )

        # 4. Validate amount (must be positive numeric)
        initial_count = len(cleaned)
        cleaned["amount"] = pd.to_numeric(cleaned["amount"], errors="coerce")
        cleaned = cleaned[cleaned["amount"].notnull() & (cleaned["amount"] > 0)]
        cleaned["amount"] = cleaned["amount"].round(2)
        summary.invalid_amounts_removed = initial_count - len(cleaned)

        # 5. Parse and validate timestamps
        initial_count = len(cleaned)
        cleaned["timestamp_dt"] = pd.to_datetime(cleaned["timestamp"], errors="coerce")
        cleaned = cleaned[cleaned["timestamp_dt"].notnull()]
        summary.invalid_timestamps_removed = initial_count - len(cleaned)

        # 6. Filter out self-transfers (sender == receiver)
        initial_count = len(cleaned)
        cleaned = cleaned[cleaned["sender_account"] != cleaned["receiver_account"]]
        summary.self_transfers_removed = initial_count - len(cleaned)

        # 7. Chronological ordering
        cleaned = cleaned.sort_values("timestamp_dt").reset_index(drop=True)
        summary.final_cleaned_rows = len(cleaned)

        return cleaned, summary


# -------------------------------------------------------------------------
# 2. Feature Engineering
# -------------------------------------------------------------------------

class FeatureEngineer:
    """
    Extracts transaction-level behavioral and velocity features.
    
    IMPORTANT: Excludes any target fraud labels ('is_fraud') to prevent data leakage.
    """

    def __init__(self, feature_columns: Optional[List[str]] = None):
        self.feature_columns = feature_columns or ENGINEERED_FEATURE_COLUMNS

    @staticmethod
    def _compute_window_counts(df: pd.DataFrame, window_seconds: int) -> pd.Series:
        """Compute rolling count of transactions per sender in the preceding window seconds."""
        counts = {}
        for _, group in df.groupby("sender_account", sort=False):
            times = group["timestamp_dt"].values.astype("int64") // 10**9
            # For each timestamp t, count how many fall in [t - window_seconds, t]
            left_indices = np.searchsorted(times, times - window_seconds, side="left")
            right_indices = np.arange(len(times)) + 1
            for idx, c in zip(group.index, right_indices - left_indices):
                counts[idx] = c
        return pd.Series(counts, index=df.index).fillna(1).astype(int)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate feature set on the preprocessed DataFrame.
        
        Features:
        - amount, log_amount
        - sender_tx_count, sender_avg_amount, amount_to_avg_ratio
        - tx_count_last_1h, tx_count_last_24h
        - time_since_prev_tx
        - receiver_tx_count, sender_unique_receivers
        - is_night_tx
        - One-hot transaction types
        """
        data = df.copy()

        # 1. Base amount & log amount
        data["log_amount"] = np.log1p(data["amount"])

        # 2. Historical sender aggregates
        sender_stats = data.groupby("sender_account")["amount"].agg(["count", "mean"]).rename(
            columns={"count": "sender_tx_count", "mean": "sender_avg_amount"}
        )
        data = data.merge(sender_stats, on="sender_account", how="left")
        data["amount_to_avg_ratio"] = (data["amount"] / (data["sender_avg_amount"] + 1e-5)).round(4)

        # 3. Inter-transaction timing per sender
        data["prev_timestamp"] = data.groupby("sender_account")["timestamp_dt"].shift(1)
        data["time_since_prev_tx"] = (
            (data["timestamp_dt"] - data["prev_timestamp"]).dt.total_seconds().fillna(86400.0)
        )
        data.drop(columns=["prev_timestamp"], inplace=True)

        # 4. Sliding time-window velocity counts per sender
        data["tx_count_last_1h"] = self._compute_window_counts(data, 3600)
        data["tx_count_last_24h"] = self._compute_window_counts(data, 86400)

        # 5. Receiver & counterparty diversity
        rec_counts = data["receiver_account"].value_counts()
        data["receiver_tx_count"] = data["receiver_account"].map(rec_counts).fillna(0).astype(int)

        unique_rec = data.groupby("sender_account")["receiver_account"].nunique()
        data["sender_unique_receivers"] = data["sender_account"].map(unique_rec).fillna(0).astype(int)

        # 6. Night transaction flag (23:00 to 06:00)
        data["is_night_tx"] = (
            (data["timestamp_dt"].dt.hour >= 23) | (data["timestamp_dt"].dt.hour < 6)
        ).astype(int)

        # 7. One-hot encoded transaction types
        for t in TRANSACTION_TYPES:
            col_name = f"is_type_{t.lower()}"
            data[col_name] = (data["transaction_type"] == t).astype(int)

        return data

    def get_feature_matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract the exact feature matrix X for ML models."""
        missing = [col for col in self.feature_columns if col not in df.columns]
        if missing:
            raise KeyError(f"DataFrame is missing engineered feature columns: {missing}")
        return df[self.feature_columns].copy()


# -------------------------------------------------------------------------
# 3. Rule-Based Detection Engine
# -------------------------------------------------------------------------

class RuleBasedDetector:
    """Configurable rule engine detecting common financial fraud indicators."""

    def __init__(
        self,
        high_amount_threshold: float = HIGH_AMOUNT_THRESHOLD,
        structuring_min: float = STRUCTURING_MIN,
        structuring_max: float = STRUCTURING_MAX,
        rapid_window_seconds: int = RAPID_TX_WINDOW_SECONDS,
        rapid_min_count: int = RAPID_TX_MIN_COUNT,
    ):
        self.high_amount_threshold = high_amount_threshold
        self.structuring_min = structuring_min
        self.structuring_max = structuring_max
        self.rapid_window_seconds = rapid_window_seconds
        self.rapid_min_count = rapid_min_count

    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Evaluate configurable rules on transactions and append flag metadata.

        Returns DataFrame with:
        - rule_flagged: int (1 if any rule triggered, 0 otherwise)
        - triggered_rules: list of str
        - rule_reasons: str (semicolon-delimited descriptions)
        - rule_severity_score: float (0 to 100)
        """
        data = df.copy()

        # Rule 1: High Amount Spike
        rule_high_amt = (
            (data["amount"] >= self.high_amount_threshold)
            | ((data["amount"] > data["sender_avg_amount"] * 5.0) & (data["amount"] > 5000.0))
        )

        # Rule 2: Rapid Repeated Velocity Burst
        rule_rapid = (
            (data["time_since_prev_tx"] <= self.rapid_window_seconds)
            & (data["tx_count_last_1h"] >= self.rapid_min_count)
        )

        # Rule 3: Smurfing / Structuring (sub-threshold amounts in 24h)
        rule_structuring = (
            (data["amount"] >= self.structuring_min)
            & (data["amount"] <= self.structuring_max)
            & (data["tx_count_last_24h"] >= 2)
        )

        # Rule 4: Repeated Transfers to same counterparty with near-identical amount
        pair_prev_time = data.groupby(["sender_account", "receiver_account"])["timestamp_dt"].shift(1)
        pair_prev_amt = data.groupby(["sender_account", "receiver_account"])["amount"].shift(1)
        pair_next_time = data.groupby(["sender_account", "receiver_account"])["timestamp_dt"].shift(-1)
        pair_next_amt = data.groupby(["sender_account", "receiver_account"])["amount"].shift(-1)

        prev_match = (
            ((data["timestamp_dt"] - pair_prev_time).dt.total_seconds() <= 3600)
            & ((data["amount"] - pair_prev_amt).abs() <= 10.0)
        )
        next_match = (
            ((pair_next_time - data["timestamp_dt"]).dt.total_seconds() <= 3600)
            & ((data["amount"] - pair_next_amt).abs() <= 10.0)
        )
        rule_repeated = prev_match | next_match

        # Rule 5: Unusual Transaction Frequency
        rule_unusual_freq = (data["tx_count_last_1h"] >= 4) | (data["tx_count_last_24h"] >= 8)

        # Compile triggers and reasons
        triggered_rules_col = []
        rule_reasons_col = []
        severity_col = []
        flagged_col = []

        for i in range(len(data)):
            triggers = []
            reasons = []
            score = 0.0

            if rule_high_amt.iloc[i]:
                triggers.append("RULE_HIGH_AMOUNT")
                reasons.append(f"Unusually large transaction amount (${data['amount'].iloc[i]:,.2f})")
                score += 40.0

            if rule_rapid.iloc[i]:
                triggers.append("RULE_RAPID_BURST")
                reasons.append("High velocity burst: multiple transfers in short time window")
                score += 30.0

            if rule_structuring.iloc[i]:
                triggers.append("RULE_STRUCTURING")
                reasons.append("Potential smurfing / structuring just below $10,000 threshold")
                score += 35.0

            if rule_repeated.iloc[i]:
                triggers.append("RULE_REPEATED_TRANSFER")
                reasons.append("Rapid repeated transfer of identical amount to same counterparty")
                score += 30.0

            if rule_unusual_freq.iloc[i]:
                triggers.append("RULE_UNUSUAL_FREQ")
                reasons.append("Abnormally elevated transaction frequency per account")
                score += 25.0

            is_flagged = 1 if len(triggers) > 0 else 0
            final_score = min(100.0, score)

            triggered_rules_col.append(triggers)
            rule_reasons_col.append("; ".join(reasons) if reasons else "Normal transaction")
            severity_col.append(round(final_score, 1))
            flagged_col.append(is_flagged)

        data["rule_flagged"] = flagged_col
        data["triggered_rules"] = triggered_rules_col
        data["rule_reasons"] = rule_reasons_col
        data["rule_severity_score"] = severity_col

        return data


# -------------------------------------------------------------------------
# 4. Unsupervised ML: Isolation Forest
# -------------------------------------------------------------------------

class IsolationForestDetector:
    """
    Unsupervised outlier detector using Isolation Forest.
    
    Interpretation:
    - Isolation Forest isolates anomalies by randomly partitioning features.
    - Anomaly score is min-max normalized to [0, 1].
    - Score > 0.60 indicates a significant statistical anomaly compared to normal baseline.
    """

    def __init__(
        self,
        contamination: float = ISOLATION_FOREST_CONTAMINATION,
        random_state: int = RANDOM_SEED,
    ):
        self.contamination = contamination
        self.random_state = random_state
        self.model = IsolationForest(
            contamination=self.contamination,
            random_state=self.random_state,
            n_estimators=100,
            n_jobs=-1,
        )
        self.is_fitted = False
        self._score_min: float = 0.0
        self._score_max: float = 1.0

    def fit(self, X: pd.DataFrame) -> "IsolationForestDetector":
        """Fit Isolation Forest on unlabeled feature matrix X."""
        self.model.fit(X)
        self.is_fitted = True

        # Compute raw decision function bounds for normalization
        # Note: In scikit-learn, decision_function is negative for anomalies and positive for inliers
        raw_scores = -self.model.decision_function(X)
        self._score_min = float(np.min(raw_scores))
        self._score_max = float(np.max(raw_scores))
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict binary anomalies: 1 for anomaly (fraud), 0 for normal."""
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict.")
        raw_preds = self.model.predict(X)
        # scikit-learn convention: -1 is outlier, 1 is inlier
        return np.where(raw_preds == -1, 1, 0)

    def score_samples(self, X: pd.DataFrame) -> np.ndarray:
        """
        Compute normalized anomaly scores between 0.0 and 1.0.
        
        Higher score = higher likelihood of being an anomaly.
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before score_samples.")
        raw_scores = -self.model.decision_function(X)
        spread = max(1e-5, self._score_max - self._score_min)
        norm_scores = (raw_scores - self._score_min) / spread
        return np.clip(norm_scores, 0.0, 1.0).round(4)

    def save(self, filepath: Union[str, Path] = ISO_FOREST_MODEL_PATH) -> None:
        """Save fitted Isolation Forest model to disk."""
        joblib.dump(
            {
                "model": self.model,
                "is_fitted": self.is_fitted,
                "score_min": self._score_min,
                "score_max": self._score_max,
                "contamination": self.contamination,
            },
            filepath,
        )

    @classmethod
    def load(cls, filepath: Union[str, Path] = ISO_FOREST_MODEL_PATH) -> "IsolationForestDetector":
        """Load fitted Isolation Forest model from disk."""
        data = joblib.load(filepath)
        instance = cls(contamination=data["contamination"])
        instance.model = data["model"]
        instance.is_fitted = data["is_fitted"]
        instance._score_min = data["score_min"]
        instance._score_max = data["score_max"]
        return instance


# -------------------------------------------------------------------------
# 5. Supervised ML: Random Forest Baseline
# -------------------------------------------------------------------------

class SupervisedFraudModel:
    """
    Supervised Random Forest baseline for benchmark evaluation.
    
    Includes StandardScaler fitted strictly on training data to prevent leakage,
    and class_weight='balanced' to handle fraud label imbalance.
    """

    def __init__(self, random_state: int = RANDOM_SEED, n_estimators: int = 100):
        self.random_state = random_state
        self.n_estimators = n_estimators
        self.scaler = StandardScaler()
        self.classifier = RandomForestClassifier(
            n_estimators=self.n_estimators,
            class_weight="balanced",
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.is_fitted = False

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> "SupervisedFraudModel":
        """Fit scaler and Random Forest on training split."""
        X_scaled = self.scaler.fit_transform(X_train)
        self.classifier.fit(X_scaled, y_train)
        self.is_fitted = True
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict class labels: 1 for fraud, 0 for normal."""
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict.")
        X_scaled = self.scaler.transform(X)
        return self.classifier.predict(X_scaled)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Predict fraud probability [0.0, 1.0]."""
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict_proba.")
        X_scaled = self.scaler.transform(X)
        return self.classifier.predict_proba(X_scaled)[:, 1].round(4)

    def get_feature_importances(self, feature_names: List[str]) -> Dict[str, float]:
        """Return dictionary mapping feature names to their Gini importance."""
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted.")
        importances = self.classifier.feature_importances_
        return dict(
            sorted(
                {feat: round(float(imp), 4) for feat, imp in zip(feature_names, importances)}.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        )

    def save(self, filepath: Union[str, Path] = RF_MODEL_PATH) -> None:
        """Save fitted model and scaler to disk."""
        joblib.dump(
            {
                "scaler": self.scaler,
                "classifier": self.classifier,
                "is_fitted": self.is_fitted,
            },
            filepath,
        )

    @classmethod
    def load(cls, filepath: Union[str, Path] = RF_MODEL_PATH) -> "SupervisedFraudModel":
        """Load fitted model and scaler from disk."""
        data = joblib.load(filepath)
        instance = cls()
        instance.scaler = data["scaler"]
        instance.classifier = data["classifier"]
        instance.is_fitted = data["is_fitted"]
        return instance


# -------------------------------------------------------------------------
# 6. Evaluation Utilities
# -------------------------------------------------------------------------

class ModelEvaluator:
    """Computes comprehensive evaluation metrics comparing rules, IF, and RF."""

    @staticmethod
    def calculate_metrics(y_true: Union[List, np.ndarray, pd.Series],
                          y_pred: Union[List, np.ndarray, pd.Series],
                          y_score: Optional[Union[List, np.ndarray, pd.Series]] = None) -> Dict[str, Any]:
        """Compute standard classification metrics and confusion matrix."""
        y_t = np.array(y_true).astype(int)
        y_p = np.array(y_pred).astype(int)

        acc = accuracy_score(y_t, y_p)
        prec = precision_score(y_t, y_p, zero_division=0)
        rec = recall_score(y_t, y_p, zero_division=0)
        f1 = f1_score(y_t, y_p, zero_division=0)

        roc_auc = None
        if y_score is not None:
            try:
                roc_auc = round(float(roc_auc_score(y_t, y_score)), 4)
            except ValueError:
                roc_auc = None

        cm = confusion_matrix(y_t, y_p).tolist()

        return {
            "accuracy": round(float(acc), 4),
            "precision": round(float(prec), 4),
            "recall": round(float(rec), 4),
            "f1_score": round(float(f1), 4),
            "roc_auc": roc_auc,
            "confusion_matrix": {
                "true_negative": cm[0][0] if len(cm) > 1 else 0,
                "false_positive": cm[0][1] if len(cm) > 1 else 0,
                "false_negative": cm[1][0] if len(cm) > 1 else 0,
                "true_positive": cm[1][1] if len(cm) > 1 else 0,
            },
        }

    @classmethod
    def compare_models(
        cls,
        y_test: pd.Series,
        rule_preds: np.ndarray,
        iso_preds: np.ndarray,
        rf_preds: np.ndarray,
        rule_scores: Optional[np.ndarray] = None,
        iso_scores: Optional[np.ndarray] = None,
        rf_scores: Optional[np.ndarray] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Compare performance across Rule-based, Isolation Forest, and Random Forest."""
        return {
            "rule_based": cls.calculate_metrics(y_test, rule_preds, rule_scores),
            "isolation_forest": cls.calculate_metrics(y_test, iso_preds, iso_scores),
            "random_forest": cls.calculate_metrics(y_test, rf_preds, rf_scores),
        }


# -------------------------------------------------------------------------
# 7. Fraud Detection Pipeline Orchestrator
# -------------------------------------------------------------------------

class FraudDetectionPipeline:
    """Orchestrates end-to-end preprocessing, feature engineering, rules, and ML."""

    def __init__(self):
        self.preprocessor = DataPreprocessor()
        self.feature_engineer = FeatureEngineer()
        self.rule_detector = RuleBasedDetector()
        self.iso_detector = IsolationForestDetector()
        self.supervised_model = SupervisedFraudModel()

    def run_pipeline(
        self,
        input_csv: Union[str, Path] = DEFAULT_CSV_PATH,
        save_processed: bool = True,
        save_models: bool = True,
        processed_output_path: Union[str, Path] = PROCESSED_CSV_PATH,
    ) -> Dict[str, Any]:
        """
        Execute full pipeline:
        1. Load & clean data
        2. Feature engineering (no label leakage)
        3. Rule-based detection
        4. Isolation Forest anomaly scoring
        5. Random Forest supervised baseline (train/test split)
        6. Performance evaluation
        """
        logger.info(f"Loading data from: {input_csv}")
        raw_df = self.preprocessor.load_data(input_csv)

        logger.info("Validating and cleaning transaction records...")
        cleaned_df, summary = self.preprocessor.validate_and_clean(raw_df)

        logger.info("Extracting behavioral and velocity features...")
        enriched_df = self.feature_engineer.transform(cleaned_df)

        logger.info("Executing rule-based detection engine...")
        flagged_df = self.rule_detector.evaluate(enriched_df)

        # Feature matrix X without target labels
        X = self.feature_engineer.get_feature_matrix(flagged_df)
        y = flagged_df["is_fraud"] if "is_fraud" in flagged_df.columns else None

        logger.info("Training Isolation Forest unsupervised detector...")
        self.iso_detector.fit(X)
        flagged_df["iso_forest_pred"] = self.iso_detector.predict(X)
        flagged_df["iso_forest_anomaly_score"] = self.iso_detector.score_samples(X)

        evaluation_results = {}
        rf_importances = {}

        if y is not None:
            logger.info("Splitting training and test sets (stratified 75/25)...")
            X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
                X, y, flagged_df.index, test_size=0.25, random_state=RANDOM_SEED, stratify=y
            )

            logger.info("Training Supervised Random Forest baseline...")
            self.supervised_model.fit(X_train, y_train)

            # Test split evaluation
            rf_test_preds = self.supervised_model.predict(X_test)
            rf_test_probs = self.supervised_model.predict_proba(X_test)
            rf_importances = self.supervised_model.get_feature_importances(self.feature_engineer.feature_columns)

            rule_test_preds = flagged_df.loc[idx_test, "rule_flagged"].values
            rule_test_scores = flagged_df.loc[idx_test, "rule_severity_score"].values / 100.0

            iso_test_preds = flagged_df.loc[idx_test, "iso_forest_pred"].values
            iso_test_scores = flagged_df.loc[idx_test, "iso_forest_anomaly_score"].values

            evaluation_results = ModelEvaluator.compare_models(
                y_test=y_test,
                rule_preds=rule_test_preds,
                iso_preds=iso_test_preds,
                rf_preds=rf_test_preds,
                rule_scores=rule_test_scores,
                iso_scores=iso_test_scores,
                rf_scores=rf_test_probs,
            )

            # Assign predictions on entire dataset for dashboard/storage
            flagged_df["rf_fraud_pred"] = self.supervised_model.predict(X)
            flagged_df["rf_fraud_probability"] = self.supervised_model.predict_proba(X)

        # Save artifacts
        if save_models:
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            self.iso_detector.save(ISO_FOREST_MODEL_PATH)
            if y is not None:
                self.supervised_model.save(RF_MODEL_PATH)
            logger.info(f"Models successfully saved to: {MODELS_DIR}")

        if save_processed:
            output_p = Path(processed_output_path)
            output_p.parent.mkdir(parents=True, exist_ok=True)
            # Remove timestamp_dt object before saving
            export_df = flagged_df.copy()
            if "timestamp_dt" in export_df.columns:
                export_df.drop(columns=["timestamp_dt"], inplace=True)
            export_df.to_csv(output_p, index=False)
            logger.info(f"Processed dataset saved to: {output_p}")

        return {
            "summary": summary.to_dict(),
            "evaluation": evaluation_results,
            "feature_importances": rf_importances,
            "processed_df": flagged_df,
        }


# -------------------------------------------------------------------------
# CLI Entrypoint
# -------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FraudGraph Lite Detection Pipeline")
    parser.add_argument("--input", type=str, default=str(DEFAULT_CSV_PATH), help="Input raw transactions CSV")
    parser.add_argument("--output", type=str, default=str(PROCESSED_CSV_PATH), help="Output processed CSV")

    args = parser.parse_args()

    pipeline = FraudDetectionPipeline()
    results = pipeline.run_pipeline(input_csv=args.input, processed_output_path=args.output)

    print("\n" + "=" * 65)
    print("           FRAUDGRAPH LITE - PHASE 2 DETECTION REPORT           ")
    print("=" * 65)

    print("\n[+] PREPROCESSING SUMMARY:")
    for k, v in results["summary"].items():
        print(f"    - {k.replace('_', ' ').title()}: {v}")

    eval_data = results["evaluation"]
    if eval_data:
        print("\n[+] MODEL COMPARISON BENCHMARK (Held-out Test Split - 625 Transactions):")
        print(f"{'Model':<20} | {'Accuracy':<10} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10} | {'ROC-AUC':<10}")
        print("-" * 75)
        for model_name, metrics in eval_data.items():
            display_name = model_name.replace("_", " ").title()
            auc_str = f"{metrics['roc_auc']:.4f}" if metrics['roc_auc'] is not None else "N/A"
            print(
                f"{display_name:<20} | "
                f"{metrics['accuracy']:<10.4f} | "
                f"{metrics['precision']:<10.4f} | "
                f"{metrics['recall']:<10.4f} | "
                f"{metrics['f1_score']:<10.4f} | "
                f"{auc_str:<10}"
            )

        print("\n[+] CONFUSION MATRICES:")
        for model_name, metrics in eval_data.items():
            cm = metrics["confusion_matrix"]
            print(f"    * {model_name.replace('_', ' ').title()}:")
            print(f"        TN: {cm['true_negative']:<4} | FP: {cm['false_positive']:<4}")
            print(f"        FN: {cm['false_negative']:<4} | TP: {cm['true_positive']:<4}")

        print("\n[+] TOP 5 RANDOM FOREST FEATURE IMPORTANCES:")
        top_features = list(results["feature_importances"].items())[:5]
        for feat, imp in top_features:
            print(f"    - {feat:<25}: {imp:.4f}")

    print("\n" + "=" * 65)

