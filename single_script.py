"""Single-file version of the rebar cutting optimizer."""
from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None
try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
except Exception:  # pragma: no cover
    Workbook = None
    Alignment = None

try:
    import pulp  # type: ignore
except Exception:  # pragma: no cover
    pulp = None

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
LOGGER = logging.getLogger("single_script")


@dataclass
class RebarItem:
    diameter: str
    length_mm: int
    quantity: int


@dataclass
class ParserConfig:
    table_header_search_rows: int = 5
    diameter_keywords: Sequence[str] = ("级", "径", "别", "直径")
    length_keywords: Sequence[str] = ("下料", "长度", "(mm)", "mm")
    quantity_keywords: Sequence[str] = ("总根数", "总", "根", "数量")
    min_length_mm: int = 200
    max_length_mm: int = 12000
    min_quantity: int = 1
    max_quantity: int = 5000
    excluded_length_tokens: Sequence[int] = (100, 150, 200, 210, 260, 300, 330, 340, 350,
                                            360, 370)
    max_paragraph_length: int = 400


DIAMETER_PATTERN = re.compile(r"E(\d{1,2})", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"\d+")


class PDFParser:
    def __init__(self, config: ParserConfig) -> None:
        self.config = config

    def parse(self, pdf_path: str) -> List[RebarItem]:
        if pdfplumber is None:
            raise RuntimeError("pdfplumber is required. Install it with 'pip install pdfplumber'.")
        items: List[RebarItem] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                page_items: List[RebarItem] = []
                tables = page.extract_tables() or []
                for table_index, table in enumerate(tables):
                    rows = [[(cell or "").strip() for cell in row] for row in table if row]
                    header_idx, column_map = self._locate_columns(rows)
                    if column_map is None:
                        continue
                    for row in rows[header_idx + 1:]:
                        item = self._row_to_item(row, column_map)
                        if item:
                            page_items.append(item)
                if len(page_items) < 3:
                    page_items.extend(self._parse_text_block(page.extract_text() or ""))
                items.extend(page_items)
        return self._aggregate(items)

    def _locate_columns(self, rows: Sequence[Sequence[str]]) -> Tuple[int, Optional[Dict[str, int]]]:
        for idx, row in enumerate(rows[:self.config.table_header_search_rows]):
            normalized = [cell.lower() for cell in row]
            dia = self._match(normalized, self.config.diameter_keywords)
            length = self._match(normalized, self.config.length_keywords)
            qty = self._match(normalized, self.config.quantity_keywords)
            if None not in (dia, length, qty):
                return idx, {"diameter": dia, "length": length, "quantity": qty}
        return 0, None

    @staticmethod
    def _match(row: Sequence[str], keywords: Sequence[str]) -> Optional[int]:
        for idx, cell in enumerate(row):
            if any(keyword in cell for keyword in keywords):
                return idx
        return None

    def _row_to_item(self, row: Sequence[str], column_map: Dict[str, int]) -> Optional[RebarItem]:
        try:
            diameter_raw = row[column_map["diameter"]]
            length_raw = row[column_map["length"]]
            quantity_raw = row[column_map["quantity"]]
        except IndexError:
            return None
        diameter = self._extract_diameter(diameter_raw)
        length = self._extract_length(length_raw)
        quantity = self._extract_quantity(quantity_raw)
        if not diameter or length <= 0 or quantity <= 0:
            return None
        return RebarItem(diameter=diameter, length_mm=length, quantity=quantity)

    def _parse_text_block(self, text: str) -> List[RebarItem]:
        segments = re.split(r"\n{2,}", text)
        items: List[RebarItem] = []
        for segment in segments:
            clean = segment.strip()
            if not clean or len(clean) > self.config.max_paragraph_length:
                continue
            match = DIAMETER_PATTERN.search(clean)
            if not match:
                continue
            diameter = f"E{match.group(1)}"
            numbers = [int(n) for n in NUMBER_PATTERN.findall(clean)]
            length = self._select_length(numbers)
            quantity = self._select_quantity(numbers)
            if length <= 0 or quantity <= 0:
                continue
            items.append(RebarItem(diameter=diameter, length_mm=length, quantity=quantity))
        return items

    def _select_length(self, numbers: Sequence[int]) -> int:
        candidates = [n for n in numbers if self.config.min_length_mm <= n <= self.config.max_length_mm
                      and n not in self.config.excluded_length_tokens]
        return max(candidates, default=0)

    def _select_quantity(self, numbers: Sequence[int]) -> int:
        candidates = [n for n in numbers if self.config.min_quantity <= n <= self.config.max_quantity]
        return candidates[-1] if candidates else 0

    @staticmethod
    def _extract_diameter(text: str) -> Optional[str]:
        match = DIAMETER_PATTERN.search(text)
        if match:
            return f"E{match.group(1)}"
        digits = re.findall(r"\d+", text)
        return f"E{digits[0]}" if digits else None

    @staticmethod
    def _extract_length(text: str) -> int:
        numbers = re.findall(r"\d+", text)
        return max((int(n) for n in numbers), default=0)

    @staticmethod
    def _extract_quantity(text: str) -> int:
        numbers = re.findall(r"\d+", text)
        return int(numbers[-1]) if numbers else 0

    @staticmethod
    def _aggregate(items: Iterable[RebarItem]) -> List[RebarItem]:
        merged: Dict[Tuple[str, int], int] = {}
        for item in items:
            merged[(item.diameter, item.length_mm)] = merged.get((item.diameter, item.length_mm), 0) + item.quantity
        return [RebarItem(diameter=diameter, length_mm=length, quantity=qty)
                for (diameter, length), qty in merged.items()]


@dataclass
class OptimizationConfig:
    stock_length: int = 12000
    local_search_iterations: int = 2
    use_ilp: bool = False
    ilp_timeout: int = 20


@dataclass
class StockCut:
    stock_id: int
    diameter: str
    segments: List[int]
    offcut: int


@dataclass
class DiameterPlan:
    diameter: str
    stock_length: int
    cuts: List[StockCut] = field(default_factory=list)


class Optimizer:
    def __init__(self, config: OptimizationConfig) -> None:
        self.config = config

    def optimize(self, grouped_lengths: Dict[str, List[int]]) -> Dict[str, DiameterPlan]:
        plans: Dict[str, DiameterPlan] = {}
        for diameter, lengths in grouped_lengths.items():
            if self.config.use_ilp and pulp is not None:
                plan = self._optimize_ilp(diameter, lengths)
            else:
                plan = self._optimize_heuristic(diameter, lengths)
            plans[diameter] = plan
        return plans

    def _optimize_heuristic(self, diameter: str, lengths: Sequence[int]) -> DiameterPlan:
        stock_length = self.config.stock_length
        bins: List[List[int]] = []
        remaining: List[int] = []
        for length in sorted(lengths, reverse=True):
            placed = False
            for idx, rem in enumerate(remaining):
                if length <= rem:
                    bins[idx].append(length)
                    remaining[idx] -= length
                    placed = True
                    break
            if not placed:
                bins.append([length])
                remaining.append(stock_length - length)
        bins = [bin_ for bin_ in bins if bin_]
        cuts = []
        for idx, segs in enumerate(bins, start=1):
            segs_sorted = sorted(segs, reverse=True)
            cuts.append(StockCut(stock_id=idx, diameter=diameter,
                                 segments=segs_sorted, offcut=stock_length - sum(segs_sorted)))
        return DiameterPlan(diameter=diameter, stock_length=stock_length, cuts=cuts)

    def _optimize_ilp(self, diameter: str, lengths: Sequence[int]) -> DiameterPlan:
        stock_length = self.config.stock_length
        pieces = list(lengths)
        max_bins = len(pieces)
        prob = pulp.LpProblem(f"Cutting_{diameter}", pulp.LpMinimize)
        x = pulp.LpVariable.dicts("x", ((i, j) for i in range(len(pieces)) for j in range(max_bins)),
                                  cat="Binary")
        y = pulp.LpVariable.dicts("y", (j for j in range(max_bins)), lowBound=0, upBound=1,
                                  cat="Binary")
        prob += pulp.lpSum(y[j] for j in range(max_bins))
        for i in range(len(pieces)):
            prob += pulp.lpSum(x[(i, j)] for j in range(max_bins)) == 1
        for j in range(max_bins):
            prob += pulp.lpSum(pieces[i] * x[(i, j)] for i in range(len(pieces))) <= stock_length * y[j]
        solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=self.config.ilp_timeout)
        prob.solve(solver)
        bins: List[List[int]] = [[] for _ in range(max_bins)]
        for (i, j), var in x.items():
            if var.value() and var.value() > 0.5:
                bins[j].append(pieces[i])
        bins = [bin_ for bin_ in bins if bin_]
        cuts = []
        for idx, segs in enumerate(bins, start=1):
            segs_sorted = sorted(segs, reverse=True)
            cuts.append(StockCut(stock_id=idx, diameter=diameter,
                                 segments=segs_sorted, offcut=stock_length - sum(segs_sorted)))
        return DiameterPlan(diameter=diameter, stock_length=stock_length, cuts=cuts)


def group_lengths(entries: Iterable[Tuple[str, int, int]]) -> Dict[str, List[int]]:
    grouped: Dict[str, List[int]] = {}
    for diameter, length, quantity in entries:
        grouped.setdefault(diameter, []).extend([length] * quantity)
    return grouped


def export_to_excel(plans: Dict[str, DiameterPlan], output_path: str) -> None:
    if Workbook is None:
        raise RuntimeError("openpyxl is required for Excel export. Install it with 'pip install openpyxl'.")
    wb = Workbook()
    summary = wb.active
    summary.title = "汇总"
    summary.append(["直径", "原材根数", "总边角(mm)", "平均浪费率"])
    total_stock = 0
    total_offcut = 0
    stock_length = 12000
    for diameter, plan in sorted(plans.items()):
        total_stock += len(plan.cuts)
        total_offcut += sum(cut.offcut for cut in plan.cuts)
        stock_length = plan.stock_length
        waste = (sum(cut.offcut for cut in plan.cuts) /
                 (len(plan.cuts) * plan.stock_length) if plan.cuts else 0)
        summary.append([diameter, len(plan.cuts), sum(cut.offcut for cut in plan.cuts), f"{waste:.2%}"])
    global_ratio = total_offcut / (total_stock * stock_length) if total_stock else 0
    summary.append(["合计", total_stock, total_offcut, f"{global_ratio:.2%}"])
    for col in summary.columns:
        for cell in col:
            if Alignment:
                cell.alignment = Alignment(horizontal="center")
    for diameter, plan in sorted(plans.items()):
        sheet = wb.create_sheet(diameter)
        sheet.append(["原材编号", "切割长度(mm)", "边角(mm)"])
        for cut in plan.cuts:
            sheet.append([cut.stock_id, ", ".join(map(str, cut.segments)), cut.offcut])
        for col in sheet.columns:
            for cell in col:
                if Alignment:
                    cell.alignment = Alignment(horizontal="center")
    wb.save(output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Single-file rebar optimizer")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--stock", type=int, default=12000)
    parser.add_argument("--out", default="下料方案.xlsx")
    parser.add_argument("--use-ilp", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    parser = PDFParser(ParserConfig())
    items = parser.parse(args.pdf)
    grouped = group_lengths((item.diameter, item.length_mm, item.quantity) for item in items)
    config = OptimizationConfig(stock_length=args.stock,
                                local_search_iterations=2,
                                use_ilp=args.use_ilp)
    optimizer = Optimizer(config)
    plans = optimizer.optimize(grouped)
    export_to_excel(plans, args.out)
    LOGGER.info("Excel exported to %s", Path(args.out).resolve())


if __name__ == "__main__":
    main()
