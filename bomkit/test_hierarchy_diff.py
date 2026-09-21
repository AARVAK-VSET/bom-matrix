from uuid import uuid4
import pytest
from bomkit.diff.snapshot_diff import (
    DiffResult, SnapshotItemState, FieldChange, ModifiedItem, diff_snapshots
)
from bomkit.diff.change_events import classify_diff

class MockDatabaseClient:
    def __init__(self, snapshot_items_a, snapshot_items_b, bom_item_details):
        self.snapshot_items_a = snapshot_items_a
        self.snapshot_items_b = snapshot_items_b
        self.bom_item_details = bom_item_details
        
    def get_snapshot_items(self, snapshot_id):
        if str(snapshot_id) == "A":
            return self.snapshot_items_a
        return self.snapshot_items_b
        
    def get_bom_item_details(self, item_ids):
        return {item_id: self.bom_item_details[item_id] for item_id in item_ids if item_id in self.bom_item_details}

def test_nested_assembly_delta():
    # Build a 3-level BOM tree: TOP -> SUB_A -> PCB_1
    top_sub_id = uuid4()
    sub_pcb_id = uuid4()
    
    # In Snapshot A, SUB_A has quantity 2, PCB_1 has quantity 3. Total PCB_1 = 6.
    # In Snapshot B, PCB_1 quantity changes to 4. Total PCB_1 = 8.
    
    snapshot_items_a = [
        {"bom_item_id": str(top_sub_id), "quantity": 2, "attributes": {}, "checksum": "chk_top_a"},
        {"bom_item_id": str(sub_pcb_id), "quantity": 3, "attributes": {}, "checksum": "chk_sub_a"},
    ]
    
    snapshot_items_b = [
        {"bom_item_id": str(top_sub_id), "quantity": 2, "attributes": {}, "checksum": "chk_top_a"},
        {"bom_item_id": str(sub_pcb_id), "quantity": 4, "attributes": {}, "checksum": "chk_sub_b"},
    ]
    
    bom_item_details = {
        top_sub_id: {
            "assembly_name": "TOP",
            "part_name": "SUB_A",
            "part_id": uuid4()
        },
        sub_pcb_id: {
            "assembly_name": "SUB_A",
            "part_name": "PCB_1",
            "part_id": uuid4()
        }
    }
    
    db = MockDatabaseClient(snapshot_items_a, snapshot_items_b, bom_item_details)
    
    # Run diff
    diff_result = diff_snapshots("A", "B", db)
    
    # Classify
    classification = classify_diff(diff_result)
    
    # Verify exactly one change event whose assembly path is 'TOP/SUB_A/PCB_1'
    # and that the effective quantity was compared correctly.
    events = classification.events
    assert len(events) == 1
    
    event = events[0]
    assert getattr(event.delta, "assembly_path", None) == "TOP/SUB_A/PCB_1"
    
    # Effective quantity = node.qty * parent.qty
    # From: 3 * 2 = 6
    # To: 4 * 2 = 8
    assert event.delta.quantity_from == 6
    assert event.delta.quantity_to == 8
