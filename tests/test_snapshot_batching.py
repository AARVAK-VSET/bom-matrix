from uuid import uuid4

import pytest

from bomkit.ingest import snapshot_ingest
from bomkit.ingest.snapshot_ingest import NormalizedRow, ingest_bom_snapshot


class RecordingDatabase:
    def __init__(self):
        self.batches = []
        self.committed = False

    def begin_transaction(self):
        pass

    def get_or_create_organization(self, org_id):
        return org_id

    def get_or_create_assembly(self, org_id, assembly_name):
        return uuid4()

    def create_snapshot(self, org_id, assembly_id, source, parent_snapshot_id=None):
        return uuid4()

    def insert_snapshot_items(self, snapshot_id, items):
        self.batches.append((snapshot_id, items))

    def commit_transaction(self):
        self.committed = True

    def rollback_transaction(self):
        raise AssertionError("rollback should not be needed")


def test_ingest_inserts_snapshot_items_in_configured_batches(monkeypatch):
    rows = [
        NormalizedRow(f"R{index}", 1, {}, {}, index)
        for index in range(5)
    ]
    db = RecordingDatabase()

    monkeypatch.setattr(snapshot_ingest, "_resolve_or_create_part", lambda **kwargs: uuid4())
    monkeypatch.setattr(snapshot_ingest, "_resolve_or_create_bom_item", lambda **kwargs: uuid4())

    ingest_bom_snapshot(
        org_id=uuid4(),
        assembly_name="test",
        rows=rows,
        db=db,
        batch_size=2,
    )

    assert [len(items) for _, items in db.batches] == [2, 2, 1]
    assert db.committed


def test_ingest_rejects_non_positive_batch_size():
    with pytest.raises(ValueError, match="batch_size"):
        ingest_bom_snapshot(
            org_id=uuid4(),
            assembly_name="test",
            rows=[NormalizedRow("R1", 1, {}, {}, 0)],
            db=RecordingDatabase(),
            batch_size=0,
        )