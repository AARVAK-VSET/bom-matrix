"""BOM snapshot ingestion module for database persistence."""

from .snapshot_ingest import (
    ingest_bom_snapshot,
    NormalizedRow,
    DatabaseClient,
    normalize_row_from_dict
)
from .supabase_client import SupabaseClient
from .multisheet_tree import (
    expand_sub_assembly_tree,
    reconcile_sub_assembly_tree,
    detect_cycle_in_branch,
)
# NOTE: diff types are re-exported for backward compatibility with tests.
def __getattr__(name: str):
    if name in ("diff_snapshots", "DiffResult"):
        from bomkit.diff.snapshot_diff import diff_snapshots, DiffResult
        if name == "diff_snapshots":
            return diff_snapshots
        return DiffResult
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "ingest_bom_snapshot",
    "NormalizedRow",
    "DatabaseClient",
    "SupabaseClient",
    "normalize_row_from_dict",
    "expand_sub_assembly_tree",
    "reconcile_sub_assembly_tree",
    "detect_cycle_in_branch",
    "diff_snapshots",
    "DiffResult",
]

