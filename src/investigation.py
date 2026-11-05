"""Investigation Management Service for Graph-Based Fraud Intelligence.

Manages case creation, status progression, commentary notes, and investigator workflows.
"""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from src.database import DatabaseManager

logger = logging.getLogger("fraudgraph.investigation")


class InvestigationManager:
    """Business logic for fraud investigation cases and audit tracking."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()

    def create_case(
        self,
        account_id: str,
        reason: Optional[str] = None,
        author: str = "Compliance Officer",
    ) -> Dict[str, Any]:
        """Open a new investigation case for an account."""
        account = self.db.get_account(account_id)
        if not account:
            raise KeyError(f"Cannot open case: Account '{account_id}' does not exist.")

        # Default reason if not provided
        if not reason:
            reasons = account.get("risk_reasons", [])
            reason = reasons[0] if reasons else f"Account risk score {account.get('graph_risk_score', 0):.1f} flagged for review"

        inv_id = self.db.create_investigation(
            account_id=account_id,
            reason=reason,
            author=author,
        )
        logger.info(f"Created investigation case {inv_id} for account {account_id}.")
        return self.get_case(inv_id)

    def get_case(self, investigation_id: str) -> Optional[Dict[str, Any]]:
        """Fetch investigation dossier including account profile and notes."""
        case = self.db.get_investigation(investigation_id)
        if not case:
            return None

        # Attach real-time account data
        acc = self.db.get_account(case["account_id"])
        case["account"] = acc
        return case

    def list_cases(
        self,
        status: Optional[str] = None,
        risk_category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List cases with optional filters."""
        return self.db.get_investigations(
            status=status,
            risk_category=risk_category,
            limit=limit,
            offset=offset,
        )

    def update_case_status(
        self,
        investigation_id: str,
        new_status: str,
        author: str = "Compliance Officer",
    ) -> Dict[str, Any]:
        """Update case status (New -> Under Review -> Escalated -> Closed)."""
        success = self.db.update_investigation_status(
            investigation_id=investigation_id,
            new_status=new_status,
            author=author,
        )
        if not success:
            raise KeyError(f"Investigation '{investigation_id}' not found.")
        return self.get_case(investigation_id)

    def add_note(
        self,
        investigation_id: str,
        note_text: str,
        author: str = "Compliance Officer",
    ) -> Dict[str, Any]:
        """Append investigator commentary to case audit trail."""
        if not note_text or not note_text.strip():
            raise ValueError("Note text cannot be empty.")
        return self.db.add_investigation_note(
            investigation_id=investigation_id,
            note_text=note_text.strip(),
            author=author,
        )
