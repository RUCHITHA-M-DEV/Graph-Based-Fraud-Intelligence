"""Synthetic Financial Transaction Dataset Generator for FraudGraph Lite.

Generates realistic normal transaction traffic along with injected fraudulent patterns:
- Structuring / Smurfing (sub-threshold transfers)
- Velocity bursts (rapid repeated transfers)
- Circular money flows (fraud rings: A -> B -> C -> A)
- High-value anomaly spikes
- Dispersal and aggregation (fan-out / fan-in)
"""

import argparse
from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.config import (
    DEFAULT_CSV_PATH,
    HIGH_AMOUNT_THRESHOLD,
    RANDOM_SEED,
    REQUIRED_COLUMNS,
    STRUCTURING_MAX,
    STRUCTURING_MIN,
    TRANSACTION_TYPES,
)


class SyntheticTransactionGenerator:
    """Generates synthetic banking transactions with realistic normal and fraudulent patterns."""

    def __init__(
        self,
        num_accounts: int = 150,
        random_seed: int = RANDOM_SEED,
        start_date: Optional[datetime] = None,
        duration_days: int = 30,
    ):
        self.num_accounts = max(10, num_accounts)
        self.random_seed = random_seed
        self.duration_days = duration_days

        # Set seeds for reproducibility
        random.seed(self.random_seed)
        np.random.seed(self.random_seed)

        # Base time window
        if start_date is None:
            self.start_date = datetime(2026, 10, 1, 8, 0, 0)
        else:
            self.start_date = start_date

        # Account IDs: ACC_0001, ACC_0002, ...
        self.accounts = [f"ACC_{i:04d}" for i in range(1, self.num_accounts + 1)]

        # Dedicated fraud ring accounts (subset of accounts)
        n = len(self.accounts)
        self.fraud_ring_accounts_3 = self.accounts[0:3]
        if n >= 7:
            self.fraud_ring_accounts_4 = self.accounts[3:7]
            self.smurfing_senders = self.accounts[0:3]
            self.smurfing_receivers = self.accounts[3:6]
        else:
            self.fraud_ring_accounts_4 = [self.accounts[i % n] for i in range(3)]
            self.smurfing_senders = [self.accounts[0]]
            self.smurfing_receivers = [self.accounts[1]]

    def _random_timestamp(self) -> datetime:
        """Generate a random timestamp within duration_days, weighted by business hours."""
        random_day = random.uniform(0, self.duration_days)
        # Bimodal peak during daytime (around 12:00 and 17:00)
        hour = int(np.clip(np.random.normal(loc=14, scale=4), 0, 23))
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        return self.start_date + timedelta(days=random_day, hours=hour, minutes=minute, seconds=second)

    def _generate_normal_transactions(self, count: int) -> List[Dict]:
        """Generate normal, legitimate banking transactions."""
        records = []
        for _ in range(count):
            sender, receiver = random.sample(self.accounts, 2)

            # Log-normal distribution for typical banking amounts: median ~$120, 95th percentile ~$1,500
            raw_amount = float(np.random.lognormal(mean=4.8, sigma=1.0))
            amount = round(max(5.0, min(raw_amount, 6500.0)), 2)

            # Legitimate transactions favor standard types
            tx_type = random.choices(
                population=TRANSACTION_TYPES,
                weights=[0.45, 0.35, 0.10, 0.10],
                k=1,
            )[0]

            ts = self._random_timestamp()

            records.append({
                "sender_account": sender,
                "receiver_account": receiver,
                "amount": amount,
                "timestamp": ts,
                "transaction_type": tx_type,
                "is_fraud": 0,
                "pattern_type": "normal",
            })
        return records

    def _generate_structuring_pattern(self, base_time: datetime) -> List[Dict]:
        """Generate structuring/smurfing: multiple sub-threshold amounts sent rapidly."""
        records = []
        sender = random.choice(self.smurfing_senders)
        receiver = random.choice(self.smurfing_receivers)

        # 3 to 5 transactions just below the $10,000 threshold
        num_bursts = random.randint(3, 5)
        current_time = base_time

        for _ in range(num_bursts):
            amount = round(random.uniform(STRUCTURING_MIN, STRUCTURING_MAX), 2)
            records.append({
                "sender_account": sender,
                "receiver_account": receiver,
                "amount": amount,
                "timestamp": current_time,
                "transaction_type": "TRANSFER",
                "is_fraud": 1,
                "pattern_type": "structuring",
            })
            # Rapid spacing: 10 to 45 minutes apart
            current_time += timedelta(minutes=random.randint(10, 45), seconds=random.randint(0, 59))
        return records

    def _generate_rapid_repeat_pattern(self, base_time: datetime) -> List[Dict]:
        """Generate rapid repeated transactions (velocity burst) between same accounts."""
        records = []
        sender, receiver = random.sample(self.accounts, 2)
        base_amount = round(random.uniform(800.0, 4500.0), 2)

        # 4 to 6 rapid transactions
        num_tx = random.randint(4, 6)
        current_time = base_time

        for _ in range(num_tx):
            # Similar or identical amounts
            amount = round(base_amount + random.choice([0.0, 5.0, -5.0]), 2)
            records.append({
                "sender_account": sender,
                "receiver_account": receiver,
                "amount": amount,
                "timestamp": current_time,
                "transaction_type": random.choice(["TRANSFER", "PAYMENT"]),
                "is_fraud": 1,
                "pattern_type": "rapid_repeat",
            })
            # Burst within 30 to 180 seconds
            current_time += timedelta(seconds=random.randint(30, 180))
        return records

    def _generate_circular_ring_pattern(self, base_time: datetime, ring_size: int = 3) -> List[Dict]:
        """Generate circular money movement (A -> B -> C -> A or A -> B -> C -> D -> A)."""
        records = []
        if ring_size == 3 or len(self.fraud_ring_accounts_4) < 4:
            nodes = self.fraud_ring_accounts_3
        else:
            nodes = self.fraud_ring_accounts_4

        initial_amount = round(random.uniform(15000.0, 48000.0), 2)
        current_time = base_time
        current_amount = initial_amount

        for i in range(len(nodes)):
            sender = nodes[i]
            receiver = nodes[(i + 1) % len(nodes)]

            # Laundering cuts/fees: 1-2% decrease per hop
            hop_amount = round(current_amount * random.uniform(0.97, 0.99), 2)
            current_amount = hop_amount

            records.append({
                "sender_account": sender,
                "receiver_account": receiver,
                "amount": hop_amount,
                "timestamp": current_time,
                "transaction_type": "TRANSFER",
                "is_fraud": 1,
                "pattern_type": "cycle_ring",
            })
            # 15 to 90 minutes between hops
            current_time += timedelta(minutes=random.randint(15, 90))
        return records

    def _generate_large_spike_pattern(self, base_time: datetime) -> List[Dict]:
        """Generate an unusually large transaction far outside typical distribution."""
        sender, receiver = random.sample(self.accounts, 2)
        amount = round(random.uniform(HIGH_AMOUNT_THRESHOLD + 5000.0, 250000.0), 2)

        return [{
            "sender_account": sender,
            "receiver_account": receiver,
            "amount": amount,
            "timestamp": base_time,
            "transaction_type": random.choice(["TRANSFER", "CASH_OUT"]),
            "is_fraud": 1,
            "pattern_type": "large_spike",
        }]

    def _generate_fan_out_pattern(self, base_time: datetime) -> List[Dict]:
        """Generate a fan-out dispersal pattern: one hub disperses funds to many receivers."""
        records = []
        sender = random.choice(self.accounts)
        candidates = [acc for acc in self.accounts if acc != sender]
        k = min(5, len(candidates))
        receivers = random.sample(candidates, k)

        current_time = base_time
        for r in receivers:
            amount = round(random.uniform(3000.0, 7500.0), 2)
            records.append({
                "sender_account": sender,
                "receiver_account": r,
                "amount": amount,
                "timestamp": current_time,
                "transaction_type": "TRANSFER",
                "is_fraud": 1,
                "pattern_type": "fan_out",
            })
            current_time += timedelta(minutes=random.randint(2, 10))
        return records

    def generate(self, total_transactions: int = 2000, fraud_ratio: float = 0.08) -> pd.DataFrame:
        """
        Generate a complete dataset of normal and fraudulent transactions.

        Args:
            total_transactions: Target total transaction count
            fraud_ratio: Target proportion of fraudulent transactions (e.g. 0.08 = 8%)

        Returns:
            pd.DataFrame sorted chronologically with standardized schema
        """
        target_fraud_count = int(total_transactions * fraud_ratio)
        target_normal_count = total_transactions - target_fraud_count

        # 1. Normal transactions
        all_records = self._generate_normal_transactions(target_normal_count)

        # 2. Fraud patterns injection
        fraud_records = []
        pattern_generators = [
            ("structuring", self._generate_structuring_pattern),
            ("rapid_repeat", self._generate_rapid_repeat_pattern),
            ("cycle_ring_3", lambda t: self._generate_circular_ring_pattern(t, ring_size=3)),
            ("cycle_ring_4", lambda t: self._generate_circular_ring_pattern(t, ring_size=4)),
            ("large_spike", self._generate_large_spike_pattern),
            ("fan_out", self._generate_fan_out_pattern),
        ]

        while len(fraud_records) < target_fraud_count:
            # Pick a pattern and a random reference time
            _, gen_func = random.choice(pattern_generators)
            base_time = self._random_timestamp()
            pattern_txs = gen_func(base_time)
            fraud_records.extend(pattern_txs)

        # Trim exact fraud count to keep requested ratio close
        fraud_records = fraud_records[:target_fraud_count]
        all_records.extend(fraud_records)

        # Convert to DataFrame
        df = pd.DataFrame(all_records)

        # Sort chronologically
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Format timestamp to ISO string
        df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

        # Assign unique transaction IDs (TXN_000001, ...)
        df.insert(0, "transaction_id", [f"TXN_{i+1:06d}" for i in range(len(df))])

        # Validate schema
        for col in REQUIRED_COLUMNS:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Ensure amounts are rounded floats
        df["amount"] = df["amount"].round(2)

        return df


def generate_and_save_dataset(
    output_path: str = str(DEFAULT_CSV_PATH),
    count: int = 2000,
    accounts: int = 150,
    fraud_ratio: float = 0.08,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Convenience helper to generate and save synthetic dataset to CSV."""
    generator = SyntheticTransactionGenerator(
        num_accounts=accounts,
        random_seed=seed,
    )
    df = generator.generate(total_transactions=count, fraud_ratio=fraud_ratio)
    df.to_csv(output_path, index=False)
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FraudGraph Lite Synthetic Transaction Generator")
    parser.add_argument("--count", type=int, default=2000, help="Total transactions to generate")
    parser.add_argument("--accounts", type=int, default=150, help="Number of distinct bank accounts")
    parser.add_argument("--fraud-ratio", type=float, default=0.08, help="Ratio of fraudulent transactions")
    parser.add_argument("--output", type=str, default=str(DEFAULT_CSV_PATH), help="Destination CSV file path")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED, help="Random seed for reproducibility")

    args = parser.parse_args()

    print(f"[*] Generating {args.count} synthetic transactions with {int(args.fraud_ratio * 100)}% fraud ratio...")
    dataset = generate_and_save_dataset(
        output_path=args.output,
        count=args.count,
        accounts=args.accounts,
        fraud_ratio=args.fraud_ratio,
        seed=args.seed,
    )
    fraud_count = int(dataset["is_fraud"].sum())
    normal_count = len(dataset) - fraud_count

    print(f"[✓] Generation complete!")
    print(f"    - Output file: {args.output}")
    print(f"    - Total transactions: {len(dataset)}")
    print(f"    - Normal transactions: {normal_count}")
    print(f"    - Fraudulent transactions: {fraud_count} ({fraud_count/len(dataset)*100:.1f}%)")
    print(f"    - Distinct accounts: {len(set(dataset['sender_account']).union(set(dataset['receiver_account'])))}")
    print("\nPattern breakdown:")
    print(dataset["pattern_type"].value_counts().to_string())
