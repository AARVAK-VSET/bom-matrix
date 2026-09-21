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
        
    def insert_snapshot_item(self, snapshot_id, bom_item_id, quantity, attributes, checksum):
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
