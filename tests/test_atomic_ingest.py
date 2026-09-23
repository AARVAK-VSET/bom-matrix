import pytest
from uuid import uuid4
from bomkit.ingest.snapshot_ingest import ingest_bom_snapshot, DatabaseClient, NormalizedRow

class MockFailingDatabaseClient(DatabaseClient):
    def __init__(self):
        self.deleted_snapshots = []
        
    def get_or_create_organization(self, org_id, org_name=None):
        return org_id
        
    def get_or_create_assembly(self, org_id, assembly_name):
        return uuid4()
        
    def find_similar_parts(self, org_id, part_name, attributes, similarity_threshold=0.8):
        return []
        
    def create_part(self, org_id, part_name, attributes):
        return uuid4()
        
    def find_similar_bom_items(self, assembly_id, part_id, context, similarity_threshold=0.7):
        return []
        
    def create_bom_item(self, assembly_id, part_id, context):
        return uuid4()
        
    def create_snapshot(self, org_id, assembly_id, source, parent_snapshot_id=None):
        return uuid4()
        
    def insert_snapshot_items_batch(self, snapshot_id, items):
        raise RuntimeError("Simulated failure during items insert")
        
    def delete_snapshot(self, snapshot_id):
        self.deleted_snapshots.append(snapshot_id)
        
    def begin_transaction(self):
        pass
        
    def commit_transaction(self):
        pass
        
    def rollback_transaction(self):
        pass

def test_partial_failure_cleanup():
    db = MockFailingDatabaseClient()
    org_id = uuid4()
    
    rows = [
        NormalizedRow(
            part_name="TEST_PART",
            quantity=1,
            attributes={},
            context={},
            row_index=1
        )
    ]
    
    with pytest.raises(RuntimeError, match="Simulated failure during items insert"):
        ingest_bom_snapshot(
            org_id=org_id,
            rows=rows,
            db=db,
            assembly_name="Test Assembly"
        )
        
    assert len(db.deleted_snapshots) == 1, "Expected compensating delete_snapshot call"

class RecordingDatabaseClient(DatabaseClient):
      """Fake client that records every batch call, for asserting on batch sizes."""
      def __init__(self, fail_on_batch_index=None):
        self.batch_calls = []
        self.fail_on_batch_index = fail_on_batch_index
        self.deleted_snapshots = []
        self.committed = False
        self.rolled_back = False

      def get_or_create_organization(self, org_id, org_name=None):
        return org_id

      def get_or_create_assembly(self, org_id, assembly_name):
        return uuid4()

      def find_similar_parts(self, org_id, part_name, attributes, similarity_threshold=0.8):
        return []

      def create_part(self, org_id, part_name, attributes):
        return uuid4()

      def find_similar_bom_items(self, assembly_id, part_id, context, similarity_threshold=0.7):
        return []

      def create_bom_item(self, assembly_id, part_id, context):
        return uuid4()

      def create_snapshot(self, org_id, assembly_id, source, parent_snapshot_id=None):
        return uuid4()

      def delete_snapshot(self, snapshot_id):
        self.deleted_snapshots.append(snapshot_id)

      def insert_snapshot_item(self, snapshot_id, bom_item_id, quantity, attributes, checksum):
        raise AssertionError("Old single-row insert path should not be called after batching fix")

      def insert_snapshot_items_batch(self, snapshot_id, items):
        idx = len(self.batch_calls)
        if self.fail_on_batch_index is not None and idx == self.fail_on_batch_index:
            raise RuntimeError(f"Simulated failure on batch {idx}")
        self.batch_calls.append(list(items))

      def begin_transaction(self):
        pass

      def commit_transaction(self):
        self.committed = True

      def rollback_transaction(self):
        self.rolled_back = True


def _make_rows(n):
    return [
        NormalizedRow(
            part_name=f"PART_{i}", quantity=1, attributes={}, context={}, row_index=i
        )
        for i in range(n)
    ]


def test_batch_size_default_is_500():
    db = RecordingDatabaseClient()
    ingest_bom_snapshot(
        org_id=uuid4(), rows=_make_rows(2500), db=db, assembly_name="Test"
    )
    assert [len(b) for b in db.batch_calls] == [500, 500, 500, 500, 500]


def test_batch_remainder_is_sent_as_final_partial_batch():
    db = RecordingDatabaseClient()
    ingest_bom_snapshot(
        org_id=uuid4(), rows=_make_rows(1200), db=db,
        assembly_name="Test", batch_size=500
    )
    assert [len(b) for b in db.batch_calls] == [500, 500, 200]


def test_batch_size_larger_than_item_count_sends_one_batch():
    db = RecordingDatabaseClient()
    ingest_bom_snapshot(
        org_id=uuid4(), rows=_make_rows(3), db=db,
        assembly_name="Test", batch_size=500
    )
    assert [len(b) for b in db.batch_calls] == [3]


def test_batch_size_exact_boundary_is_one_batch_not_two():
    db = RecordingDatabaseClient()
    ingest_bom_snapshot(
        org_id=uuid4(), rows=_make_rows(500), db=db,
        assembly_name="Test", batch_size=500
    )
    assert [len(b) for b in db.batch_calls] == [500]


def test_invalid_batch_size_raises_value_error():
    db = RecordingDatabaseClient()
    with pytest.raises(ValueError, match="batch_size"):
        ingest_bom_snapshot(
            org_id=uuid4(), rows=_make_rows(3), db=db,
            assembly_name="Test", batch_size=0
        )


def test_batch_failure_rolls_back_and_reports_context():
    db = RecordingDatabaseClient(fail_on_batch_index=1)
    with pytest.raises(RuntimeError, match="Batch 1 failed after 1 batch"):
        ingest_bom_snapshot(
            org_id=uuid4(), rows=_make_rows(12), db=db,
            assembly_name="Test", batch_size=5
        )
    assert not db.committed
    assert len(db.deleted_snapshots) == 1
    assert len(db.batch_calls) == 1  # only the first batch got through
