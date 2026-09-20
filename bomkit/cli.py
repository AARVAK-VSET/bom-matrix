"""
BOM-Matrix CLI Entrypoint
AARVAK-VSET Open-Source Initiative
"""
import sys
import argparse
import json
from pathlib import Path
from .parser import BomParser
from .normalizer import BomNormalizer
from .unit_normalizer import UnitNormalizer
from .column_profiler import ColumnProfiler
from .adapters.csv_adapter import CsvAdapter
from .adapters.excel_adapter import ExcelAdapter
from .confidence import ConfidenceScorer

def main():
    parser = argparse.ArgumentParser(
        prog="bom-matrix",
        description="BOM-Matrix: High-performance Bill of Materials parsing and normalization engine."
    )
    parser.add_argument("file", nargs="?", help="Path to BOM file (CSV/Excel) to parse or inspect")
    parser.add_argument("--profile", action="store_true", help="Profile columns and detect standard headers")
    parser.add_argument("--normalize", action="store_true", help="Normalize columns and units")
    parser.add_argument("--output", "-o", help="Output path for normalized BOM (JSON or CSV)")
    parser.add_argument("--version", "-v", action="version", version="bom-matrix 1.0.0")
    parser.add_argument(
        "--confidence",
        action="store_true",
        help="Emit a structured composite confidence telemetry report (JSON)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        metavar="FLOAT",
        help="Flag line items whose composite confidence is below this 0.0-1.0 "
             "threshold and exit with a non-zero status code if any are flagged",
    )

    args = parser.parse_args()

    if args.min_confidence is not None and not (0.0 <= args.min_confidence <= 1.0):
        parser.error("--min-confidence must be a float between 0.0 and 1.0")

    if not args.file:
        parser.print_help()
        sys.exit(0)

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File '{args.file}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"[BOM-Matrix] Loading BOM: {file_path.name}")
    bom_parser = BomParser()
    bom_parser.register_adapter(CsvAdapter())
    bom_parser.register_adapter(ExcelAdapter())
    try:
        data = bom_parser.parse(file_path)
        print(f"[BOM-Matrix] Successfully parsed {len(data)} rows.")
        
        if args.profile:
            profiler = ColumnProfiler()
            profile_results = profiler.profile(data)
            print("[BOM-Matrix] Column Profiles:")
            print(json.dumps(profile_results, indent=2, default=str))

        if args.normalize:
            normalizer = BomNormalizer()
            normalized_data = normalizer.normalize(data)
            print(f"[BOM-Matrix] Normalized {len(normalized_data)} records.")
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(normalized_data, f, indent=2, default=str)
                print(f"[BOM-Matrix] Saved output to {args.output}")

        if args.confidence or args.min_confidence is not None:
            raw_data = bom_parser.parse(file_path, normalize=False)
            scorer = ConfidenceScorer()
            report = scorer.build_report(raw_data, min_confidence=args.min_confidence)
            print("[BOM-Matrix] Composite Confidence Telemetry:")
            print(json.dumps(report, indent=2, default=str))

            if args.min_confidence is not None:
                flagged = [item for item in report.get("items", []) if item.get("flagged")]
                if flagged:
                    rows = ", ".join(f"row {item['row']}" for item in flagged)
                    total = report.get("table", {}).get("rows", 0)
                    print(
                        f"[BOM-Matrix] Confidence check FAILED: {len(flagged)} of {total} "
                        f"line items below {args.min_confidence}.",
                        file=sys.stderr,
                    )
                    print(f"[BOM-Matrix] Flagged low-confidence line items: {rows}")
                    sys.exit(1)
                print(
                    f"[BOM-Matrix] Confidence check passed: all "
                    f"{report.get('table', {}).get('rows', 0)} line items at or above "
                    f"{args.min_confidence}."
                )

    except Exception as e:
        print(f"[BOM-Matrix] Error processing file: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
