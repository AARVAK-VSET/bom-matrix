# BOM-Matrix ⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Organization](https://img.shields.io/badge/Organization-AARVAK--VSET-purple.svg)](https://github.com/AARVAK-VSET)
[![Event](https://img.shields.io/badge/TSJ%202026-Patch%20Wars-orange.svg)](https://github.com/AARVAK-VSET)

> **BOM-Matrix** is an open-source, high-performance toolkit for parsing, normalizing, profiling, and diffing engineering **Bills of Materials (BOM)** across diverse formats (Excel, CSV, PLM exports). Built for precision engineering, hardware teams, and enterprise automation.

---

## 🚀 Key Features

- **Multi-Format Ingestion**: Streamlined parsing of `.xlsx`, `.xls`, and `.csv` files with automatic encoding detection.
- **Header Profiling & Schema Normalization**: Lexical and semantic matching to map arbitrary vendor column names to standardized engineering headers.
- **Unit Normalization**: Automatic conversion and unit standardisation (dimensions, weights, tolerances, package counts) powered by `pint`.
- **Intelligent Diff Engine**: Detect structural hierarchy shifts, part revisions, and quantity discrepancies across BOM releases.
- **MCP Integration**: Includes Model Context Protocol (MCP) server integration for automated querying via LLMs and AI engineering agents.
- **Clean CLI & Python SDK**: Use as a standalone command-line tool or import directly into your Python processing pipelines.

---

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/AARVAK-VSET/bom-matrix.git
cd bom-matrix

# Install dependencies
pip install -e .

# Or install with MCP server support
pip install -e .[mcp]
```

---

## 🛠️ Quick Start

### 1. Command Line Interface (CLI)

```bash
# Inspect and profile column schema
bom-matrix sample_bom.xlsx --profile

# Normalize BOM and export to JSON
bom-matrix sample_bom.xlsx --normalize -o normalized_bom.json
```

### 2. Python API

```python
from bomkit import BomParser, BomNormalizer, UnitNormalizer

# Initialize parser & normalizer
parser = BomParser()
normalizer = BomNormalizer()

# Parse file
raw_records = parser.parse("parts_list.csv")

# Standardize fields and units
clean_records = normalizer.normalize(raw_records)
print(f"Processed {len(clean_records)} normalized BOM rows.")
```

---

## 📁 Architecture Overview

```
bom-matrix/
├── bomkit/
│   ├── adapters/            # Vendor-specific import adapters
│   ├── diff/                # Structural and revision diffing engine
│   ├── ingest/              # File loaders and chardet stream decoders
│   ├── mcp/                 # Teamcenter and PLM MCP servers
│   ├── schema/              # Standardized engineering schemas and mappings
│   ├── column_profiler.py   # Statistical column and header inference
│   ├── lexical_similarity.py# Fuzzy matching algorithms for messy headers
│   ├── normalizer.py        # Master BOM normalizer
│   ├── parser.py            # Tabular file parser (Excel/CSV)
│   └── unit_normalizer.py   # Dimensional unit conversion
├── tests/                   # Automated unit & integration tests
├── pyproject.toml           # Packaging and CLI specification
└── README.md
```

---

## 🤝 Contributing to Patch Wars 2026

We welcome contributions from all **Patch Wars (TSJ 2026)** participants!

1. Fork this repository: `https://github.com/AARVAK-VSET/bom-matrix`
2. Claim an open issue by commenting `"Claiming this issue"` on the issue thread.
3. Create your feature branch: `git checkout -b fix/issue-<number>`
4. Implement your solution and ensure tests pass: `pytest`
5. Submit a clear Pull Request referencing the issue (e.g., `Fixes #12`).

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more details.  
Maintained by **[AARVAK-VSET](https://github.com/AARVAK-VSET)**.
