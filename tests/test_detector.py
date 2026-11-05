"""Unit tests for Phase 2: Transaction Preprocessing & Fraud Detection."""

import numpy as np
import pandas as pd
import pytest

from src.config import ENGINEERED_FEATURE_COLUMNS, REQUIRED_COLUMNS
from src.detector import (
    DataPreprocessor,
    FeatureEngineer,
    FraudDetectionPipeline,
    IsolationForestDetector,
    ModelEvaluator,
    RuleBasedDetector,
    SupervisedFraudModel,
)


@pytest.fixture
def dirty_sample_df():
    """Fixture with deliberate data quality anomalies."""
    return pd.DataFrame([
        # Normal record
        {"transaction_id": "TXN_1", "sender_account": "ACC_1", "receiver_account": "ACC_2",
         "amount": 100.0, "timestamp": "2026-10-01 10:00:00", "transaction_type": "TRANSFER", "is_fraud": 0},
        # Duplicate record
        {"transaction_id": "TXN_1", "sender_account": "ACC_1", "receiver_account": "ACC_2",
         "amount": 100.0, "timestamp": "2026-10-01 10:00:00", "transaction_type": "TRANSFER", "is_fraud": 0},
        # Missing critical value
        {"transaction_id": "TXN_2", "sender_account": None, "receiver_account": "ACC_2",
         "amount": 50.0, "timestamp": "2026-10-01 10:05:00", "transaction_type": "TRANSFER", "is_fraud": 0},
        # Negative amount
        {"transaction_id": "TXN_3", "sender_account": "ACC_2", "receiver_account": "ACC_3",
         "amount": -20.0, "timestamp": "2026-10-01 10:10:00", "transaction_type": "TRANSFER", "is_fraud": 0},
        # Invalid timestamp
        {"transaction_id": "TXN_4", "sender_account": "ACC_3", "receiver_account": "ACC_4",
         "amount": 75.0, "timestamp": "invalid_date", "transaction_type": "PAYMENT", "is_fraud": 0},
        # Self-transfer
        {"transaction_id": "TXN_5", "sender_account": "ACC_5", "receiver_account": "ACC_5",
         "amount": 500.0, "timestamp": "2026-10-01 10:20:00", "transaction_type": "TRANSFER", "is_fraud": 0},
        # Valid second record
        {"transaction_id": "TXN_6", "sender_account": "ACC_4", "receiver_account": "ACC_5",
         "amount": 250.0, "timestamp": "2026-10-01 10:30:00", "transaction_type": "PAYMENT", "is_fraud": 0},
    ])


@pytest.fixture
def clean_sample_df():
    """Fixture with valid transactions and diverse patterns."""
    return pd.DataFrame([
        {"transaction_id": "T1", "sender_account": "ACC_A", "receiver_account": "ACC_B",
         "amount": 120.0, "timestamp": "2026-10-01 09:00:00", "transaction_type": "TRANSFER", "is_fraud": 0},
        {"transaction_id": "T2", "sender_account": "ACC_A", "receiver_account": "ACC_B",
         "amount": 120.0, "timestamp": "2026-10-01 09:02:00", "transaction_type": "TRANSFER", "is_fraud": 1},
        {"transaction_id": "T3", "sender_account": "ACC_A", "receiver_account": "ACC_B",
         "amount": 125.0, "timestamp": "2026-10-01 09:04:00", "transaction_type": "TRANSFER", "is_fraud": 1},
        {"transaction_id": "T4", "sender_account": "ACC_C", "receiver_account": "ACC_D",
         "amount": 9200.0, "timestamp": "2026-10-01 11:00:00", "transaction_type": "TRANSFER", "is_fraud": 1},
        {"transaction_id": "T5", "sender_account": "ACC_C", "receiver_account": "ACC_D",
         "amount": 9500.0, "timestamp": "2026-10-01 12:00:00", "transaction_type": "TRANSFER", "is_fraud": 1},
        {"transaction_id": "T6", "sender_account": "ACC_E", "receiver_account": "ACC_F",
         "amount": 150000.0, "timestamp": "2026-10-01 14:00:00", "transaction_type": "TRANSFER", "is_fraud": 1},
        {"transaction_id": "T7", "sender_account": "ACC_G", "receiver_account": "ACC_H",
         "amount": 45.0, "timestamp": "2026-10-01 15:00:00", "transaction_type": "PAYMENT", "is_fraud": 0},
        {"transaction_id": "T8", "sender_account": "ACC_I", "receiver_account": "ACC_J",
         "amount": 310.0, "timestamp": "2026-10-01 16:00:00", "transaction_type": "DEBIT", "is_fraud": 0},
    ])


def test_data_preprocessor_cleansing(dirty_sample_df):
    """Verify that corrupt, duplicate, and invalid rows are properly sanitized."""
    preprocessor = DataPreprocessor()
    cleaned, summary = preprocessor.validate_and_clean(dirty_sample_df)

    assert summary.total_raw_rows == 7
    assert summary.final_cleaned_rows == 2
    assert summary.duplicate_rows_removed == 1
    assert summary.missing_critical_values_removed == 1
    assert summary.invalid_amounts_removed == 1
    assert summary.invalid_timestamps_removed == 1
    assert summary.self_transfers_removed == 1
    assert set(cleaned["transaction_id"]) == {"TXN_1", "TXN_6"}


def test_feature_engineering_no_label_leakage(clean_sample_df):
    """Verify feature matrix generation and absence of label leakage."""
    preprocessor = DataPreprocessor()
    cleaned, _ = preprocessor.validate_and_clean(clean_sample_df)

    engineer = FeatureEngineer()
    enriched = engineer.transform(cleaned)
    X = engineer.get_feature_matrix(enriched)

    assert "is_fraud" not in X.columns
    assert "transaction_id" not in X.columns
    for col in ENGINEERED_FEATURE_COLUMNS:
        assert col in X.columns
    assert not X.isnull().any().any(), "Engineered feature matrix contains NaN values"


def test_rule_based_detection_flags(clean_sample_df):
    """Verify that rule detector correctly catches high amount, structuring, and repeated bursts."""
    preprocessor = DataPreprocessor()
    cleaned, _ = preprocessor.validate_and_clean(clean_sample_df)
    engineer = FeatureEngineer()
    enriched = engineer.transform(cleaned)

    detector = RuleBasedDetector()
    flagged = detector.evaluate(enriched)

    assert "rule_flagged" in flagged.columns
    assert "triggered_rules" in flagged.columns
    assert "rule_reasons" in flagged.columns

    # High amount test (T6: $150,000)
    t6_row = flagged[flagged["transaction_id"] == "T6"].iloc[0]
    assert "RULE_HIGH_AMOUNT" in t6_row["triggered_rules"]

    # Structuring test (T4 and T5: ~$9,000+)
    t5_row = flagged[flagged["transaction_id"] == "T5"].iloc[0]
    assert "RULE_STRUCTURING" in t5_row["triggered_rules"]

    # Normal transactions (T7, T8)
    t7_row = flagged[flagged["transaction_id"] == "T7"].iloc[0]
    assert t7_row["rule_flagged"] == 0


def test_isolation_forest_anomaly_scoring(clean_sample_df):
    """Verify unsupervised Isolation Forest anomaly prediction and scoring."""
    preprocessor = DataPreprocessor()
    cleaned, _ = preprocessor.validate_and_clean(clean_sample_df)
    engineer = FeatureEngineer()
    enriched = engineer.transform(cleaned)
    X = engineer.get_feature_matrix(enriched)

    iso = IsolationForestDetector(contamination=0.25, random_state=42)
    iso.fit(X)

    preds = iso.predict(X)
    scores = iso.score_samples(X)

    assert set(preds).issubset({0, 1})
    assert len(preds) == len(clean_sample_df)
    assert (scores >= 0.0).all() and (scores <= 1.0).all()


def test_supervised_random_forest_training_and_serialization(tmp_path, clean_sample_df):
    """Verify Random Forest training, probability output, and serialization."""
    preprocessor = DataPreprocessor()
    cleaned, _ = preprocessor.validate_and_clean(clean_sample_df)
    engineer = FeatureEngineer()
    enriched = engineer.transform(cleaned)
    X = engineer.get_feature_matrix(enriched)
    y = cleaned["is_fraud"]

    rf = SupervisedFraudModel(random_state=42, n_estimators=10)
    rf.fit(X, y)

    preds = rf.predict(X)
    probs = rf.predict_proba(X)

    assert len(preds) == len(X)
    assert len(probs) == len(X)
    assert (probs >= 0.0).all() and (probs <= 1.0).all()

    # Model save and load test
    model_file = tmp_path / "test_rf.joblib"
    rf.save(model_file)
    assert model_file.exists()

    loaded_rf = SupervisedFraudModel.load(model_file)
    loaded_preds = loaded_rf.predict(X)
    np.testing.assert_array_equal(preds, loaded_preds)


def test_model_evaluator_metrics():
    """Verify metric calculations against known expectations."""
    y_true = [0, 0, 0, 0, 1, 1, 1, 1]
    y_pred = [0, 0, 0, 1, 0, 1, 1, 1]
    y_score = [0.1, 0.2, 0.1, 0.8, 0.3, 0.9, 0.85, 0.95]

    metrics = ModelEvaluator.calculate_metrics(y_true, y_pred, y_score)

    assert metrics["accuracy"] == 0.75
    assert metrics["precision"] == 0.75  # TP=3, FP=1 -> 3/4
    assert metrics["recall"] == 0.75     # TP=3, FN=1 -> 3/4
    assert metrics["f1_score"] == 0.75
    assert metrics["roc_auc"] > 0.8
    assert metrics["confusion_matrix"]["true_positive"] == 3
    assert metrics["confusion_matrix"]["false_negative"] == 1


def test_pipeline_end_to_end(tmp_path):
    """Verify entire detection pipeline execution on sample CSV."""
    from src.generator import generate_and_save_dataset

    sample_csv = tmp_path / "test_txs.csv"
    processed_csv = tmp_path / "test_processed.csv"

    generate_and_save_dataset(
        output_path=str(sample_csv),
        count=150,
        accounts=25,
        fraud_ratio=0.10,
        seed=42,
    )

    pipeline = FraudDetectionPipeline()
    results = pipeline.run_pipeline(
        input_csv=sample_csv,
        save_processed=True,
        save_models=False,
        processed_output_path=processed_csv,
    )

    assert results["summary"]["final_cleaned_rows"] == 150
    assert "random_forest" in results["evaluation"]
    assert "isolation_forest" in results["evaluation"]
    assert "rule_based" in results["evaluation"]
    assert processed_csv.exists()

    processed_df = pd.read_csv(processed_csv)
    expected_output_cols = [
        "rule_flagged",
        "triggered_rules",
        "iso_forest_pred",
        "iso_forest_anomaly_score",
        "rf_fraud_pred",
        "rf_fraud_probability",
    ]
    for col in expected_output_cols:
        assert col in processed_df.columns

