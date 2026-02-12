#!/usr/bin/env python3
"""
Test script for SBFL (Spectrum-Based Fault Localization) implementation.

This script verifies the correctness of:
1. Ochiai formula computation
2. Other SBFL metrics (Tarantula, DStar, Jaccard)
3. Line ranking
4. Edge cases

Run with: python -m pytest tests/test_sbfl.py -v
Or directly: python tests/test_sbfl.py
"""

import math
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from apr_tool.localization.sbfl import (
    CoverageMatrix,
    SBFLLocalizer,
    SuspiciousnessMetric,
    SuspiciousnessScore,
    read_source_lines
)


def approx_equal(a: float, b: float, epsilon: float = 1e-6) -> bool:
    """Check if two floats are approximately equal."""
    return abs(a - b) < epsilon


class TestCoverageMatrix:
    """Tests for CoverageMatrix class."""

    def test_empty_matrix(self):
        """Test empty coverage matrix."""
        matrix = CoverageMatrix()
        assert matrix.all_lines == set()
        assert matrix.num_failing == 0
        assert matrix.num_passing == 0
        assert matrix.test_cases == []

    def test_add_test_case(self):
        """Test adding test cases to matrix."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20, 30}, False)
        matrix.add_test_case("p1", {10, 20}, True)

        assert matrix.test_cases == ["n1", "p1"]
        assert matrix.num_failing == 1
        assert matrix.num_passing == 1
        assert matrix.failing_tests == ["n1"]
        assert matrix.passing_tests == ["p1"]
        assert matrix.all_lines == {10, 20, 30}

    def test_line_covered_by(self):
        """Test finding which tests cover a line."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20, 30}, False)
        matrix.add_test_case("n2", {10, 30, 40}, False)
        matrix.add_test_case("p1", {10, 20}, True)

        assert set(matrix.line_covered_by(10)) == {"n1", "n2", "p1"}
        assert set(matrix.line_covered_by(20)) == {"n1", "p1"}
        assert set(matrix.line_covered_by(30)) == {"n1", "n2"}
        assert set(matrix.line_covered_by(40)) == {"n2"}
        assert matrix.line_covered_by(50) == []

    def test_is_covered_by_failing(self):
        """Test checking if line is covered by failing tests."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20}, False)
        matrix.add_test_case("p1", {10, 30}, True)

        assert matrix.is_covered_by_failing(10) == True
        assert matrix.is_covered_by_failing(20) == True
        assert matrix.is_covered_by_failing(30) == False


class TestOchiai:
    """Tests for Ochiai suspiciousness metric."""

    def test_ochiai_basic(self):
        """Test basic Ochiai computation."""
        # Setup: 2 failing tests, 2 passing tests
        # Line 10: covered by n1, n2, p1 (ef=2, ep=1)
        # Line 20: covered by n1 only (ef=1, ep=0)
        # Line 30: covered by p1 only (ef=0, ep=1)
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20}, False)
        matrix.add_test_case("n2", {10}, False)
        matrix.add_test_case("p1", {10, 30}, True)
        matrix.add_test_case("p2", {30}, True)

        localizer = SBFLLocalizer(matrix)

        # Line 10: ef=2, ep=1, total_failed=2
        # ochiai = 2 / sqrt(2 * 3) = 2 / sqrt(6) ≈ 0.8165
        score_10 = localizer.ochiai(10)
        expected_10 = 2 / math.sqrt(2 * 3)
        assert approx_equal(score_10, expected_10), f"Line 10: {score_10} != {expected_10}"

        # Line 20: ef=1, ep=0, total_failed=2
        # ochiai = 1 / sqrt(2 * 1) = 1 / sqrt(2) ≈ 0.7071
        score_20 = localizer.ochiai(20)
        expected_20 = 1 / math.sqrt(2 * 1)
        assert approx_equal(score_20, expected_20), f"Line 20: {score_20} != {expected_20}"

        # Line 30: ef=0, ep=2, total_failed=2
        # ochiai = 0 / sqrt(2 * 2) = 0
        score_30 = localizer.ochiai(30)
        assert approx_equal(score_30, 0.0), f"Line 30: {score_30} != 0.0"

    def test_ochiai_perfect_correlation(self):
        """Test Ochiai when line is covered by all and only failing tests."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20}, False)
        matrix.add_test_case("n2", {10, 20}, False)
        matrix.add_test_case("p1", {20}, True)
        matrix.add_test_case("p2", {20}, True)

        localizer = SBFLLocalizer(matrix)

        # Line 10: ef=2, ep=0, total_failed=2
        # ochiai = 2 / sqrt(2 * 2) = 2 / 2 = 1.0
        score = localizer.ochiai(10)
        assert approx_equal(score, 1.0), f"Perfect correlation should be 1.0, got {score}"

    def test_ochiai_no_failing_tests(self):
        """Test Ochiai when there are no failing tests."""
        matrix = CoverageMatrix()
        matrix.add_test_case("p1", {10, 20}, True)
        matrix.add_test_case("p2", {10, 30}, True)

        localizer = SBFLLocalizer(matrix)

        # No failing tests, all scores should be 0
        assert localizer.ochiai(10) == 0.0
        assert localizer.ochiai(20) == 0.0

    def test_ochiai_no_passing_tests(self):
        """Test Ochiai when there are no passing tests."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20}, False)
        matrix.add_test_case("n2", {10, 30}, False)

        localizer = SBFLLocalizer(matrix)

        # Line 10: ef=2, ep=0, total_failed=2
        # ochiai = 2 / sqrt(2 * 2) = 1.0
        score_10 = localizer.ochiai(10)
        assert approx_equal(score_10, 1.0)

        # Line 20: ef=1, ep=0, total_failed=2
        # ochiai = 1 / sqrt(2 * 1) ≈ 0.7071
        score_20 = localizer.ochiai(20)
        expected_20 = 1 / math.sqrt(2)
        assert approx_equal(score_20, expected_20)

    def test_ochiai_line_not_covered(self):
        """Test Ochiai for a line that's never executed."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20}, False)
        matrix.add_test_case("p1", {10}, True)

        localizer = SBFLLocalizer(matrix)

        # Line 99 is not covered by any test
        # ef=0, ep=0 -> denominator is 0 -> score is 0
        score = localizer.ochiai(99)
        assert score == 0.0


class TestTarantula:
    """Tests for Tarantula suspiciousness metric."""

    def test_tarantula_basic(self):
        """Test basic Tarantula computation."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20}, False)
        matrix.add_test_case("n2", {10}, False)
        matrix.add_test_case("p1", {10, 30}, True)
        matrix.add_test_case("p2", {30}, True)

        localizer = SBFLLocalizer(matrix, metric=SuspiciousnessMetric.TARANTULA)

        # Line 10: ef=2, ep=1, total_failed=2, total_passed=2
        # fail_ratio = 2/2 = 1.0
        # pass_ratio = 1/2 = 0.5
        # tarantula = 1.0 / (1.0 + 0.5) = 1.0 / 1.5 ≈ 0.6667
        score_10 = localizer.tarantula(10)
        expected_10 = 1.0 / 1.5
        assert approx_equal(score_10, expected_10), f"Line 10: {score_10} != {expected_10}"

        # Line 20: ef=1, ep=0
        # fail_ratio = 1/2 = 0.5
        # pass_ratio = 0/2 = 0
        # tarantula = 0.5 / 0.5 = 1.0
        score_20 = localizer.tarantula(20)
        assert approx_equal(score_20, 1.0), f"Line 20: {score_20} != 1.0"

        # Line 30: ef=0, ep=2
        # fail_ratio = 0
        # pass_ratio = 1.0
        # tarantula = 0 / 1.0 = 0
        score_30 = localizer.tarantula(30)
        assert approx_equal(score_30, 0.0), f"Line 30: {score_30} != 0.0"


class TestDStar:
    """Tests for D* suspiciousness metric."""

    def test_dstar_basic(self):
        """Test basic DStar computation."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20}, False)
        matrix.add_test_case("n2", {10}, False)
        matrix.add_test_case("p1", {10, 30}, True)
        matrix.add_test_case("p2", {30}, True)

        localizer = SBFLLocalizer(matrix, metric=SuspiciousnessMetric.DSTAR)

        # Line 10: ef=2, ep=1, nf=0
        # dstar = 2^2 / (1 + 0) = 4 / 1 = 4.0
        score_10 = localizer.dstar(10)
        assert approx_equal(score_10, 4.0), f"Line 10: {score_10} != 4.0"

        # Line 20: ef=1, ep=0, nf=1
        # dstar = 1^2 / (0 + 1) = 1 / 1 = 1.0
        score_20 = localizer.dstar(20)
        assert approx_equal(score_20, 1.0), f"Line 20: {score_20} != 1.0"


class TestJaccard:
    """Tests for Jaccard suspiciousness metric."""

    def test_jaccard_basic(self):
        """Test basic Jaccard computation."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20}, False)
        matrix.add_test_case("n2", {10}, False)
        matrix.add_test_case("p1", {10, 30}, True)
        matrix.add_test_case("p2", {30}, True)

        localizer = SBFLLocalizer(matrix, metric=SuspiciousnessMetric.JACCARD)

        # Line 10: ef=2, ep=1, nf=0
        # jaccard = 2 / (2 + 0 + 1) = 2/3 ≈ 0.6667
        score_10 = localizer.jaccard(10)
        expected_10 = 2 / 3
        assert approx_equal(score_10, expected_10), f"Line 10: {score_10} != {expected_10}"

        # Line 20: ef=1, ep=0, nf=1
        # jaccard = 1 / (1 + 1 + 0) = 1/2 = 0.5
        score_20 = localizer.jaccard(20)
        assert approx_equal(score_20, 0.5), f"Line 20: {score_20} != 0.5"


class TestRanking:
    """Tests for line ranking functionality."""

    def test_rank_lines_order(self):
        """Test that lines are ranked in descending order of suspiciousness."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20, 30}, False)
        matrix.add_test_case("n2", {10, 20}, False)
        matrix.add_test_case("p1", {10}, True)
        matrix.add_test_case("p2", {10}, True)

        localizer = SBFLLocalizer(matrix)
        ranked = localizer.rank_lines()

        # Verify descending order
        scores = [s.score for s in ranked]
        assert scores == sorted(scores, reverse=True), "Scores should be in descending order"

        # Calculate expected scores:
        # total_failed = 2, total_passed = 2
        #
        # Line 10: covered by n1, n2, p1, p2
        #   ef=2, ep=2 -> ochiai = 2/sqrt(2*4) = 2/sqrt(8) ≈ 0.707
        #
        # Line 20: covered by n1, n2 (not p1, p2)
        #   ef=2, ep=0 -> ochiai = 2/sqrt(2*2) = 1.0
        #
        # Line 30: covered by n1 only
        #   ef=1, ep=0 -> ochiai = 1/sqrt(2*1) ≈ 0.707

        # Order should be: 20 (1.0), then 10 and 30 (both ~0.707)
        # Ties broken by line number, so: 20, 10, 30
        assert ranked[0].line == 20
        assert approx_equal(ranked[0].score, 1.0)

        # Lines 10 and 30 have the same score (~0.707), sorted by line number
        assert ranked[1].line == 10
        assert ranked[2].line == 30
        assert approx_equal(ranked[1].score, ranked[2].score)

    def test_rank_lines_tie_breaking(self):
        """Test that ties are broken by line number (ascending)."""
        matrix = CoverageMatrix()
        # Create situation where lines 20 and 30 have the same score
        matrix.add_test_case("n1", {20, 30}, False)
        matrix.add_test_case("p1", {10}, True)

        localizer = SBFLLocalizer(matrix)
        ranked = localizer.rank_lines()

        # Lines 20 and 30 both have ef=1, ep=0
        # They should have the same score, with 20 coming before 30
        assert ranked[0].line == 20
        assert ranked[1].line == 30
        assert approx_equal(ranked[0].score, ranked[1].score)

    def test_rank_lines_top_n(self):
        """Test limiting results to top N lines."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20, 30, 40, 50}, False)
        matrix.add_test_case("p1", {10, 20}, True)

        localizer = SBFLLocalizer(matrix)
        ranked = localizer.rank_lines(top_n=3)

        assert len(ranked) == 3

    def test_get_suspicious_lines_threshold(self):
        """Test filtering by score threshold."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20, 30}, False)
        matrix.add_test_case("p1", {10, 20}, True)

        localizer = SBFLLocalizer(matrix)

        # Line 30 has highest score (ef=1, ep=0) -> ~0.707 (Ochiai with 1 failing)
        # Wait, total_failed=1, so:
        # Line 30: 1/sqrt(1*1) = 1.0
        # Line 20: 1/sqrt(1*2) ≈ 0.707
        # Line 10: 1/sqrt(1*2) ≈ 0.707

        suspicious = localizer.get_suspicious_lines(threshold=0.9)
        assert len(suspicious) == 1
        assert suspicious[0][0] == 30  # line number


class TestRealisticScenario:
    """Test with a scenario similar to the real use case."""

    def test_use_after_free_scenario(self):
        """
        Simulate fault localization for a use-after-free bug.

        Scenario:
        - Line 68: free(temp_buffer)  <- The free
        - Line 75: temp_buffer[0]     <- The use-after-free
        - Line 40: interpolate_point() <- Called but not buggy

        Failing tests (n1, n2) execute the buggy code path.
        Passing tests (p1, p2) don't trigger the vulnerability.
        """
        matrix = CoverageMatrix()

        # Failing tests execute the full buggy path
        matrix.add_test_case("n1", {
            32, 33, 36, 37, 40,  # interpolate_trajectory_point setup
            44, 45, 48, 49, 50,  # acceleration processing
            52, 53, 55, 56, 57,  # temp_buffer usage
            68,                   # free(temp_buffer) <- BUG
            71, 72, 75,           # use after free <- BUG
            78, 79, 83, 84,       # continued usage
            105, 107, 109         # step() return
        }, False)

        matrix.add_test_case("n2", {
            32, 33, 36, 37, 40,
            44, 45, 48, 49, 50,
            52, 53, 55, 56, 57,
            68,                   # free <- BUG
            71, 72, 75,           # use after free <- BUG
            78, 79, 83, 84,
            105, 107, 109
        }, False)

        # Passing tests don't trigger the vulnerable path
        # (maybe accelerations_length == 0 or effort_length == 0)
        matrix.add_test_case("p1", {
            32, 33, 36, 37, 40,  # interpolate_trajectory_point
            105, 107, 109        # step() return
        }, True)

        matrix.add_test_case("p2", {
            32, 33, 36, 37, 40,
            105, 107, 109
        }, True)

        localizer = SBFLLocalizer(matrix)

        # Lines only executed by failing tests (ef=2, ep=0):
        # {44, 45, 48, 49, 50, 52, 53, 55, 56, 57, 68, 71, 72, 75, 78, 79, 83, 84}
        # All have score 1.0, ties broken by line number (ascending)
        #
        # Lines executed by both passing and failing (ef=2, ep=2):
        # {32, 33, 36, 37, 40, 105, 107, 109}
        # These have score 2/sqrt(2*4) = 2/sqrt(8) ≈ 0.707

        ranked = localizer.rank_lines()

        # All lines only in failing tests should have score 1.0
        failing_only_lines = {44, 45, 48, 49, 50, 52, 53, 55, 56, 57, 68, 71, 72, 75, 78, 79, 83, 84}
        for score in ranked:
            if score.line in failing_only_lines:
                assert approx_equal(score.score, 1.0), \
                    f"Line {score.line} should have score 1.0, got {score.score}"

        # The buggy lines (68, 75) should have score 1.0
        buggy_lines = {68, 75}
        for score in ranked:
            if score.line in buggy_lines:
                assert approx_equal(score.score, 1.0), \
                    f"Buggy line {score.line} should have score 1.0, got {score.score}"

        # Lines executed by both should have lower scores
        common_lines = {32, 33, 36, 37, 40, 105, 107, 109}
        for score in ranked:
            if score.line in common_lines:
                assert score.score < 1.0, \
                    f"Common line {score.line} should have score < 1.0, got {score.score}"

        # Verify that all top-scoring lines (score 1.0) come before lower-scoring lines
        scores_list = [s.score for s in ranked]
        high_score_count = sum(1 for s in scores_list if approx_equal(s, 1.0))
        assert high_score_count == len(failing_only_lines), \
            f"Expected {len(failing_only_lines)} lines with score 1.0, got {high_score_count}"

        # The first N lines should all have score 1.0
        for i in range(high_score_count):
            assert approx_equal(ranked[i].score, 1.0), \
                f"Rank {i} should have score 1.0, got {ranked[i].score}"

    def test_with_source_lines(self):
        """Test that source text is included in results."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {1, 2, 3}, False)
        matrix.add_test_case("p1", {1, 2}, True)

        source_lines = {
            1: "int x = 0;",
            2: "x = x + 1;",
            3: "free(buffer);  // BUG"
        }

        localizer = SBFLLocalizer(matrix, source_lines=source_lines)
        ranked = localizer.rank_lines()

        # Check that source text is included
        for score in ranked:
            assert score.source_text == source_lines[score.line]

        # Line 3 should be most suspicious and contain "BUG"
        assert ranked[0].line == 3
        assert "BUG" in ranked[0].source_text


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_coverage(self):
        """Test with no coverage data."""
        matrix = CoverageMatrix()
        localizer = SBFLLocalizer(matrix)

        ranked = localizer.rank_lines()
        assert ranked == []

    def test_single_test_failing(self):
        """Test with only one failing test."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10, 20, 30}, False)

        localizer = SBFLLocalizer(matrix)
        ranked = localizer.rank_lines()

        # All lines should have score 1.0 (ef=1, ep=0, total_failed=1)
        for score in ranked:
            assert approx_equal(score.score, 1.0)

    def test_single_test_passing(self):
        """Test with only one passing test."""
        matrix = CoverageMatrix()
        matrix.add_test_case("p1", {10, 20, 30}, True)

        localizer = SBFLLocalizer(matrix)
        ranked = localizer.rank_lines()

        # All scores should be 0 (no failing tests)
        for score in ranked:
            assert score.score == 0.0

    def test_compute_score_with_different_metrics(self):
        """Test that compute_score uses the configured metric."""
        matrix = CoverageMatrix()
        matrix.add_test_case("n1", {10}, False)
        matrix.add_test_case("p1", {10}, True)

        for metric in SuspiciousnessMetric:
            localizer = SBFLLocalizer(matrix, metric=metric)
            score = localizer.compute_score(10)
            assert isinstance(score, float)


def run_tests():
    """Run all tests and report results."""
    import traceback

    test_classes = [
        TestCoverageMatrix,
        TestOchiai,
        TestTarantula,
        TestDStar,
        TestJaccard,
        TestRanking,
        TestRealisticScenario,
        TestEdgeCases,
    ]

    total_tests = 0
    passed_tests = 0
    failed_tests = []

    for test_class in test_classes:
        print(f"\n{'='*60}")
        print(f"Running {test_class.__name__}")
        print('='*60)

        instance = test_class()
        test_methods = [m for m in dir(instance) if m.startswith('test_')]

        for method_name in test_methods:
            total_tests += 1
            method = getattr(instance, method_name)

            try:
                method()
                print(f"  ✓ {method_name}")
                passed_tests += 1
            except AssertionError as e:
                print(f"  ✗ {method_name}")
                print(f"    AssertionError: {e}")
                failed_tests.append((test_class.__name__, method_name, str(e)))
            except Exception as e:
                print(f"  ✗ {method_name}")
                print(f"    {type(e).__name__}: {e}")
                traceback.print_exc()
                failed_tests.append((test_class.__name__, method_name, str(e)))

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed_tests}/{total_tests} tests passed")
    print('='*60)

    if failed_tests:
        print("\nFailed tests:")
        for class_name, method_name, error in failed_tests:
            print(f"  - {class_name}.{method_name}: {error}")
        return 1
    else:
        print("\nAll tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(run_tests())
