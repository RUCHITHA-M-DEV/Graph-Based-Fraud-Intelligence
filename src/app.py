"""Flask Web Application & REST API Server for Graph-Based Fraud Intelligence.

Exposes REST APIs for:
- Dashboard KPIs & Charts
- Transaction Explorer & Filters
- Account Risk & Graph Insights
- Investigation Management & Notes
- Interactive Cytoscape.js Network Visualization
- PDF & CSV Report Exports
- System Monitoring & Health
"""

import io
import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
)
import pandas as pd

from src.config import (
    DEFAULT_GRAPH_EDGE_LIMIT,
    PROJECT_ROOT,
    PROCESSED_CSV_PATH,
)
from src.database import DatabaseManager
from src.graph_analyzer import GraphAnalyzer, TransactionGraph
from src.investigation import InvestigationManager
from src.reporter import ReportGenerator
from src.risk_scorer import UnifiedRiskEngine

logger = logging.getLogger("fraudgraph.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def create_app(db_manager: Optional[DatabaseManager] = None) -> Flask:
    """Application factory for Graph-Based Fraud Intelligence Flask application."""
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config["JSON_SORT_KEYS"] = False

    # Dependencies
    db = db_manager or DatabaseManager()
    investigation_mgr = InvestigationManager(db)
    reporter = ReportGenerator(db)
    risk_engine = UnifiedRiskEngine()

    # Cached in-memory graph analyzer state
    state: Dict[str, Any] = {
        "graph_analyzer": None,
        "accounts_cache": [],
        "cycles_cache": [],
        "rings_cache": [],
        "is_built": False,
        "start_time": time.time(),
    }

    def _ensure_graph_built() -> GraphAnalyzer:
        """Helper to ensure graph analyzer is loaded into memory."""
        if state["graph_analyzer"] is not None:
            return state["graph_analyzer"]

        csv_path = Path(PROCESSED_CSV_PATH)
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Processed dataset not found at {csv_path}. Please run detector pipeline first."
            )

        df = pd.read_csv(csv_path)
        tx_graph = TransactionGraph(df)
        analyzer = GraphAnalyzer(tx_graph)
        analysis = analyzer.run_full_analysis()

        # Persist to SQLite
        db.save_transactions(df)
        db.save_graph_analysis(
            accounts_data=analysis["accounts"],
            cycles_data=analysis["cycles"],
            rings_data=analysis["fraud_rings"],
        )

        state["graph_analyzer"] = analyzer
        state["accounts_cache"] = analysis["accounts"]
        state["cycles_cache"] = analysis["cycles"]
        state["rings_cache"] = analysis["fraud_rings"]
        state["is_built"] = True

        return analyzer

    # ---------------------------------------------------------------------
    # Error Handlers
    # ---------------------------------------------------------------------

    @app.errorhandler(404)
    def handle_not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Resource not found", "message": str(e)}), 404
        return render_template("base.html", page_title="Page Not Found"), 404

    @app.errorhandler(500)
    def handle_server_error(e):
        logger.error(f"Internal server error: {e}", exc_info=True)
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error", "message": str(e)}), 500
        return render_template("base.html", page_title="Server Error"), 500

    # ---------------------------------------------------------------------
    # Frontend Page Rendering Views
    # ---------------------------------------------------------------------

    @app.route("/", methods=["GET"])
    def view_dashboard():
        return render_template("dashboard.html", active_page="dashboard")

    @app.route("/transactions", methods=["GET"])
    def view_transactions():
        return render_template("transactions.html", active_page="transactions")

    @app.route("/investigation", methods=["GET"])
    @app.route("/account/<account_id>", methods=["GET"])
    def view_investigation(account_id: Optional[str] = None):
        target = account_id or request.args.get("account_id", "")
        return render_template("investigation.html", active_page="investigation", target_account=target)

    @app.route("/network", methods=["GET"])
    def view_network():
        return render_template("network.html", active_page="network")

    @app.route("/rings", methods=["GET"])
    def view_rings():
        return render_template("rings.html", active_page="rings")

    @app.route("/cases", methods=["GET"])
    def view_cases():
        return render_template("cases.html", active_page="cases")

    @app.route("/analytics", methods=["GET"])
    def view_analytics():
        return render_template("analytics.html", active_page="analytics")

    @app.route("/monitoring", methods=["GET"])
    def view_monitoring():
        return render_template("monitoring.html", active_page="monitoring")

    # ---------------------------------------------------------------------
    # Dashboard API Endpoints
    # ---------------------------------------------------------------------

    @app.route("/api/dashboard/overview", methods=["GET"])
    def api_dashboard_overview():
        try:
            overview = db.get_overview()
            return jsonify(overview), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch overview", "message": str(e)}), 500

    @app.route("/api/dashboard/charts", methods=["GET"])
    def api_dashboard_charts():
        try:
            charts_data = db.get_dashboard_charts()
            return jsonify(charts_data), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch charts data", "message": str(e)}), 500

    @app.route("/api/dashboard/recent-activity", methods=["GET"])
    def api_dashboard_recent_activity():
        try:
            recent_txs = db.get_recent_flagged_transactions(limit=6)
            rings = db.get_fraud_rings()[:3]
            cases = investigation_mgr.list_cases(limit=4)
            return jsonify({
                "recent_flagged_transactions": recent_txs,
                "recent_fraud_rings": rings,
                "recent_investigations": cases,
            }), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch recent activity", "message": str(e)}), 500

    # ---------------------------------------------------------------------
    # Risk Assessment API Endpoints
    # ---------------------------------------------------------------------

    @app.route("/api/risk/accounts", methods=["GET"])
    def api_risk_accounts():
        try:
            category = request.args.get("category", type=str)
            limit = request.args.get("limit", default=100, type=int)
            scores = db.get_risk_scores(risk_category=category, limit=limit)
            return jsonify({"count": len(scores), "accounts": scores}), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch risk scores", "message": str(e)}), 500

    @app.route("/api/risk/accounts/<account_id>", methods=["GET"])
    def api_risk_account_detail(account_id: str):
        try:
            account = db.get_account(account_id)
            if not account:
                return jsonify({"error": "Account not found", "message": f"Account '{account_id}' does not exist."}), 404
            neighbors = db.get_account_neighbors(account_id)
            return jsonify({"account": account, "neighbors": neighbors}), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch account detail", "message": str(e)}), 500

    @app.route("/api/risk/transactions", methods=["GET"])
    def api_risk_transactions():
        try:
            search = request.args.get("search", type=str)
            risk_cat = request.args.get("risk_category", type=str)
            min_amt = request.args.get("min_amount", type=float)
            max_amt = request.args.get("max_amount", type=float)
            is_suspicious_param = request.args.get("is_suspicious", type=str)
            is_susp = None
            if is_suspicious_param is not None and is_suspicious_param.lower() in ("true", "1"):
                is_susp = True
            elif is_suspicious_param is not None and is_suspicious_param.lower() in ("false", "0"):
                is_susp = False

            sort_by = request.args.get("sort_by", default="timestamp", type=str)
            sort_order = request.args.get("sort_order", default="DESC", type=str)
            limit = request.args.get("limit", default=50, type=int)
            offset = request.args.get("offset", default=0, type=int)

            result = db.get_transactions_paginated(
                search=search,
                risk_category=risk_cat,
                min_amount=min_amt,
                max_amount=max_amt,
                is_suspicious=is_susp,
                sort_by=sort_by,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
            return jsonify(result), 200
        except Exception as e:
            return jsonify({"error": "Failed to query transactions", "message": str(e)}), 500

    # ---------------------------------------------------------------------
    # Investigation Management API Endpoints
    # ---------------------------------------------------------------------

    @app.route("/api/investigations", methods=["GET"])
    def api_list_investigations():
        try:
            status = request.args.get("status", type=str)
            cat = request.args.get("risk_category", type=str)
            limit = request.args.get("limit", default=100, type=int)
            offset = request.args.get("offset", default=0, type=int)
            cases = investigation_mgr.list_cases(status=status, risk_category=cat, limit=limit, offset=offset)
            return jsonify({"count": len(cases), "cases": cases}), 200
        except Exception as e:
            return jsonify({"error": "Failed to list cases", "message": str(e)}), 500

    @app.route("/api/investigations", methods=["POST"])
    def api_create_investigation():
        try:
            data = request.get_json(silent=True) or {}
            acc_id = data.get("account_id")
            if not acc_id:
                return jsonify({"error": "Validation error", "message": "account_id is required"}), 400
            reason = data.get("reason", "Investigator manual case opening")
            author = data.get("author", "Compliance Officer")
            case = investigation_mgr.create_case(account_id=acc_id, reason=reason, author=author)
            return jsonify(case), 201
        except KeyError as ke:
            return jsonify({"error": "Not found", "message": str(ke)}), 404
        except Exception as e:
            return jsonify({"error": "Failed to create case", "message": str(e)}), 500

    @app.route("/api/investigations/<investigation_id>", methods=["GET"])
    def api_get_investigation(investigation_id: str):
        try:
            case = investigation_mgr.get_case(investigation_id)
            if not case:
                return jsonify({"error": "Not found", "message": f"Case '{investigation_id}' not found."}), 404
            return jsonify(case), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch case", "message": str(e)}), 500

    @app.route("/api/investigations/<investigation_id>", methods=["PUT"])
    def api_update_investigation(investigation_id: str):
        try:
            data = request.get_json(silent=True) or {}
            new_status = data.get("status")
            author = data.get("author", "Compliance Officer")
            if not new_status:
                return jsonify({"error": "Validation error", "message": "status is required"}), 400
            updated = investigation_mgr.update_case_status(investigation_id, new_status, author=author)
            return jsonify(updated), 200
        except ValueError as ve:
            return jsonify({"error": "Validation error", "message": str(ve)}), 400
        except KeyError as ke:
            return jsonify({"error": "Not found", "message": str(ke)}), 404
        except Exception as e:
            return jsonify({"error": "Failed to update case", "message": str(e)}), 500

    @app.route("/api/investigations/<investigation_id>/notes", methods=["POST"])
    def api_add_investigation_note(investigation_id: str):
        try:
            data = request.get_json(silent=True) or {}
            note_text = data.get("note_text")
            author = data.get("author", "Compliance Officer")
            if not note_text:
                return jsonify({"error": "Validation error", "message": "note_text cannot be empty"}), 400
            note = investigation_mgr.add_note(investigation_id, note_text, author=author)
            return jsonify(note), 201
        except KeyError as ke:
            return jsonify({"error": "Not found", "message": str(ke)}), 404
        except Exception as e:
            return jsonify({"error": "Failed to add note", "message": str(e)}), 500

    # ---------------------------------------------------------------------
    # Report Export API Endpoints
    # ---------------------------------------------------------------------

    @app.route("/api/reports/account/<account_id>/csv", methods=["GET"])
    def api_export_account_csv(account_id: str):
        try:
            csv_content = reporter.export_account_transactions_csv(account_id)
            return Response(
                csv_content,
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=account_{account_id}_transactions.csv"},
            )
        except Exception as e:
            return jsonify({"error": "Failed to export CSV", "message": str(e)}), 500

    @app.route("/api/reports/investigations/csv", methods=["GET"])
    def api_export_investigations_csv():
        try:
            csv_content = reporter.export_investigations_csv()
            return Response(
                csv_content,
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=investigations_ledger.csv"},
            )
        except Exception as e:
            return jsonify({"error": "Failed to export CSV", "message": str(e)}), 500

    @app.route("/api/reports/investigation/<investigation_id>/pdf", methods=["GET"])
    def api_export_investigation_pdf(investigation_id: str):
        try:
            pdf_bytes = reporter.generate_investigation_pdf(investigation_id)
            return send_file(
                io.BytesIO(pdf_bytes),
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f"investigation_{investigation_id}_dossier.pdf",
            )
        except KeyError as ke:
            return jsonify({"error": "Not found", "message": str(ke)}), 404
        except Exception as e:
            logger.error(f"Failed to generate PDF: {e}", exc_info=True)
            return jsonify({"error": "Failed to generate PDF", "message": str(e)}), 500

    # ---------------------------------------------------------------------
    # Graph Analysis Endpoints (Phase 3 Integration)
    # ---------------------------------------------------------------------

    @app.route("/api/graph/build", methods=["POST"])
    def build_graph():
        try:
            data = request.get_json(silent=True) or {}
            csv_path = data.get("csv_path", str(PROCESSED_CSV_PATH))
            min_amount = float(data.get("min_amount_cycle", 1000.0))
            max_cycle_len = int(data.get("max_cycle_length", 4))

            p = Path(csv_path)
            if not p.exists():
                return jsonify({"error": "File not found", "message": f"CSV not found at {p}"}), 404

            df = pd.read_csv(p)
            tx_graph = TransactionGraph(df)
            analyzer = GraphAnalyzer(tx_graph)
            analysis = analyzer.run_full_analysis(
                min_amount_cycle=min_amount,
                max_cycle_length=max_cycle_len,
            )

            # Persist to SQLite
            db.save_transactions(df)
            db.save_graph_analysis(
                accounts_data=analysis["accounts"],
                cycles_data=analysis["cycles"],
                rings_data=analysis["fraud_rings"],
            )

            state["graph_analyzer"] = analyzer
            state["accounts_cache"] = analysis["accounts"]
            state["cycles_cache"] = analysis["cycles"]
            state["rings_cache"] = analysis["fraud_rings"]
            state["is_built"] = True

            return jsonify({
                "message": "Graph built and analyzed successfully",
                "metrics": analysis["metrics"],
                "total_accounts": len(analysis["accounts"]),
                "detected_cycles": len(analysis["cycles"]),
                "detected_fraud_rings": len(analysis["fraud_rings"]),
            }), 201
        except Exception as e:
            logger.error(f"Build graph error: {e}", exc_info=True)
            return jsonify({"error": "Failed to build graph", "message": str(e)}), 500

    @app.route("/api/graph/overview", methods=["GET"])
    def get_graph_overview():
        try:
            overview = db.get_overview()
            return jsonify(overview), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch overview", "message": str(e)}), 500

    @app.route("/api/graph/account/<account_id>", methods=["GET"])
    def get_account_profile(account_id: str):
        try:
            account = db.get_account(account_id)
            if not account:
                return jsonify({"error": "Account not found", "message": f"Account '{account_id}' does not exist."}), 404
            return jsonify(account), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch account", "message": str(e)}), 500

    @app.route("/api/graph/neighbors/<account_id>", methods=["GET"])
    def get_neighbors(account_id: str):
        try:
            account = db.get_account(account_id)
            if not account:
                return jsonify({"error": "Account not found", "message": f"Account '{account_id}' does not exist."}), 404
            neighbors = db.get_account_neighbors(account_id)
            return jsonify(neighbors), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch neighbors", "message": str(e)}), 500

    @app.route("/api/graph/cycles", methods=["GET"])
    def get_cycles():
        try:
            min_len = request.args.get("min_length", type=int)
            max_len = request.args.get("max_length", type=int)
            cycles = db.get_cycles(min_length=min_len, max_length=max_len)
            return jsonify({"count": len(cycles), "cycles": cycles}), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch cycles", "message": str(e)}), 500

    @app.route("/api/graph/communities", methods=["GET"])
    def get_communities():
        try:
            communities = db.get_communities()
            return jsonify({"count": len(communities), "communities": communities}), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch communities", "message": str(e)}), 500

    @app.route("/api/graph/fraud-rings", methods=["GET"])
    def get_fraud_rings():
        try:
            rings = db.get_fraud_rings()
            return jsonify({"count": len(rings), "fraud_rings": rings}), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch fraud rings", "message": str(e)}), 500

    @app.route("/api/graph/risk-scores", methods=["GET"])
    def get_risk_scores():
        try:
            category = request.args.get("category", type=str)
            limit = request.args.get("limit", default=100, type=int)
            scores = db.get_risk_scores(risk_category=category, limit=limit)
            return jsonify({"count": len(scores), "risk_scores": scores}), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch risk scores", "message": str(e)}), 500

    @app.route("/api/graph/visualization", methods=["GET"])
    def get_visualization():
        try:
            analyzer = _ensure_graph_built()

            filter_account = request.args.get("account_id", type=str)
            min_amount = request.args.get("min_amount", type=float)
            risk_category = request.args.get("risk_category", type=str)
            only_suspicious = request.args.get("only_suspicious", default="false").lower() in ("true", "1")
            limit = request.args.get("limit", default=DEFAULT_GRAPH_EDGE_LIMIT, type=int)

            payload = analyzer.export_cytoscape_payload(
                account_scores=state["accounts_cache"],
                cycles=state["cycles_cache"],
                filter_account=filter_account,
                min_amount=min_amount,
                risk_category=risk_category,
                only_suspicious=only_suspicious,
                limit=limit,
            )
            return jsonify(payload), 200
        except Exception as e:
            logger.error(f"Visualization error: {e}", exc_info=True)
            return jsonify({"error": "Failed to export visualization", "message": str(e)}), 500

    # ---------------------------------------------------------------------
    # System Monitoring Endpoints
    # ---------------------------------------------------------------------

    @app.route("/api/health", methods=["GET"])
    @app.route("/api/system/health", methods=["GET"])
    def api_system_health():
        uptime = round(time.time() - state["start_time"], 1)
        db_ok = True
        try:
            with db.get_connection() as conn:
                conn.execute("SELECT 1;").fetchone()
        except Exception:
            db_ok = False

        return jsonify({
            "status": "healthy" if db_ok else "degraded",
            "uptime_seconds": uptime,
            "database_connected": db_ok,
            "graph_cached": state["is_built"],
            "model_ready": True,
        }), 200

    @app.route("/api/system/statistics", methods=["GET"])
    def api_system_statistics():
        try:
            overview = db.get_overview()
            return jsonify({
                "overview": overview,
                "dataset_path": str(PROCESSED_CSV_PATH),
                "graph_cache_nodes": len(state["accounts_cache"]),
                "graph_cache_cycles": len(state["cycles_cache"]),
                "graph_cache_rings": len(state["rings_cache"]),
            }), 200
        except Exception as e:
            return jsonify({"error": "Failed to fetch stats", "message": str(e)}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    logger.info("Starting Graph-Based Fraud Intelligence web server on port 5000...")
    app.run(host="127.0.0.1", port=5000, debug=True)
