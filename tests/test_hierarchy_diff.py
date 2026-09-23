from uuid import uuid4

from bomkit.diff.snapshot_diff import diff_snapshots
from bomkit.diff.change_events import classify_diff, ChangeEventType


class FakeDB:
    """
    Minimal database stub for testing nested BOM hierarchy handling.

    Hierarchy:

        TOP
        └── SUB_A × 2
            └── PCB_1 × 3

    Snapshot B changes PCB_1 from 3 -> 4.

    Expected effective quantity:

        Snapshot A: 2 * 3 = 6
        Snapshot B: 2 * 4 = 8
    """

    def __init__(self):
        self.top = uuid4()
        self.sub = uuid4()
        self.pcb = uuid4()

        self.snap_a = uuid4()
        self.snap_b = uuid4()

        self.items = {
            self.snap_a: [
                {
                    "bom_item_id": str(self.top),
                    "quantity": 1,
                    "attributes": {},
                    "checksum": "top",
                },
                {
                    "bom_item_id": str(self.sub),
                    "quantity": 2,
                    "attributes": {},
                    "checksum": "sub-a",
                },
                {
                    "bom_item_id": str(self.pcb),
                    "quantity": 3,
                    "attributes": {},
                    "checksum": "pcb-a",
                },
            ],
            self.snap_b: [
                {
                    "bom_item_id": str(self.top),
                    "quantity": 1,
                    "attributes": {},
                    "checksum": "top",
                },
                {
                    "bom_item_id": str(self.sub),
                    "quantity": 2,
                    "attributes": {},
                    "checksum": "sub-b",
                },
                {
                    "bom_item_id": str(self.pcb),
                    "quantity": 4,
                    "attributes": {},
                    "checksum": "pcb-b",
                },
            ],
        }

        self.details = {
            self.top: {
                "bom_item_id": self.top,
                "assembly_name": None,
                "part_name": "TOP",
                "part_id": uuid4(),
            },
            self.sub: {
                "bom_item_id": self.sub,
                "assembly_name": "TOP",
                "part_name": "SUB_A",
                "part_id": uuid4(),
            },
            self.pcb: {
                "bom_item_id": self.pcb,
                "assembly_name": "SUB_A",
                "part_name": "PCB_1",
                "part_id": uuid4(),
            },
        }

    def get_snapshot_items(self, snapshot_id):
        return self.items[snapshot_id]

    def get_bom_item_details(self, bom_item_ids):
        return {
            item_id: self.details[item_id]
            for item_id in bom_item_ids
        }


def test_nested_assembly_delta():
    db = FakeDB()

    diff = diff_snapshots(
        db.snap_a,
        db.snap_b,
        db,
    )

    # Only PCB_1 should be modified.
    assert diff.added_items == []
    assert diff.removed_items == []
    assert len(diff.modified_items) == 1

    modified = diff.modified_items[0]

    assert modified.bom_item_id == db.pcb

    # Full hierarchy path must be preserved.
    assert modified.assembly_path == "TOP/SUB_A/PCB_1"

    # Only one semantic change should be reported.
    assert len(modified.changes) == 1
    assert modified.changes[0].type == "QUANTITY_CHANGED"

    # Effective quantity:
    # Snapshot A = SUB_A(2) * PCB_1(3) = 6
    # Snapshot B = SUB_A(2) * PCB_1(4) = 8
    assert modified.changes[0].from_value == 6.0
    assert modified.changes[0].to_value == 8.0

    # Verify the change reaches the classification layer.
    result = classify_diff(diff)

    assert len(result.events) == 1

    event = result.events[0]

    assert event.event_type == ChangeEventType.QUANTITY_CHANGED

    # The hierarchy path should survive classification.
    assert event.delta is not None
    assert event.delta.assembly_path == "TOP/SUB_A/PCB_1"

    assert event.delta.quantity_from == 6.0
    assert event.delta.quantity_to == 8.0