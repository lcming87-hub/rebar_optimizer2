# Rebar Optimizer

This repository delivers a PDF-to-cutting-plan workflow tailored for reinforced concrete projects. It fulfills the full specification described in the prompt, including PDF parsing, stock cutting optimization, Excel reporting, and verification tests.

## Features

* **Robust PDF parsing** using `pdfplumber`, with automatic table header detection and a text-regex fallback to cope with noisy layouts.
* **Configurable data cleaning** (keyword lists, length/quantity ranges, excluded tokens) via `project/core/config.py`.
* **Heuristic and ILP optimization** for 12 m stock (or custom). First-Fit-Decreasing packing plus small local swaps serves as the default, while an optional PuLP-based ILP gives optimal solutions for smaller instances.
* **Excel reporting** with a summary worksheet and one sheet per diameter, detailing each bar, its cuts, and the offcut waste.
* **Single-file implementation** (`single_script.py`) for copy/paste deployment, and a modular multi-file project under `project/`.
* **Logging + validation** with informative INFO/WARNING entries, ready for integration into larger automation pipelines.
* **Self-tests** covering zero-waste scenarios, quantity conservation, and per-stock length limits.

## Project Layout

```
project/
  core/
    __init__.py
    config.py         # Centralized configuration constants
    parser_pdf.py     # PDF parsing + regex fallback
    optimize.py       # Heuristic + optional ILP cutting
    export_xlsx.py    # Excel writer
  main.py             # CLI entry point
single_script.py      # Standalone script variant
requirements.txt
README.md
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## CLI Usage

Modular project:

```bash
cd project
python main.py --pdf "3#住宅 二层 柱（上接）(全部汇总).pdf" --stock 12000 --out "下料方案.xlsx"
```

Single-file version:

```bash
python single_script.py --pdf "3#住宅 二层 柱（上接）(全部汇总).pdf"
```

Additional flags:

* `--stock`: Stock length in millimeters (default 12000)
* `--out`: Output Excel path (default `下料方案.xlsx`)
* `--use-ilp`: Force ILP optimization (falls back automatically if PuLP unavailable)

## PDF Parsing Logic

1. **Table-first strategy** – each PDF page is scanned for tables (`page.extract_tables`). Rows are cleaned, and within the first configurable rows the code searches for the diameter/length/quantity headers using keyword lists (`ParserConfig`).
2. **Column extraction** – once headers are located, rows below are converted to `RebarItem` instances. Each cell undergoes:
   * Diameter detection via `E\d+` regex or fallback digits.
   * Length parsing by collecting numeric tokens and taking the maximum (matching the longest bar in cells like `3000/3640`).
   * Quantity parsing via the last integer in the cell.
3. **Text fallback** – if a page produces fewer than 3 entries from tables, the full text block is split by blank lines. Segments containing `E\d+` are processed with number filtering (length range 200–12000 mm, excluding common stirrup spacings like 100/150/210, etc.). Length takes the maximum candidate; quantity is the last in range 1–5000.
4. **Aggregation** – identical `(直径, 长度)` pairs have their quantities summed to avoid duplication. Invalid rows (length/quantity ≤ 0) are discarded with debug logs. Optionally, unparsed snippets emit warnings.

## Cutting Optimization Logic

1. **Input preparation** – `group_lengths` explodes the aggregated rows into per-diameter length lists, duplicating each length by its quantity.
2. **Heuristic baseline (FFD)** – lengths sort descending; each piece is dropped into the first stock with sufficient remaining length. When none fits, a new 12 m stock is created.
3. **Local improvement** – configurable small iterations attempt to move pieces between stocks if doing so reduces the remaining length of either stock (simple hill-climb to shave waste).
4. **ILP option** – if enabled, a PuLP model uses binary variables `x_{ij}` (piece `i` assigned to stock `j`) and `y_j` (stock `j` used) with constraints:
   * `sum_j x_{ij} = 1` for each piece.
   * `sum_i length_i * x_{ij} <= stock_length * y_j` for each stock.
   * Objective: minimize `sum_j y_j` (indirectly minimizing offcut and stock count). Solver time limit is configurable; the CLI automatically falls back to heuristic if PuLP is missing.
5. **Validation** – while exporting, sums per diameter and the global totals enforce conservation of segments, and offcuts are derived from `stock_length - sum(segments)` to ensure ≤ 12000 mm.

## Excel Output

* **`汇总` sheet** – columns `直径`, `原材根数`, `总边角(mm)`, `平均浪费率`. A final `合计` row aggregates across diameters, and waste rate = total offcut / (stock_count × stock_length).
* **Per-diameter sheets** – columns `原材编号`, `切割长度(mm)`, `边角(mm)` listing each stock bar.

## OCR Strategy (for scanned PDFs)

The default implementation relies on text-based PDFs. For image-only PDFs, integrate Tesseract:

```python
import pdf2image, pytesseract

pages = pdf2image.convert_from_path(pdf_path)
for page_image in pages:
    text = pytesseract.image_to_string(page_image, lang="chi_sim")
    # feed the text into the regex fallback parser
```

You can wrap this logic into `PDFRebarParser` when `page.extract_tables()` returns no tables.

## Tests / Self-checks

`pytest` tests live in `tests/test_optimizer.py` and cover:

1. **Zero waste** – lengths 6000 + 3000 + 3000 fit exactly into a single stock (waste 0).
2. **Quantity conservation** – mixed lengths maintain total counts after optimization.
3. **Stock bounds** – every generated stock obeys the 12,000 mm limit.

Run them with `pytest` from the repo root.

## Extensibility Notes

* **New business rules** – add constraints in `core/optimize.py`, e.g., to enforce paired bars or minimum leftover lengths.
* **Tolerance bands** – modify `OptimizationConfig` to support stock length variations or kerf deductions.
* **Advanced heuristics** – plug additional local search operators (e.g., pair swaps) into `_local_search`.
* **Additional exports** – hook into `ExcelExporter` to emit CSV summaries or PowerPoint charts.

