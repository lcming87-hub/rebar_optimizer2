"""Excel export utilities for the cutting plan."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

try:  # pragma: no cover - optional dependency for tests
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
except Exception:  # pragma: no cover
    Workbook = None
    Alignment = None

from .config import DEFAULT_EXPORT_CONFIG, ExportConfig
from .optimize import DiameterPlan


@dataclass
class SummaryRow:
    diameter: str
    stock_count: int
    total_offcut: int
    waste_ratio: float


class ExcelExporter:
    def __init__(self, config: ExportConfig = DEFAULT_EXPORT_CONFIG) -> None:
        self.config = config

    def export(self, plans: Dict[str, DiameterPlan], output_path: str) -> None:
        if Workbook is None:
            raise RuntimeError("openpyxl is required for Excel export. Install it via pip.")
        wb = Workbook()
        summary_sheet = wb.active
        summary_sheet.title = self.config.summary_sheet_name
        self._write_summary(summary_sheet, plans)
        for diameter, plan in sorted(plans.items()):
            sheet = wb.create_sheet(title=diameter)
            self._write_diameter_sheet(sheet, plan)
        wb.save(output_path)

    def _write_summary(self, sheet, plans: Dict[str, DiameterPlan]) -> None:
        headers = ["直径", "原材根数", "总边角(mm)", "平均浪费率"]
        sheet.append(headers)
        total_stock = 0
        total_offcut = 0
        stock_length = 0
        for diameter, plan in sorted(plans.items()):
            stock_count = plan.total_stock
            total_stock += stock_count
            total_offcut += plan.total_offcut
            stock_length = plan.stock_length
            waste_ratio = plan.total_offcut / (stock_count * stock_length) if stock_count else 0
            sheet.append([diameter, stock_count, plan.total_offcut,
                          f"{waste_ratio:.2%}"])
        global_ratio = total_offcut / (total_stock * stock_length) if total_stock else 0
        sheet.append(["合计", total_stock, total_offcut, f"{global_ratio:.2%}"])
        for col in sheet.columns:
            for cell in col:
                if Alignment:
                    cell.alignment = Alignment(horizontal="center")

    def _write_diameter_sheet(self, sheet, plan: DiameterPlan) -> None:
        sheet.append(["原材编号", "切割长度(mm)", "边角(mm)"])
        for cut in plan.cuts:
            lengths = ", ".join(str(length) for length in cut.segments)
            sheet.append([cut.stock_id, lengths, cut.offcut])
        for col in sheet.columns:
            for cell in col:
                if Alignment:
                    cell.alignment = Alignment(horizontal="center")


def export_to_excel(plans: Dict[str, DiameterPlan],
                    output_path: str,
                    config: ExportConfig = DEFAULT_EXPORT_CONFIG) -> None:
    exporter = ExcelExporter(config)
    exporter.export(plans, output_path)
