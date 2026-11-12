"""
Pharmacy Expiry and Re-order Dispatch Engine
Problem Statement #15 | Healthcare and Telemedicine Track
Author: Devraj M (devrajm2005)
"""

from datetime import datetime, timezone, date, timedelta
from typing import List, Dict, Optional, Tuple
import uuid


class MedicineBatch:
    def __init__(self, batch_id: str, medicine_id: str, medicine_name: str, 
                 quantity: int, expiry_date: date, purchase_cost: float, threshold: int = 15):
        self.batch_id = batch_id
        self.medicine_id = medicine_id
        self.medicine_name = medicine_name
        self.quantity = quantity
        self.expiry_date = expiry_date
        self.purchase_cost = purchase_cost
        self.threshold = threshold
        self.status = "ACTIVE"

    def is_expired(self, current_date: Optional[date] = None) -> bool:
        today = current_date or date.today()
        return self.expiry_date <= today

    def days_to_expiry(self, current_date: Optional[date] = None) -> int:
        today = current_date or date.today()
        return (self.expiry_date - today).days

    def to_dict(self):
        today = date.today()
        days_left = self.days_to_expiry(today)
        computed_status = "EXPIRED" if days_left <= 0 else ("NEAR_EXPIRY" if days_left <= 30 else self.status)
        return {
            "batch_id": self.batch_id,
            "medicine_id": self.medicine_id,
            "medicine_name": self.medicine_name,
            "quantity": self.quantity,
            "expiry_date": self.expiry_date.isoformat(),
            "days_to_expiry": days_left,
            "purchase_cost": self.purchase_cost,
            "threshold": self.threshold,
            "status": computed_status
        }


class PurchaseOrder:
    def __init__(self, po_id: str, medicine_id: str, medicine_name: str, 
                 reorder_quantity: int, supplier_id: str):
        self.po_id = po_id
        self.medicine_id = medicine_id
        self.medicine_name = medicine_name
        self.reorder_quantity = reorder_quantity
        self.supplier_id = supplier_id
        self.created_at = datetime.now(timezone.utc)
        self.status = "DISPATCHED"

    def to_dict(self):
        return {
            "po_id": self.po_id,
            "medicine_id": self.medicine_id,
            "medicine_name": self.medicine_name,
            "reorder_quantity": self.reorder_quantity,
            "supplier_id": self.supplier_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "status": self.status
        }


class PharmacyEngine:
    def __init__(self):
        self.batches: Dict[str, MedicineBatch] = {}
        self.purchase_orders: List[PurchaseOrder] = []
        self.audit_logs: List[Dict] = []
        self.safety_thresholds: Dict[str, int] = {}
        self.default_reorder_qty = 50

    def add_batch(self, batch_id: str, medicine_id: str, medicine_name: str, 
                  quantity: int, expiry_date: date, purchase_cost: float, 
                  threshold: int = 20) -> MedicineBatch:
        if expiry_date <= date.today():
            raise ValueError("Cannot register medicine batch with past or current-day expiry date")
        if quantity <= 0:
            raise ValueError("Batch quantity must be greater than zero")
        
        batch = MedicineBatch(batch_id, medicine_id, medicine_name, quantity, expiry_date, purchase_cost, threshold)
        self.batches[batch_id] = batch
        self.safety_thresholds[medicine_id] = threshold
        self._log_audit("BATCH_ADDED", f"Batch {batch_id} added for {medicine_name} (Qty: {quantity}, Expiry: {expiry_date})")
        return batch

    def get_active_batches_fefo(self, medicine_id: str, current_date: Optional[date] = None) -> List[MedicineBatch]:
        today = current_date or date.today()
        valid_batches = [
            b for b in self.batches.values()
            if b.medicine_id == medicine_id and b.quantity > 0 and not b.is_expired(today) and b.status in ("ACTIVE", "NEAR_EXPIRY")
        ]
        # FEFO order: sort ascending by expiry_date
        return sorted(valid_batches, key=lambda b: b.expiry_date)

    def get_total_stock(self, medicine_id: str, current_date: Optional[date] = None) -> int:
        return sum(b.quantity for b in self.get_active_batches_fefo(medicine_id, current_date))

    def dispense_fefo(self, medicine_id: str, requested_quantity: int, current_date: Optional[date] = None) -> List[Dict]:
        """
        Enforces First-Expired-First-Out dispensing.
        Splits request across batches if necessary.
        Raises ValueError if insufficient stock.
        """
        if requested_quantity <= 0:
            raise ValueError("Requested quantity must be positive")

        available_batches = self.get_active_batches_fefo(medicine_id, current_date)
        total_avail = sum(b.quantity for b in available_batches)
        if total_avail < requested_quantity:
            raise ValueError(f"Insufficient stock for {medicine_id}. Requested: {requested_quantity}, Available: {total_avail}")

        allocated = []
        remaining_needed = requested_quantity

        for batch in available_batches:
            if remaining_needed == 0:
                break

            deduct = min(batch.quantity, remaining_needed)
            batch.quantity -= deduct
            remaining_needed -= deduct
            allocated.append({
                "batch_id": batch.batch_id,
                "expiry_date": batch.expiry_date.isoformat(),
                "units_dispensed": deduct,
                "remaining_in_batch": batch.quantity
            })
            self._log_audit("DISPENSE", f"Dispensed {deduct} units from batch {batch.batch_id} (Expiry: {batch.expiry_date})")

        # Check reorder condition
        self.check_and_trigger_reorder(medicine_id, current_date)
        return allocated

    def check_near_expiry(self, days_threshold: int = 30, current_date: Optional[date] = None) -> List[Dict]:
        today = current_date or date.today()
        alerts = []
        for batch in self.batches.values():
            if batch.quantity > 0 and not batch.is_expired(today):
                days = (batch.expiry_date - today).days
                if days <= days_threshold:
                    batch.status = "NEAR_EXPIRY"
                    alerts.append({
                        "batch_id": batch.batch_id,
                        "medicine_name": batch.medicine_name,
                        "days_remaining": days,
                        "quantity": batch.quantity,
                        "expiry_date": batch.expiry_date.isoformat()
                    })
                    self._log_audit("EXPIRY_ALERT", f"Batch {batch.batch_id} has only {days} days to expiry")
        return alerts

    def check_and_trigger_reorder(self, medicine_id: str, current_date: Optional[date] = None) -> Optional[PurchaseOrder]:
        total_stock = self.get_total_stock(medicine_id, current_date)
        threshold = self.safety_thresholds.get(medicine_id, 20)

        if total_stock <= threshold:
            # Check if pending PO already exists
            pending = any(po.medicine_id == medicine_id and po.status == "DISPATCHED" for po in self.purchase_orders)
            if not pending:
                po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
                med_name = next((b.medicine_name for b in self.batches.values() if b.medicine_id == medicine_id), "Unknown")
                po = PurchaseOrder(po_id, medicine_id, med_name, self.default_reorder_qty, "SUPPLIER-MED-01")
                self.purchase_orders.append(po)
                self._log_audit("AUTO_REORDER", f"Dispatched {po_id} for {med_name} (Reorder Qty: {self.default_reorder_qty})")
                return po
        return None

    def get_stock_summary(self) -> List[Dict]:
        """Returns aggregated summary for all unique medicines"""
        medicines = {}
        for b in self.batches.values():
            if b.medicine_id not in medicines:
                medicines[b.medicine_id] = {
                    "medicine_id": b.medicine_id,
                    "medicine_name": b.medicine_name,
                    "threshold": self.safety_thresholds.get(b.medicine_id, 20),
                    "batches_count": 0,
                    "total_stock": 0,
                    "earliest_expiry": None,
                    "status": "NORMAL"
                }
            m = medicines[b.medicine_id]
            m["batches_count"] += 1
            if not b.is_expired() and b.quantity > 0:
                m["total_stock"] += b.quantity
                if m["earliest_expiry"] is None or b.expiry_date < m["earliest_expiry"]:
                    m["earliest_expiry"] = b.expiry_date

        summary = []
        for m in medicines.values():
            earliest = m["earliest_expiry"].isoformat() if m["earliest_expiry"] else "N/A"
            status = "CRITICAL_LOW" if m["total_stock"] <= m["threshold"] else "ADEQUATE"
            summary.append({
                "medicine_id": m["medicine_id"],
                "medicine_name": m["medicine_name"],
                "threshold": m["threshold"],
                "batches_count": m["batches_count"],
                "total_stock": m["total_stock"],
                "earliest_expiry": earliest,
                "status": status
            })
        return sorted(summary, key=lambda x: x["medicine_name"])

    def seed_sample_data(self):
        """Populate realistic pharmacy stock for demonstration"""
        today = date.today()
        # Medicine 1: Paracetamol 500mg (2 batches: one near expiry 14 days, one 90 days)
        self.add_batch("B-PAR-01", "MED-001", "Paracetamol 500mg", 40, today + timedelta(days=14), 2.5, threshold=30)
        self.add_batch("B-PAR-02", "MED-001", "Paracetamol 500mg", 100, today + timedelta(days=95), 2.5, threshold=30)

        # Medicine 2: Amoxicillin 250mg (earliest 25 days)
        self.add_batch("B-AMX-01", "MED-002", "Amoxicillin 250mg", 25, today + timedelta(days=25), 4.75, threshold=20)
        self.add_batch("B-AMX-02", "MED-002", "Amoxicillin 250mg", 60, today + timedelta(days=180), 4.75, threshold=20)

        # Medicine 3: Ibuprofen 400mg (low stock -> trigger test)
        self.add_batch("B-IBU-01", "MED-003", "Ibuprofen 400mg", 18, today + timedelta(days=45), 3.20, threshold=20)

        # Medicine 4: Azithromycin 500mg
        self.add_batch("B-AZI-01", "MED-004", "Azithromycin 500mg", 50, today + timedelta(days=120), 12.00, threshold=15)

        # Medicine 5: Metformin 500mg (two batches for FEFO split demonstration)
        self.add_batch("B-MET-01", "MED-005", "Metformin 500mg", 15, today + timedelta(days=28), 1.80, threshold=25)
        self.add_batch("B-MET-02", "MED-005", "Metformin 500mg", 50, today + timedelta(days=150), 1.80, threshold=25)

        # Run initial near expiry detection
        self.check_near_expiry(30)
        # Check if any initial item triggers reorder
        for med_id in ["MED-001", "MED-002", "MED-003", "MED-004", "MED-005"]:
            self.check_and_trigger_reorder(med_id)

    def _log_audit(self, action: str, details: str):
        self.audit_logs.append({
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "action": action,
            "details": details
        })
