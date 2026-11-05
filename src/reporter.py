"""Report Generation Service for Graph-Based Fraud Intelligence.

Generates:
1. Exportable CSV transaction ledgers and case files
2. Professional PDF investigation dossiers using ReportLab
"""

from datetime import datetime
import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.database import DatabaseManager

logger = logging.getLogger("fraudgraph.reporter")


class ReportGenerator:
    """Produces CSV data exports and PDF investigation summaries."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()

    # ---------------------------------------------------------------------
    # CSV Exports
    # ---------------------------------------------------------------------

    def export_account_transactions_csv(self, account_id: str) -> str:
        """Export all transactions involving given account as CSV string."""
        with self.db.get_connection() as conn:
            query = """
            SELECT transaction_id, sender_account, receiver_account, amount, timestamp,
                   transaction_type, rule_flagged, rule_severity_score, iso_forest_pred,
                   iso_forest_anomaly_score, rf_fraud_pred, rf_fraud_probability
            FROM transactions
            WHERE sender_account = ? OR receiver_account = ?
            ORDER BY timestamp DESC;
            """
            df = pd.read_sql_query(query, conn, params=(account_id, account_id))

        if df.empty:
            return "transaction_id,sender_account,receiver_account,amount,timestamp\n"
        return df.to_csv(index=False)

    def export_investigations_csv(self) -> str:
        """Export all investigation cases as CSV string."""
        cases = self.db.get_investigations(limit=1000)
        if not cases:
            return "investigation_id,account_id,risk_score,risk_category,status,reason,created_at\n"
        df = pd.DataFrame(cases)
        return df.to_csv(index=False)

    # ---------------------------------------------------------------------
    # PDF Dossier Generation
    # ---------------------------------------------------------------------

    def generate_investigation_pdf(
        self,
        investigation_id: str,
        output_stream: Optional[Union[io.BytesIO, Path, str]] = None,
    ) -> bytes:
        """
        Generate an executive investigation PDF dossier.
        """
        case = self.db.get_investigation(investigation_id)
        if not case:
            raise KeyError(f"Investigation '{investigation_id}' does not exist.")

        account_id = case["account_id"]
        account = self.db.get_account(account_id) or {}
        neighbors = self.db.get_account_neighbors(account_id)

        # Output buffer
        buffer = io.BytesIO() if output_stream is None else output_stream

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        styles = getSampleStyleSheet()

        # Custom Palette
        PRIMARY_COLOR = colors.HexColor("#0f172a")    # Deep navy slate
        ACCENT_COLOR = colors.HexColor("#1e293b")     # Border tone
        TEXT_LIGHT = colors.HexColor("#64748b")       # Subdued slate

        risk_cat = case.get("risk_category", "Medium")
        if risk_cat == "Critical":
            STATUS_COLOR = colors.HexColor("#ef4444")
        elif risk_cat == "High":
            STATUS_COLOR = colors.HexColor("#f97316")
        elif risk_cat == "Medium":
            STATUS_COLOR = colors.HexColor("#f59e0b")
        else:
            STATUS_COLOR = colors.HexColor("#10b981")

        # Typography
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=PRIMARY_COLOR,
        )
        subtitle_style = ParagraphStyle(
            "SubTitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=TEXT_LIGHT,
        )
        h2_style = ParagraphStyle(
            "Heading2",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=PRIMARY_COLOR,
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#1e293b"),
        )
        meta_label = ParagraphStyle(
            "MetaLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=TEXT_LIGHT,
        )

        story = []

        # 1. Header Banner
        header_data = [
            [
                Paragraph("<b>GRAPH-BASED FRAUD INTELLIGENCE</b>", title_style),
                Paragraph(f"<b>STATUS: {case.get('status', 'New').upper()}</b>", ParagraphStyle(
                    "StatusBadge", fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=STATUS_COLOR, alignment=2
                )),
            ],
            [
                Paragraph(f"Official Investigation Case Dossier &bull; Case Ref: <b>{investigation_id}</b>", subtitle_style),
                Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}", ParagraphStyle(
                    "DateBadge", fontName="Helvetica", fontSize=8, leading=10, textColor=TEXT_LIGHT, alignment=2
                )),
            ]
        ]
        header_table = Table(header_data, colWidths=[4.0 * inch, 3.25 * inch])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY_COLOR, spaceAfter=14))

        # 2. Case Overview Summary Cards
        score = case.get("risk_score", 0.0)
        summary_data = [
            [
                Paragraph("Target Account", meta_label),
                Paragraph("Unified Risk Score", meta_label),
                Paragraph("Risk Classification", meta_label),
                Paragraph("Opened On", meta_label),
            ],
            [
                Paragraph(f"<b>{account_id}</b>", body_style),
                Paragraph(f"<b>{score:.1f} / 100</b>", ParagraphStyle("ScoreBig", fontName="Helvetica-Bold", fontSize=14, leading=16, textColor=STATUS_COLOR)),
                Paragraph(f"<b>{risk_cat.upper()}</b>", ParagraphStyle("CatBig", fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=STATUS_COLOR)),
                Paragraph(f"{case.get('created_at', '')[:10]}", body_style),
            ]
        ]
        summary_table = Table(summary_data, colWidths=[1.8 * inch, 1.8 * inch, 1.8 * inch, 1.85 * inch])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 14))

        # 3. Account Topological Profile
        story.append(Paragraph("Account Topological Profile & KYC Metrics", h2_style))
        story.append(Spacer(1, 6))

        in_cnt = account.get("in_degree", 0)
        out_cnt = account.get("out_degree", 0)
        sent = account.get("total_sent", 0.0)
        recv = account.get("total_received", 0.0)
        pr = account.get("pagerank", 0.0)
        comm = account.get("community_id", 0)

        profile_data = [
            [Paragraph("Total Capital Sent:", meta_label), Paragraph(f"${sent:,.2f}", body_style),
             Paragraph("Out-Degree (Dispersal):", meta_label), Paragraph(str(out_cnt), body_style)],
            [Paragraph("Total Capital Received:", meta_label), Paragraph(f"${recv:,.2f}", body_style),
             Paragraph("In-Degree (Aggregation):", meta_label), Paragraph(str(in_cnt), body_style)],
            [Paragraph("Net Capital Flow:", meta_label), Paragraph(f"${(recv - sent):,.2f}", body_style),
             Paragraph("PageRank Centrality:", meta_label), Paragraph(f"{pr:.6f}", body_style)],
            [Paragraph("Community Cluster:", meta_label), Paragraph(f"Cluster #{comm}", body_style),
             Paragraph("Laundering Cycle Member:", meta_label), Paragraph("YES" if account.get("is_in_cycle") else "NO", body_style)],
        ]
        profile_table = Table(profile_data, colWidths=[1.8 * inch, 1.8 * inch, 1.8 * inch, 1.85 * inch])
        profile_table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(profile_table)
        story.append(Spacer(1, 14))

        # 4. Triggered Risk Reasons & Explanations
        story.append(Paragraph("Suspicious Indicator Attribution & Rationale", h2_style))
        story.append(Spacer(1, 6))

        reasons = account.get("risk_reasons", [])
        if not reasons:
            reasons = [case.get("reason", "Activity deviation from normal baseline")]

        reason_items = [[Paragraph(f"&bull; {r}", body_style)] for r in reasons]
        reason_table = Table(reason_items, colWidths=[7.25 * inch])
        reason_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff7ed") if risk_cat in ("Critical", "High") else colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#fed7aa") if risk_cat in ("Critical", "High") else colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(reason_table)
        story.append(Spacer(1, 14))

        # 5. Connected Counterparties Summary
        story.append(Paragraph("Direct Connected Counterparties (Ego Network)", h2_style))
        story.append(Spacer(1, 6))

        out_neighbors = neighbors.get("outgoing_neighbors", [])[:5]
        in_neighbors = neighbors.get("incoming_neighbors", [])[:5]

        cp_data = [
            [Paragraph("Counterparty Account", meta_label), Paragraph("Direction", meta_label), Paragraph("Transfers", meta_label), Paragraph("Total Volume", meta_label)]
        ]
        for n in out_neighbors:
            cp_data.append([
                Paragraph(n["receiver_account"], body_style),
                Paragraph("Outbound (Sent to)", body_style),
                Paragraph(str(n["count"]), body_style),
                Paragraph(f"${n['volume']:,.2f}", body_style)
            ])
        for n in in_neighbors:
            cp_data.append([
                Paragraph(n["sender_account"], body_style),
                Paragraph("Inbound (Received from)", body_style),
                Paragraph(str(n["count"]), body_style),
                Paragraph(f"${n['volume']:,.2f}", body_style)
            ])

        if len(cp_data) == 1:
            cp_data.append([Paragraph("No active counterparties recorded.", body_style), Paragraph("-", body_style), Paragraph("-", body_style), Paragraph("-", body_style)])

        cp_table = Table(cp_data, colWidths=[2.2 * inch, 1.8 * inch, 1.2 * inch, 2.05 * inch])
        cp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(cp_table)
        story.append(Spacer(1, 14))

        # 6. Investigation Notes & Case History
        story.append(Paragraph("Case Activity Log & Compliance Notes", h2_style))
        story.append(Spacer(1, 6))

        notes = case.get("notes", [])
        if notes:
            note_data = [[Paragraph("Timestamp", meta_label), Paragraph("Author", meta_label), Paragraph("Commentary", meta_label)]]
            for n in notes:
                note_data.append([
                    Paragraph(n.get("created_at", "")[:19], body_style),
                    Paragraph(n.get("author", "Officer"), body_style),
                    Paragraph(n.get("note_text", ""), body_style),
                ])
            note_table = Table(note_data, colWidths=[1.8 * inch, 1.5 * inch, 3.95 * inch])
            note_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(note_table)
        else:
            story.append(Paragraph("No investigator notes recorded yet.", subtitle_style))

        story.append(Spacer(1, 20))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=8))
        story.append(Paragraph(
            "<b>CONFIDENTIAL FINANCIAL INTELLIGENCE DOSSIER</b> &bull; Prototype for algorithmic research & portfolio demonstration. Synthetic data.",
            ParagraphStyle("Footer", fontName="Helvetica", fontSize=7.5, leading=10, textColor=TEXT_LIGHT, alignment=1)
        ))

        doc.build(story)

        if isinstance(buffer, io.BytesIO):
            return buffer.getvalue()
        return b""
