"""Configuration constants for the rebar optimizer pipeline."""
from dataclasses import dataclass, field
from typing import List, Sequence


@dataclass(frozen=True)
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
    log_unparsed_snippets: bool = True


@dataclass(frozen=True)
class OptimizationConfig:
    stock_length: int = 12000
    local_search_iterations: int = 2
    allow_ilp: bool = False
    ilp_timeout: int = 20  # seconds


@dataclass(frozen=True)
class ExportConfig:
    summary_sheet_name: str = "汇总"
    diameter_sheet_prefix: str = "E"


DEFAULT_PARSER_CONFIG = ParserConfig()
DEFAULT_OPT_CONFIG = OptimizationConfig()
DEFAULT_EXPORT_CONFIG = ExportConfig()
