import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from bomkit.ingest.snapshot_ingest import (
    NormalizedRow,
    ingest_bom_snapshot,
)


def test_partial_failure_cleanup():
    db = MagicMock()

    org_id = uuid4()
    assembly_id = uuid4()
    part_id = uuid4()
    bom_item_id = uuid4()
    snapshot_id = uuid4()

    # Mock database operations
    db.get_or_create_organization.return_value = org_id
    db.get_or_create_assembly.return_value = assembly_id

    db.find_similar_parts.return_value = []
    db.create_part.return_value = part_id

    db.find_similar_bom_items.return_value = []
    db.create_bom_item.return_value = bom_item_id

    db.create_snapshot.return_value = snapshot_id

    # Simulate failure while inserting the snapshot item
    db.insert_snapshot_item.side_effect = RuntimeError(
        "simulated snapshot item insert failure"
    )

    row = NormalizedRow(
        part_name="TEST-001",
        quantity=1,
        attributes={
            "manufacturer": "Test Manufacturer",
            "description": "Test component",
            "package": "0603",
        },
        context={
            "reference_designator": "R1",
            "supplier": "Test Supplier",
        },
        row_index=1,
    )

    # The original exception must be re-raised
    with pytest.raises(
        RuntimeError,
        match="simulated snapshot item insert failure",
    ):
        ingest_bom_snapshot(
            org_id=org_id,
            rows=[row],
            db=db,
            assembly_name="Test Assembly",
        )

    # Transaction must be rolled back
    db.rollback_transaction.assert_called_once_with()

    # Snapshot header must be explicitly deleted
    db.delete_snapshot.assert_called_once_with(snapshot_id)

    # Commit must never happen after the failure
    db.commit_transaction.assert_not_called()