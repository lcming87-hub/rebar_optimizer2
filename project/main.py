"""Command line interface for the rebar optimization workflow."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, List

from core.config import DEFAULT_EXPORT_CONFIG, DEFAULT_OPT_CONFIG, DEFAULT_PARSER_CONFIG
from core.export_xlsx import export_to_excel
from core.optimize import group_lengths, optimize
from core.parser_pdf import RebarItem, parse_pdf

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebar stock cutting optimizer")
    parser.add_argument("--pdf", required=True, help="Path to the PDF summary report")
    parser.add_argument("--stock", type=int, default=DEFAULT_OPT_CONFIG.stock_length,
                        help="Stock length in mm (default: 12000)")
    parser.add_argument("--out", default="下料方案.xlsx", help="Output Excel path")
    parser.add_argument("--use-ilp", action="store_true", help="Use ILP optimizer")
    return parser


def main(argv: List[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    stock_length = args.stock
    LOGGER.info("Parsing PDF: %s", args.pdf)
    entries = parse_pdf(args.pdf, config=DEFAULT_PARSER_CONFIG)
    total_segments = sum(item.quantity for item in entries)
    LOGGER.info("Parsed %s unique (直径, 长度) records", len(entries))
    LOGGER.info("Total segments: %s", total_segments)
    grouped = group_lengths((item.diameter, item.length_mm, item.quantity) for item in entries)
    opt_config = DEFAULT_OPT_CONFIG
    opt_config = opt_config.__class__(
        stock_length=stock_length,
        local_search_iterations=opt_config.local_search_iterations,
        allow_ilp=args.use_ilp,
        ilp_timeout=opt_config.ilp_timeout,
    )
    plans = optimize(grouped, config=opt_config, use_ilp=args.use_ilp)
    output_path = Path(args.out)
    export_to_excel(plans, str(output_path), config=DEFAULT_EXPORT_CONFIG)
    LOGGER.info("Excel exported to %s", output_path.resolve())


if __name__ == "__main__":
    main()
