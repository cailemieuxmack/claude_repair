"""
Spectrum-Based Fault Localization (SBFL) implementation.

This module implements SBFL techniques for ranking source code lines
by their suspiciousness based on test execution coverage data.

Key concepts:
- Coverage is collected at the TEST CASE level (not iteration level)
- Each test case may have multiple iterations, but they run sequentially
- A test case passes only if ALL its iterations pass
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SuspiciousnessMetric(Enum):
    """Available suspiciousness metrics for SBFL."""
    OCHIAI = "ochiai"
    TARANTULA = "tarantula"
    DSTAR = "dstar"
    JACCARD = "jaccard"


@dataclass
class CoverageMatrix:
    """
    Coverage data at TEST CASE level.

    Attributes:
        coverage: Mapping from test case name to set of covered line numbers.
                  e.g., {"n1": {10, 20, 30}, "p1": {10, 20}}
        results: Mapping from test case name to pass/fail status.
                 e.g., {"n1": False, "p1": True}
        source_file: Path to the source file (for reference)
    """
    coverage: dict[str, set[int]] = field(default_factory=dict)
    results: dict[str, bool] = field(default_factory=dict)
    source_file: Optional[str] = None

    @property
    def all_lines(self) -> set[int]:
        """Union of all lines covered by any test case."""
        if not self.coverage:
            return set()
        return set().union(*self.coverage.values())

    @property
    def test_cases(self) -> list[str]:
        """List of all test case names."""
        return list(self.coverage.keys())

    @property
    def num_failing(self) -> int:
        """Number of failing test cases."""
        return sum(1 for passed in self.results.values() if not passed)

    @property
    def num_passing(self) -> int:
        """Number of passing test cases."""
        return sum(1 for passed in self.results.values() if passed)

    @property
    def failing_tests(self) -> list[str]:
        """List of failing test case names."""
        return [name for name, passed in self.results.items() if not passed]

    @property
    def passing_tests(self) -> list[str]:
        """List of passing test case names."""
        return [name for name, passed in self.results.items() if passed]

    def add_test_case(self, name: str, covered_lines: set[int], passed: bool) -> None:
        """Add a test case to the coverage matrix."""
        self.coverage[name] = covered_lines
        self.results[name] = passed

    def line_covered_by(self, line: int) -> list[str]:
        """Return list of test cases that cover the given line."""
        return [tc for tc, lines in self.coverage.items() if line in lines]

    def is_covered_by_failing(self, line: int) -> bool:
        """Check if the line is covered by at least one failing test."""
        return any(
            line in self.coverage.get(tc, set())
            for tc in self.failing_tests
        )


@dataclass
class SuspiciousnessScore:
    """A line's suspiciousness score with metadata."""
    line: int
    score: float
    source_text: str = ""
    ef: int = 0  # Number of failing tests executing this line
    ep: int = 0  # Number of passing tests executing this line
    nf: int = 0  # Number of failing tests NOT executing this line
    np: int = 0  # Number of passing tests NOT executing this line


class SBFLLocalizer:
    """
    Spectrum-based fault localization using test case coverage.

    This class computes suspiciousness scores for source code lines
    based on their correlation with test failures.
    """

    def __init__(
        self,
        matrix: CoverageMatrix,
        source_lines: Optional[dict[int, str]] = None,
        metric: SuspiciousnessMetric = SuspiciousnessMetric.OCHIAI
    ):
        """
        Initialize the localizer.

        Args:
            matrix: Coverage matrix with test case coverage and results
            source_lines: Optional mapping from line number to source text
            metric: Suspiciousness metric to use (default: Ochiai)
        """
        self.matrix = matrix
        self.source_lines = source_lines or {}
        self.metric = metric

        # Precompute totals
        self.total_failed = matrix.num_failing
        self.total_passed = matrix.num_passing

    def _compute_counts(self, line: int) -> tuple[int, int, int, int]:
        """
        Compute the four counts for a line.

        Returns:
            (ef, ep, nf, np) where:
            - ef: # failing tests executing line
            - ep: # passing tests executing line
            - nf: # failing tests NOT executing line
            - np: # passing tests NOT executing line
        """
        ef = 0  # failing tests that execute this line
        ep = 0  # passing tests that execute this line

        for tc_name, covered_lines in self.matrix.coverage.items():
            passed = self.matrix.results[tc_name]
            if line in covered_lines:
                if passed:
                    ep += 1
                else:
                    ef += 1

        nf = self.total_failed - ef
        np = self.total_passed - ep

        return ef, ep, nf, np

    def ochiai(self, line: int) -> float:
        """
        Compute Ochiai suspiciousness score for a line.

        Formula: ef / sqrt(total_failed * (ef + ep))

        Where:
            ef = # failing tests executing line
            ep = # passing tests executing line
            total_failed = total # of failing tests

        Returns value in [0, 1] where 1 is most suspicious.
        """
        ef, ep, nf, np = self._compute_counts(line)

        if self.total_failed == 0:
            return 0.0

        denominator = math.sqrt(self.total_failed * (ef + ep))

        if denominator == 0:
            return 0.0

        return ef / denominator

    def tarantula(self, line: int) -> float:
        """
        Compute Tarantula suspiciousness score for a line.

        Formula: (ef / total_failed) / ((ef / total_failed) + (ep / total_passed))

        Returns value in [0, 1] where 1 is most suspicious.
        """
        ef, ep, nf, np = self._compute_counts(line)

        if self.total_failed == 0:
            return 0.0

        fail_ratio = ef / self.total_failed

        if self.total_passed == 0:
            # If no passing tests, any executed line is suspicious
            return 1.0 if ef > 0 else 0.0

        pass_ratio = ep / self.total_passed

        denominator = fail_ratio + pass_ratio
        if denominator == 0:
            return 0.0

        return fail_ratio / denominator

    def dstar(self, line: int, star: int = 2) -> float:
        """
        Compute D* (DStar) suspiciousness score for a line.

        Formula: ef^* / (ep + nf)

        Where * is typically 2 or 3.

        Returns value >= 0 where higher is more suspicious.
        Note: Unlike Ochiai/Tarantula, this is not bounded to [0, 1].
        """
        ef, ep, nf, np = self._compute_counts(line)

        denominator = ep + nf
        if denominator == 0:
            # If no passing tests execute and no failing tests miss,
            # this line is very suspicious
            return float('inf') if ef > 0 else 0.0

        return (ef ** star) / denominator

    def jaccard(self, line: int) -> float:
        """
        Compute Jaccard suspiciousness score for a line.

        Formula: ef / (ef + nf + ep)

        Returns value in [0, 1] where 1 is most suspicious.
        """
        ef, ep, nf, np = self._compute_counts(line)

        denominator = ef + nf + ep
        if denominator == 0:
            return 0.0

        return ef / denominator

    def compute_score(self, line: int) -> float:
        """Compute suspiciousness score using the configured metric."""
        if self.metric == SuspiciousnessMetric.OCHIAI:
            return self.ochiai(line)
        elif self.metric == SuspiciousnessMetric.TARANTULA:
            return self.tarantula(line)
        elif self.metric == SuspiciousnessMetric.DSTAR:
            return self.dstar(line)
        elif self.metric == SuspiciousnessMetric.JACCARD:
            return self.jaccard(line)
        else:
            raise ValueError(f"Unknown metric: {self.metric}")

    def compute_all_scores(self) -> list[SuspiciousnessScore]:
        """
        Compute suspiciousness scores for all covered lines.

        Returns list of SuspiciousnessScore objects (unsorted).
        """
        scores = []

        for line in self.matrix.all_lines:
            ef, ep, nf, np = self._compute_counts(line)
            score = self.compute_score(line)
            source_text = self.source_lines.get(line, "")

            scores.append(SuspiciousnessScore(
                line=line,
                score=score,
                source_text=source_text,
                ef=ef,
                ep=ep,
                nf=nf,
                np=np
            ))

        return scores

    def rank_lines(self, top_n: Optional[int] = None) -> list[SuspiciousnessScore]:
        """
        Rank all lines by suspiciousness (descending).

        Args:
            top_n: If provided, return only the top N most suspicious lines.

        Returns:
            List of SuspiciousnessScore sorted by score (highest first).
            Ties are broken by line number (lower line number first).
        """
        scores = self.compute_all_scores()

        # Sort by score descending, then by line number ascending for ties
        scores.sort(key=lambda s: (-s.score, s.line))

        if top_n is not None:
            return scores[:top_n]

        return scores

    def get_suspicious_lines(
        self,
        threshold: float = 0.0,
        top_n: Optional[int] = None
    ) -> list[tuple[int, float, str]]:
        """
        Get suspicious lines as simple tuples.

        Args:
            threshold: Minimum score to include (default: 0.0 includes all)
            top_n: If provided, return only top N lines

        Returns:
            List of (line_number, score, source_text) tuples, sorted by score descending.
        """
        ranked = self.rank_lines(top_n=top_n)

        return [
            (s.line, s.score, s.source_text)
            for s in ranked
            if s.score >= threshold
        ]


def read_source_lines(source_path: str) -> dict[int, str]:
    """
    Read source file and return mapping from line number to text.

    Line numbers are 1-indexed to match gcov output.
    """
    lines = {}
    with open(source_path, 'r') as f:
        for i, line in enumerate(f, start=1):
            lines[i] = line.rstrip('\n')
    return lines
