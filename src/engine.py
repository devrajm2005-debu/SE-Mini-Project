"""
Pharmacy Expiry and Re-order Dispatch Engine
Problem Statement #15 | Healthcare and Telemedicine Track
Author: Devraj M (devrajm2005)
"""

from datetime import datetime, date, timedelta
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
        return {
            "batch_id": self.batch_id,
            "medicine_id": self.medicine_id,
            "medicine_name": self.medicine_name,
            "quantity": self.quantity,
            "expiry_date": self.expiry_date.isoformat(),
            "purchase_cost": self.purchase_cost,
            "status": self.status
        }


class PurchaseOrder:
    def __init__(self, po_id: str, medicine_id: str, medicine_name: str, 
                 reorder_quantity: int, supplier_id: str):
        self.po_id = po_id
        self.medicine_id = medicine_id
        self.medicine_name = medicine_name
        self.reorder_quantity = reorder_quantity
        self.supplier_id = supplier_id
        self.created_at = datetime.utcnow()
        self.status = "DISPATCHED"


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
        self._log_audit("BATCH_ADDED", f"Batch {batch_id} added for {medicine_name} (Qty: {quantity})")
        return batch

    def get_active_batches_fefo(self, medicine_id: str, current_date: Optional[date] = None) -> List[MedicineBatch]:
        today = current_date or date.today()
        valid_batches = [
            b for b in self.batches.values()
            if b.medicine_id == medicine_id and b.quantity > 0 and not b.is_expired(today) and b.status == "ACTIVE"
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
                        "quantity": batch.quantity
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

    def _log_audit(self, action: str, details: str):
        self.audit_logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "details": details
        })
