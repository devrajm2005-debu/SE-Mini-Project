"""
Unit and Integration Tests for Pharmacy Expiry and Re-order Dispatch Engine
Problem Statement #15 | PES University SE Mini-Project
"""

import unittest
from datetime import date, timedelta
from src.engine import PharmacyEngine, MedicineBatch, PurchaseOrder


class TestPharmacyEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PharmacyEngine()
        self.today = date.today()

    # --- TC-BATCH: Batch Management Tests ---
    def test_tc_batch_01_add_valid_batch(self):
        """TC-BATCH-01: Successfully add a valid medicine batch with future expiry"""
        exp = self.today + timedelta(days=120)
        batch = self.engine.add_batch("B001", "MED01", "Paracetamol 500mg", 100, exp, 2.5, threshold=20)
        self.assertEqual(batch.batch_id, "B001")
        self.assertEqual(batch.quantity, 100)
        self.assertEqual(self.engine.get_total_stock("MED01"), 100)

    def test_tc_batch_02_reject_expired_batch_addition(self):
        """TC-BATCH-02: System must reject registering a batch with past/today expiry date"""
        past_exp = self.today - timedelta(days=10)
        with self.assertRaises(ValueError):
            self.engine.add_batch("B_EXP", "MED01", "Paracetamol 500mg", 50, past_exp, 2.5)

    def test_tc_batch_03_reject_zero_or_negative_quantity(self):
        """TC-BATCH-03: System must reject batch registration with zero or negative quantity"""
        future_exp = self.today + timedelta(days=60)
        with self.assertRaises(ValueError):
            self.engine.add_batch("B_ZERO", "MED01", "Paracetamol", 0, future_exp, 1.0)
        with self.assertRaises(ValueError):
            self.engine.add_batch("B_NEG", "MED01", "Paracetamol", -10, future_exp, 1.0)

    # --- TC-FEFO: FEFO Dispensing Tests ---
    def test_tc_fefo_01_prioritize_earliest_expiry_batch(self):
        """
        TC-FEFO-01: System must prioritize medicine batch with nearest expiry date.
        FR-001 Sample: Pass: Oldest valid batch selected first; Fail: Newer batch assigned.
        """
        exp_soon = self.today + timedelta(days=15)
        exp_later = self.today + timedelta(days=90)

        # Add later batch first, then sooner batch
        self.engine.add_batch("B_LATER", "MED01", "Amoxicillin", 50, exp_later, 5.0)
        self.engine.add_batch("B_SOON", "MED01", "Amoxicillin", 50, exp_soon, 5.0)

        # Dispense 20 units
        allocations = self.engine.dispense_fefo("MED01", 20)
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0]["batch_id"], "B_SOON")
        self.assertEqual(allocations[0]["units_dispensed"], 20)
        self.assertEqual(self.engine.batches["B_SOON"].quantity, 30)
        self.assertEqual(self.engine.batches["B_LATER"].quantity, 50)

    def test_tc_fefo_02_split_across_multiple_batches(self):
        """TC-FEFO-02: Dispense quantity split accurately across multiple batches when 1st batch is depleted"""
        exp_soon = self.today + timedelta(days=10)
        exp_later = self.today + timedelta(days=40)

        self.engine.add_batch("B1", "MED02", "Ibuprofen", 10, exp_soon, 3.0)
        self.engine.add_batch("B2", "MED02", "Ibuprofen", 25, exp_later, 3.0)

        # Request 15 units (needs 10 from B1, and 5 from B2)
        allocations = self.engine.dispense_fefo("MED02", 15)
        self.assertEqual(len(allocations), 2)
        self.assertEqual(allocations[0]["batch_id"], "B1")
        self.assertEqual(allocations[0]["units_dispensed"], 10)
        self.assertEqual(allocations[1]["batch_id"], "B2")
        self.assertEqual(allocations[1]["units_dispensed"], 5)
        self.assertEqual(self.engine.get_total_stock("MED02"), 20)

    def test_tc_fefo_03_insufficient_stock_exception(self):
        """TC-FEFO-03: System must raise ValueError if requested units exceed total available stock"""
        exp = self.today + timedelta(days=30)
        self.engine.add_batch("B1", "MED03", "Cetirizine", 10, exp, 1.5)
        with self.assertRaises(ValueError):
            self.engine.dispense_fefo("MED03", 25)

    # --- TC-EXP: Expiry Alert Engine Tests ---
    def test_tc_exp_01_detect_near_expiry_batches(self):
        """TC-EXP-01: Detect batches approaching expiry within 30 days"""
        exp_20d = self.today + timedelta(days=20)
        exp_80d = self.today + timedelta(days=80)

        self.engine.add_batch("B_EXP20", "MED04", "Metformin", 40, exp_20d, 4.0)
        self.engine.add_batch("B_EXP80", "MED04", "Metformin", 40, exp_80d, 4.0)

        alerts = self.engine.check_near_expiry(days_threshold=30)
        alert_batch_ids = [a["batch_id"] for a in alerts]
        self.assertIn("B_EXP20", alert_batch_ids)
        self.assertNotIn("B_EXP80", alert_batch_ids)

    # --- TC-REORD: Auto Re-order and Purchase Order Tests ---
    def test_tc_reord_01_auto_trigger_purchase_order_below_threshold(self):
        """TC-REORD-01: Automatically generate Purchase Order when stock drops below safety threshold"""
        exp = self.today + timedelta(days=60)
        # Threshold set to 20; initial stock 25
        self.engine.add_batch("B_RE", "MED05", "Azithromycin", 25, exp, 10.0, threshold=20)

        # Dispense 10 units -> stock drops to 15 (<= 20 threshold)
        self.engine.dispense_fefo("MED05", 10)

        self.assertEqual(len(self.engine.purchase_orders), 1)
        po = self.engine.purchase_orders[0]
        self.assertEqual(po.medicine_id, "MED05")
        self.assertEqual(po.reorder_quantity, 50)
        self.assertEqual(po.status, "DISPATCHED")

    def test_tc_reord_02_idempotent_reorder_no_duplicate_po(self):
        """TC-REORD-02: Do not flood multiple POs for the same medicine while one is already pending"""
        exp = self.today + timedelta(days=60)
        self.engine.add_batch("B_RE", "MED06", "Omeprazole", 25, exp, 5.0, threshold=20)

        # First dispense triggers PO
        self.engine.dispense_fefo("MED06", 10)
        self.assertEqual(len(self.engine.purchase_orders), 1)

        # Second dispense further depletes stock but should NOT trigger another duplicate PO
        self.engine.dispense_fefo("MED06", 2)
        self.assertEqual(len(self.engine.purchase_orders), 1)

    # --- TC-AUDIT: Audit Trail Verification ---
    def test_tc_audit_trail_logging(self):
        """TC-AUDIT-01: Verify audit log entries are generated for every state modification"""
        exp = self.today + timedelta(days=45)
        self.engine.add_batch("B_AUD", "MED07", "Aspirin", 50, exp, 2.0)
        self.engine.dispense_fefo("MED07", 10)

        actions = [log["action"] for log in self.engine.audit_logs]
        self.assertIn("BATCH_ADDED", actions)
        self.assertIn("DISPENSE", actions)


if __name__ == "__main__":
    unittest.main()
