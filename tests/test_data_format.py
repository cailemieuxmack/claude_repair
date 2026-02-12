#!/usr/bin/env python3
"""
Tests for the data format module.

Run with: python tests/test_data_format.py
"""

import sys
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apr_tool.testing.data_format import (
    POINT_FORMAT, VOTE_FORMAT,
    VOTE_SIZE, Vote,
    parse_vote, parse_vote_file,
)

POINT_SIZE = struct.calcsize(POINT_FORMAT)


class TestFormatSizes:
    """Tests for struct format sizes."""

    def test_point_size(self):
        # 4*Q(8) + 4*100d(800) + i(4) + I(4) = 32 + 3200 + 8 = 3240
        assert POINT_SIZE == 3240

    def test_vote_size(self):
        # i(4) + 4 padding (Q needs 8-byte alignment) + POINT_SIZE
        assert VOTE_SIZE == 8 + POINT_SIZE


class TestVote:
    """Tests for Vote parsing."""

    def _make_vote_tuple(self, idx=0, positions=None, velocities=None):
        """Build a 407-element tuple for packing into VOTE_FORMAT."""
        data = [0] * 407
        data[0] = idx
        data[1] = 6  # positions_length
        if positions:
            for i, v in enumerate(positions):
                data[2 + i] = v
        data[102] = 6  # velocities_length
        if velocities:
            for i, v in enumerate(velocities):
                data[103 + i] = v
        # int fields that struct.pack needs as ints
        data[203] = 0  # accelerations_length
        data[304] = 0  # effort_length
        data[405] = 0  # time_from_start_sec
        data[406] = 0  # time_from_start_nsec
        return data

    def test_parse_vote_from_bytes(self):
        data = self._make_vote_tuple(idx=123, positions=[3.14])
        binary = struct.pack(VOTE_FORMAT, *data)
        vote = parse_vote(binary)

        assert vote.idx == 123
        assert abs(vote.positions[0] - 3.14) < 0.0001

    def test_get_comparison_vector(self):
        pos = [float(i + 1) for i in range(6)]
        vel = [float(i + 1) * 0.1 for i in range(6)]
        data = self._make_vote_tuple(idx=1, positions=pos, velocities=vel)
        binary = struct.pack(VOTE_FORMAT, *data)
        vote = parse_vote(binary)

        vec = vote.get_comparison_vector(6)
        assert len(vec) == 12
        assert vec[:6] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        for i in range(6):
            assert abs(vec[6 + i] - (i + 1) * 0.1) < 0.0001


class TestRealDataFiles:
    """Tests using actual test data files."""

    def test_parse_real_vote_file(self):
        test_file = Path("/workspace/test_examples/test/n1/output.t1")
        if not test_file.exists():
            print("  (skipping - test file not found)")
            return

        vote = parse_vote_file(test_file)

        assert isinstance(vote.idx, int)
        assert len(vote.positions) == 100
        assert len(vote.velocities) == 100

        vec = vote.get_comparison_vector()
        assert len(vec) == 12

        print(f"    Parsed vote: idx={vote.idx}")
        print(f"    First 3 positions: {tuple(vote.positions[:3])}")
        print(f"    First 3 velocities: {tuple(vote.velocities[:3])}")

    def test_vote_file_size(self):
        test_file = Path("/workspace/test_examples/test/n1/output.t1")
        if not test_file.exists():
            print("  (skipping - test file not found)")
            return

        assert test_file.stat().st_size == VOTE_SIZE

    def test_state_file_size(self):
        test_file = Path("/workspace/test_examples/test/n1/t1")
        if not test_file.exists():
            print("  (skipping - test file not found)")
            return

        actual_size = test_file.stat().st_size
        assert 800000 < actual_size < 900000


def run_tests():
    """Run all tests and report results."""
    test_classes = [
        TestFormatSizes,
        TestVote,
        TestRealDataFiles,
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
                import traceback
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
