"""Unit tests for the synthetic dataset generator (Phase 1)."""

from datetime import datetime
import os
import tempfile

import pandas as pd
import pytest

from src.config import REQUIRED_COLUMNS, TRANSACTION_TYPES
from src.generator import SyntheticTransactionGenerator, generate_and_save_dataset


def test_generator_output_schema():
    """Verify that generated DataFrame contains all required columns."""
    generator = SyntheticTransactionGenerator(num_accounts=50, random_seed=42)
    df = generator.generate(total_transactions=200, fraud_ratio=0.1)

    for col in REQUIRED_COLUMNS:
        assert col in df.columns, f"Expected column '{col}' missing from generated DataFrame."


def test_generator_counts_and_fraud_ratio():
    """Verify total rows and approximate fraud ratio."""
    generator = SyntheticTransactionGenerator(num_accounts=60, random_seed=123)
    total_tx = 500
    target_fraud_ratio = 0.10
    df = generator.generate(total_transactions=total_tx, fraud_ratio=target_fraud_ratio)

    assert len(df) == total_tx
    fraud_count = df["is_fraud"].sum()
    expected_fraud = int(total_tx * target_fraud_ratio)
    assert fraud_count == expected_fraud


def test_no_self_transfers():
    """Ensure no transaction has the same sender and receiver."""
    generator = SyntheticTransactionGenerator(num_accounts=40, random_seed=99)
    df = generator.generate(total_transactions=300, fraud_ratio=0.15)

    self_transfers = df[df["sender_account"] == df["receiver_account"]]
    assert len(self_transfers) == 0, "Found invalid self-transfers where sender == receiver."


def test_amounts_and_types_are_valid():
    """Verify amounts are positive and transaction types conform to allowed types."""
    generator = SyntheticTransactionGenerator(num_accounts=50, random_seed=42)
    df = generator.generate(total_transactions=200, fraud_ratio=0.1)

    assert (df["amount"] > 0).all(), "Found non-positive transaction amounts."
    assert set(df["transaction_type"]).issubset(set(TRANSACTION_TYPES)), "Found unknown transaction types."


def test_timestamps_chronologically_sorted():
    """Verify timestamp parsing and sorted order."""
    generator = SyntheticTransactionGenerator(num_accounts=50, random_seed=42)
    df = generator.generate(total_transactions=300, fraud_ratio=0.08)

    parsed_dates = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for ts in df["timestamp"]]
    for i in range(len(parsed_dates) - 1):
        assert parsed_dates[i] <= parsed_dates[i + 1], "Transactions are not in chronological order."


def test_fraud_patterns_present():
    """Verify that multiple fraudulent pattern types are represented."""
    generator = SyntheticTransactionGenerator(num_accounts=100, random_seed=42)
    df = generator.generate(total_transactions=1000, fraud_ratio=0.15)

    fraud_df = df[df["is_fraud"] == 1]
    pattern_counts = fraud_df["pattern_type"].value_counts()

    # Must contain multiple fraud types
    assert len(pattern_counts) >= 4, f"Expected multiple fraud patterns, got: {list(pattern_counts.keys())}"
    assert "normal" in df["pattern_type"].values


def test_reproducibility():
    """Verify that the same random seed produces identical results."""
    gen1 = SyntheticTransactionGenerator(num_accounts=50, random_seed=777)
    df1 = gen1.generate(total_transactions=150, fraud_ratio=0.1)

    gen2 = SyntheticTransactionGenerator(num_accounts=50, random_seed=777)
    df2 = gen2.generate(total_transactions=150, fraud_ratio=0.1)

    pd.testing.assert_frame_equal(df1, df2)


def test_csv_file_generation():
    """Verify generate_and_save_dataset writes a readable CSV file."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp_file:
        tmp_path = tmp_file.name

    try:
        generate_and_save_dataset(output_path=tmp_path, count=100, accounts=30, fraud_ratio=0.1, seed=42)
        assert os.path.exists(tmp_path)
        loaded_df = pd.read_csv(tmp_path)
        assert len(loaded_df) == 100
        for col in REQUIRED_COLUMNS:
            assert col in loaded_df.columns
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

