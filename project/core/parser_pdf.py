"""PDF parsing utilities for extracting rebar schedules."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency during tests
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

from .config import ParserConfig, DEFAULT_PARSER_CONFIG

LOGGER = logging.getLogger(__name__)


@dataclass
class RebarItem:
    diameter: str
    length_mm: int
    quantity: int


DIAMETER_PATTERN = re.compile(r"E(\d{1,2})", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"\d+")


class PDFRebarParser:
    """Parser that extracts rebar data from PDF reports."""

    def __init__(self, config: ParserConfig = DEFAULT_PARSER_CONFIG) -> None:
        self.config = config

    def parse(self, pdf_path: str) -> List[RebarItem]:
        if pdfplumber is None:
            raise RuntimeError("pdfplumber is required for PDF parsing. Please install it via pip.")
        entries: List[RebarItem] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                page_entries: List[RebarItem] = []
                tables = page.extract_tables() or []
                for table_index, table in enumerate(tables):
                    parsed = self._parse_table(table, page_index, table_index)
                    page_entries.extend(parsed)
                if len(page_entries) < 3:
                    fallback_entries = self._parse_text_block(page.extract_text() or "",
                                                             page_index)
                    page_entries.extend(fallback_entries)
                entries.extend(page_entries)
        aggregated = self._aggregate(entries)
        return aggregated

    def _parse_table(self, table: Sequence[Sequence[Optional[str]]], page: int,
                     table_index: int) -> List[RebarItem]:
        rows = [[(cell or "").strip() for cell in row] for row in table if row]
        header_row_index, column_map = self._locate_columns(rows)
        if column_map is None:
            LOGGER.debug("Page %s table %s skipped: header not found", page, table_index)
            return []
        entries: List[RebarItem] = []
        for row in rows[header_row_index + 1:]:
            entry = self._row_to_item(row, column_map)
            if entry:
                entries.append(entry)
        LOGGER.info("Page %s table %s parsed %s entries", page, table_index, len(entries))
        return entries

    def _locate_columns(self, rows: Sequence[Sequence[str]]) -> Tuple[int, Optional[Dict[str, int]]]:
        for idx, row in enumerate(rows[:self.config.table_header_search_rows]):
            normalized = [cell.lower() for cell in row]
            diameter_col = self._match_column(normalized, self.config.diameter_keywords)
            length_col = self._match_column(normalized, self.config.length_keywords)
            quantity_col = self._match_column(normalized, self.config.quantity_keywords)
            if None not in (diameter_col, length_col, quantity_col):
                return idx, {"diameter": diameter_col, "length": length_col,
                             "quantity": quantity_col}
        return 0, None

    @staticmethod
    def _match_column(row: Sequence[str], keywords: Sequence[str]) -> Optional[int]:
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
            LOGGER.debug("Discarded row: %s", row)
            return None
        return RebarItem(diameter=diameter, length_mm=length, quantity=quantity)

    def _parse_text_block(self, text: str, page_index: int) -> List[RebarItem]:
        if not text:
            return []
        segments = re.split(r"\n{2,}", text)
        items: List[RebarItem] = []
        for segment in segments:
            clean_segment = segment.strip()
            if not clean_segment or len(clean_segment) > self.config.max_paragraph_length:
                continue
            diameters = DIAMETER_PATTERN.findall(clean_segment)
            if not diameters:
                continue
            diameter = f"E{diameters[-1]}"
            numbers = [int(match) for match in NUMBER_PATTERN.findall(clean_segment)]
            if not numbers:
                continue
            length = self._select_length(numbers)
            quantity = self._select_quantity(numbers)
            if length <= 0 or quantity <= 0:
                continue
            items.append(RebarItem(diameter=diameter, length_mm=length, quantity=quantity))
        if items:
            LOGGER.info("Page %s text fallback produced %s entries", page_index, len(items))
        elif self.config.log_unparsed_snippets:
            LOGGER.warning("Page %s text fallback failed. Sample text: %s", page_index,
                           text[:100])
        return items

    def _select_length(self, numbers: Sequence[int]) -> int:
        candidates = [n for n in numbers if self.config.min_length_mm <= n <= self.config.max_length_mm
                      and n not in self.config.excluded_length_tokens]
        return max(candidates, default=0)

    def _select_quantity(self, numbers: Sequence[int]) -> int:
        candidates = [n for n in numbers if self.config.min_quantity <= n <= self.config.max_quantity]
        return candidates[-1] if candidates else 0

    @staticmethod
    def _extract_diameter(cell: str) -> Optional[str]:
        match = DIAMETER_PATTERN.search(cell)
        if match:
            return f"E{match.group(1)}"
        digits = re.findall(r"\d+", cell)
        if digits:
            return f"E{digits[0]}"
        return None

    @staticmethod
    def _extract_length(cell: str) -> int:
        numbers = re.findall(r"\d+", cell)
        if not numbers:
            return 0
        return max(int(n) for n in numbers)

    @staticmethod
    def _extract_quantity(cell: str) -> int:
        numbers = re.findall(r"\d+", cell)
        if not numbers:
            return 0
        return int(numbers[-1])

    @staticmethod
    def _aggregate(items: Iterable[RebarItem]) -> List[RebarItem]:
        merged: Dict[Tuple[str, int], int] = {}
        for item in items:
            key = (item.diameter, item.length_mm)
            merged[key] = merged.get(key, 0) + item.quantity
        return [RebarItem(diameter=diameter, length_mm=length, quantity=qty)
                for (diameter, length), qty in merged.items() if qty > 0]


def parse_pdf(pdf_path: str, config: ParserConfig = DEFAULT_PARSER_CONFIG) -> List[RebarItem]:
    parser = PDFRebarParser(config)
    return parser.parse(pdf_path)
