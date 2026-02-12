#!/usr/bin/env python3
"""
Tests for the validator module.

Run with: python tests/test_validator.py
"""

import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apr_tool.testing.validator import (
    cosine_distance,
    validate_iteration,
    ValidationResult,
)
from apr_tool.testing.data_format import Vote


def approx_equal(a: float, b: float, epsilon: float = 1e-6) -> bool:
    return abs(a - b) < epsilon


class TestCosineDistance:
    """Tests for cosine distance calculation."""

    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert approx_equal(cosine_distance(v, v), 0.0)

    def test_opposite_vectors(self):
        assert approx_equal(cosine_distance([1.0, 0.0], [-1.0, 0.0]), 2.0)

    def test_orthogonal_vectors(self):
        assert approx_equal(cosine_distance([1.0, 0.0], [0.0, 1.0]), 1.0)

    def test_both_zero_vectors(self):
        assert cosine_distance([0.0, 0.0], [0.0, 0.0]) == 0.0

    def test_one_zero_vector(self):
        assert cosine_distance([1.0, 2.0], [0.0, 0.0]) == 1.0

    def test_similar_vectors(self):
        assert cosine_distance([1.0, 2.0, 3.0], [1.1, 2.1, 3.1]) < 0.01

    def test_scaled_vectors(self):
        assert approx_equal(cosine_distance([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]), 0.0)


def _create_vote(idx, positions, velocities):
    """Helper to create a Vote with specific values, padded to 100."""
    positions = positions + [0.0] * (100 - len(positions))
    velocities = velocities + [0.0] * (100 - len(velocities))
    return Vote(idx=idx, positions=positions, velocities=velocities)


class TestValidation:
    """Tests for iteration validation."""

    def test_validation_pass_identical(self):
        pos = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        vel = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        result = validate_iteration(_create_vote(1, pos, vel), _create_vote(1, pos, vel))
        assert result.passed
        assert "PASS" in str(result)

    def test_validation_fail_index_mismatch(self):
        pos = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        vel = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        result = validate_iteration(_create_vote(1, pos, vel), _create_vote(2, pos, vel))
        assert not result.passed
        assert "index mismatch" in str(result)

    def test_validation_pass_within_epsilon(self):
        controller = _create_vote(1, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        oracle = _create_vote(1, [1.1, 2.1, 3.1, 4.1, 5.1, 6.1], [0.11, 0.21, 0.31, 0.41, 0.51, 0.61])
        result = validate_iteration(controller, oracle, epsilon=0.5)
        assert result.passed

    def test_validation_fail_exceeds_epsilon(self):
        controller = _create_vote(1, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0]*6)
        oracle = _create_vote(1, [0.0, 1.0, 0.0, 0.0, 0.0, 0.0], [0.0]*6)
        result = validate_iteration(controller, oracle, epsilon=0.5)
        assert not result.passed
        assert "cosine_distance" in str(result)

    def test_validation_uses_first_six_joints(self):
        controller = _create_vote(1, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 100.0], [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 10.0])
        oracle = _create_vote(1, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0], [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.0])
        result = validate_iteration(controller, oracle, num_joints=6)
        assert result.passed


class TestValidationResult:
    """Tests for ValidationResult formatting."""

    def test_str_pass(self):
        s = str(ValidationResult(True, "PASS (distance=0.1000)"))
        assert "PASS" in s
        assert "0.1" in s

    def test_str_fail_index(self):
        s = str(ValidationResult(False, "FAIL: index mismatch (1 != 2)"))
        assert "FAIL" in s
        assert "index" in s.lower()

    def test_str_fail_distance(self):
        s = str(ValidationResult(False, "FAIL: cosine_distance=0.7000 > 0.5"))
        assert "FAIL" in s
        assert "0.7" in s


def run_tests():
    """Run all tests and report results."""
    test_classes = [
        TestCosineDistance,
        TestValidation,
        TestValidationResult,
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
                print(f"  \u2713 {method_name}")
                passed_tests += 1
            except AssertionError as e:
                print(f"  \u2717 {method_name}")
                print(f"    AssertionError: {e}")
                failed_tests.append((test_class.__name__, method_name, str(e)))
            except Exception as e:
                print(f"  \u2717 {method_name}")
                print(f"    {type(e).__name__}: {e}")
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
