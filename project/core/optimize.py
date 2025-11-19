"""Cutting optimization algorithms for rebar stock."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import pulp  # type: ignore
except Exception:  # pragma: no cover
    pulp = None

from .config import OptimizationConfig, DEFAULT_OPT_CONFIG

LOGGER = logging.getLogger(__name__)


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

    @property
    def total_offcut(self) -> int:
        return sum(cut.offcut for cut in self.cuts)

    @property
    def total_stock(self) -> int:
        return len(self.cuts)


class CuttingOptimizer:
    def __init__(self, config: OptimizationConfig = DEFAULT_OPT_CONFIG) -> None:
        self.config = config

    def optimize(self, grouped_lengths: Dict[str, List[int]],
                 use_ilp: Optional[bool] = None) -> Dict[str, DiameterPlan]:
        use_ilp = self.config.allow_ilp if use_ilp is None else use_ilp
        plans: Dict[str, DiameterPlan] = {}
        for diameter, lengths in grouped_lengths.items():
            if not lengths:
                continue
            LOGGER.info("Optimizing %s with %s segments", diameter, len(lengths))
            if use_ilp and pulp is None:
                LOGGER.warning("ILP requested but pulp not installed. Falling back to heuristic.")
                use_ilp = False
            if use_ilp:
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
            for idx, remaining_length in enumerate(remaining):
                if length <= remaining_length:
                    bins[idx].append(length)
                    remaining[idx] -= length
                    placed = True
                    break
            if not placed:
                bins.append([length])
                remaining.append(stock_length - length)
        bins, remaining = self._local_search(bins, remaining)
        cuts: List[StockCut] = []
        for idx, segs in enumerate(bins, start=1):
            segs_sorted = sorted(segs, reverse=True)
            offcut = stock_length - sum(segs_sorted)
            cuts.append(StockCut(stock_id=idx, diameter=diameter,
                                 segments=segs_sorted, offcut=offcut))
        return DiameterPlan(diameter=diameter, stock_length=stock_length, cuts=cuts)

    def _local_search(self, bins: List[List[int]], remaining: List[int]) -> Tuple[List[List[int]], List[int]]:
        stock_length = self.config.stock_length
        for _ in range(self.config.local_search_iterations):
            improved = False
            for i in range(len(bins)):
                for j in range(len(bins)):
                    if i == j:
                        continue
                    for seg in list(bins[i]):
                        if seg <= remaining[j]:
                            new_remaining_i = remaining[i] + seg
                            new_remaining_j = remaining[j] - seg
                            if new_remaining_i < remaining[i] or new_remaining_j < remaining[j]:
                                bins[i].remove(seg)
                                bins[j].append(seg)
                                remaining[i] = new_remaining_i
                                remaining[j] = new_remaining_j
                                improved = True
                                break
                    if improved:
                        break
                if improved:
                    break
            if not improved:
                break
        bins = [bin_ for bin_ in bins if bin_]
        remaining = [stock_length - sum(bin_) for bin_ in bins]
        return bins, remaining

    def _optimize_ilp(self, diameter: str, lengths: Sequence[int]) -> DiameterPlan:
        if pulp is None:
            raise RuntimeError("pulp is required for ILP optimization")
        stock_length = self.config.stock_length
        pieces = list(lengths)
        max_bins = len(pieces)
        prob = pulp.LpProblem(f"Cutting_{diameter}", pulp.LpMinimize)
        x = pulp.LpVariable.dicts("x", ((i, j) for i in range(len(pieces)) for j in range(max_bins)),
                                  cat="Binary")
        y = pulp.LpVariable.dicts("y", (j for j in range(max_bins)), lowBound=0, upBound=1,
                                  cat="Binary")
        prob += pulp.lpSum(y[j] for j in range(max_bins))
        for i, length in enumerate(pieces):
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
        cuts: List[StockCut] = []
        for idx, segs in enumerate(bins, start=1):
            segs_sorted = sorted(segs, reverse=True)
            offcut = stock_length - sum(segs_sorted)
            cuts.append(StockCut(stock_id=idx, diameter=diameter,
                                 segments=segs_sorted, offcut=offcut))
        return DiameterPlan(diameter=diameter, stock_length=stock_length, cuts=cuts)


def group_lengths(entries: Iterable[Tuple[str, int, int]]) -> Dict[str, List[int]]:
    grouped: Dict[str, List[int]] = {}
    for diameter, length, quantity in entries:
        grouped.setdefault(diameter, []).extend([length] * quantity)
    return grouped


def optimize(grouped_lengths: Dict[str, List[int]],
             config: OptimizationConfig = DEFAULT_OPT_CONFIG,
             use_ilp: Optional[bool] = None) -> Dict[str, DiameterPlan]:
    optimizer = CuttingOptimizer(config)
    return optimizer.optimize(grouped_lengths, use_ilp=use_ilp)
