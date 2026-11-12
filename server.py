"""
MediStock Web Server & REST API Gateway
Pharmacy Expiry and Re-order Dispatch Engine (Problem Statement #15)
PES University - Dept. of CSE
"""

import http.server
import socketserver
import json
import os
import sys
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs

# Add root directory to sys.path so we can import src.engine
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.engine import PharmacyEngine, MedicineBatch

# Global singleton engine instance initialized with sample data
engine = PharmacyEngine()
engine.seed_sample_data()

PORT = int(os.environ.get("PORT", 8000))
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class PharmacyRequestHandler(http.server.BaseHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS and disable caching for active development
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.serve_file(os.path.join(WEB_DIR, "index.html"), "text/html")
        elif path == "/api/batches":
            batches = [b.to_dict() for b in engine.batches.values()]
            self.send_json_response(batches)
        elif path == "/api/stock":
            summary = engine.get_stock_summary()
            self.send_json_response(summary)
        elif path == "/api/alerts":
            alerts = engine.check_near_expiry(days_threshold=30)
            self.send_json_response(alerts)
        elif path == "/api/orders":
            orders = [po.to_dict() for po in reversed(engine.purchase_orders)]
            self.send_json_response(orders)
        elif path == "/api/audit":
            self.send_json_response(list(reversed(engine.audit_logs)))
        elif path == "/api/stats":
            unique_meds = len(set(b.medicine_id for b in engine.batches.values()))
            total_units = sum(b.quantity for b in engine.batches.values() if not b.is_expired())
            near_exp = len(engine.check_near_expiry(30))
            stats = {
                "total_skus": unique_meds,
                "total_units": total_units,
                "active_batches": len(engine.batches),
                "near_expiry_count": near_exp,
                "pending_orders": len(engine.purchase_orders)
            }
            self.send_json_response(stats)
        else:
            self.send_error(404, "Endpoint not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except json.JSONDecodeError:
            self.send_json_response({"error": "Invalid JSON payload"}, status=400)
            return

        if path == "/api/batches":
            try:
                batch_id = payload.get("batch_id")
                med_id = payload.get("medicine_id")
                med_name = payload.get("medicine_name")
                qty = int(payload.get("quantity", 0))
                exp_str = payload.get("expiry_date")
                cost = float(payload.get("purchase_cost", 0.0))
                thresh = int(payload.get("threshold", 20))

                if not (batch_id and med_id and med_name and exp_str):
                    self.send_json_response({"error": "Missing required fields"}, status=400)
                    return

                exp_date = date.fromisoformat(exp_str)
                batch = engine.add_batch(batch_id, med_id, med_name, qty, exp_date, cost, thresh)
                self.send_json_response({"message": "Batch registered successfully", "batch": batch.to_dict()}, status=201)
            except Exception as e:
                self.send_json_response({"error": str(e)}, status=400)

        elif path == "/api/dispense":
            try:
                med_id = payload.get("medicine_id")
                qty = int(payload.get("quantity", 0))

                if not med_id or qty <= 0:
                    self.send_json_response({"error": "Valid medicine_id and positive quantity are required"}, status=400)
                    return

                allocations = engine.dispense_fefo(med_id, qty)
                triggered_po = engine.check_and_trigger_reorder(med_id)

                response_data = {
                    "message": "FEFO Dispensing completed",
                    "medicine_id": med_id,
                    "units_requested": qty,
                    "allocations": allocations,
                    "purchase_order_triggered": triggered_po.to_dict() if triggered_po else None
                }
                self.send_json_response(response_data, status=200)
            except Exception as e:
                self.send_json_response({"error": str(e)}, status=400)
        else:
            self.send_error(404, "Endpoint not found")

    def serve_file(self, file_path, content_type):
        if not os.path.exists(file_path):
            self.send_error(404, "File not found")
            return
        with open(file_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json_response(self, data, status=200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Override to suppress default stdout noise, keeping output clean
        return


def run_server():
    print(f"================================================================")
    print(f" MediStock Web Server - Pharmacy FEFO & Re-Order Dispatch Engine")
    print(f" Running locally at: http://localhost:{PORT}")
    print(f" Open your browser to access the pharmacy stock and dispenser")
    print(f"================================================================")
    with socketserver.TCPServer(("", PORT), PharmacyRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down MediStock web server...")


if __name__ == "__main__":
    run_server()
