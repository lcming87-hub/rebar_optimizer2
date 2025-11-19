"""Self-checks for the rebar optimizer."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1] / "project"
sys.path.insert(0, str(PROJECT_ROOT))

from core.optimize import CuttingOptimizer
from core.config import OptimizationConfig


def make_plan(lengths_by_diameter, stock_length=12000):
    config = OptimizationConfig(stock_length=stock_length, local_search_iterations=2)
    optimizer = CuttingOptimizer(config)
    return optimizer.optimize(lengths_by_diameter)


def test_zero_waste_case():
    data = {"E12": [6000, 3000, 3000]}
    plan = make_plan(data)
    assert plan["E12"].cuts[0].offcut == 0
    assert len(plan["E12"].cuts) == 1


def test_quantity_preservation():
    grouped = {"E10": [4000, 4000, 2000, 2000, 2000]}
    plan = make_plan(grouped)
    reconstructed = []
    for cut in plan["E10"].cuts:
        reconstructed.extend(cut.segments)
    assert sorted(reconstructed) == sorted(grouped["E10"])


def test_stock_length_not_exceeded():
    grouped = {"E14": [5000, 5000, 2000, 1500, 1500, 1000]}
    plan = make_plan(grouped)
    for cut in plan["E14"].cuts:
        assert sum(cut.segments) <= plan["E14"].stock_length
