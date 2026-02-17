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
    POINT_FORMAT, VOTE_FORMAT, POINT_SIZE,
    VOTE_SIZE, Vote,
    parse_vote, parse_vote_file,
    TrajectoryPoint, State,
    parse_state, parse_state_file,
    format_state_text,
)

POINT_SIZE_CALC = struct.calcsize(POINT_FORMAT)


class TestFormatSizes:
    """Tests for struct format sizes."""

    def test_point_size(self):
        # 4*Q(8) + 4*100d(800) + i(4) + I(4) = 32 + 3200 + 8 = 3240
        assert POINT_SIZE_CALC == 3240
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

    def test_point_size_constant(self):
        assert POINT_SIZE == POINT_SIZE_CALC

    def test_state_file_size(self):
        test_file = Path("/workspace/test_examples/test/n1/t1")
        if not test_file.exists():
            print("  (skipping - test file not found)")
            return

        actual_size = test_file.stat().st_size
        assert 800000 < actual_size < 900000


class TestStateParsing:
    """Tests for State parsing from real binary files."""

    STATE_FILE = Path("/workspace/test_examples/test/n1/t1")

    def test_parse_state_file(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        state = parse_state_file(self.STATE_FILE)

        assert isinstance(state, State)
        assert isinstance(state.idx, int)
        assert isinstance(state.cur_time_seconds, int)
        assert isinstance(state.joint_names, list)
        assert isinstance(state.points_length, int)
        assert isinstance(state.points, list)

    def test_state_idx(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        state = parse_state_file(self.STATE_FILE)
        # idx should be a small non-negative integer for the first iteration
        assert state.idx >= 0

    def test_state_joint_names(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        state = parse_state_file(self.STATE_FILE)
        # Should have joint names (typically 6 for a robot arm)
        assert len(state.joint_names) > 0
        assert len(state.joint_names) <= 10
        # Each name should be a non-empty ASCII string
        for name in state.joint_names:
            assert isinstance(name, str)
            assert len(name) > 0

    def test_state_points_length(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        state = parse_state_file(self.STATE_FILE)
        assert state.points_length > 0
        assert state.points_length <= 256
        assert len(state.points) == state.points_length

    def test_state_trajectory_point_fields(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        state = parse_state_file(self.STATE_FILE)
        assert len(state.points) > 0

        pt = state.points[0]
        assert isinstance(pt, TrajectoryPoint)
        assert pt.positions_length >= 0
        assert pt.positions_length <= 100
        assert len(pt.positions) == pt.positions_length
        assert pt.velocities_length >= 0
        assert pt.velocities_length <= 100
        assert len(pt.velocities) == pt.velocities_length
        assert pt.accelerations_length >= 0
        assert pt.accelerations_length <= 100
        assert len(pt.accelerations) == pt.accelerations_length
        assert pt.effort_length >= 0
        assert pt.effort_length <= 100
        assert len(pt.effort) == pt.effort_length

    def test_state_point_values_are_finite(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        import math
        state = parse_state_file(self.STATE_FILE)
        pt = state.points[0]
        for v in pt.positions:
            assert math.isfinite(v), f"Non-finite position value: {v}"
        for v in pt.velocities:
            assert math.isfinite(v), f"Non-finite velocity value: {v}"


class TestFormatStateText:
    """Tests for format_state_text()."""

    STATE_FILE = Path("/workspace/test_examples/test/n1/t1")

    def test_format_produces_nonempty_string(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        state = parse_state_file(self.STATE_FILE)
        text = format_state_text(state)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_format_contains_key_fields(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        state = parse_state_file(self.STATE_FILE)
        text = format_state_text(state)
        assert "idx:" in text
        assert "cur_time_seconds:" in text
        assert "joint_names" in text
        assert "points_length:" in text
        assert "point[0]:" in text

    def test_format_contains_point_data(self):
        if not self.STATE_FILE.exists():
            print("  (skipping - test file not found)")
            return

        state = parse_state_file(self.STATE_FILE)
        text = format_state_text(state)
        assert "positions(" in text
        assert "velocities(" in text
        assert "accelerations(" in text
        assert "effort(" in text
        assert "time=" in text


def run_tests():
    """Run all tests and report results."""
    test_classes = [
        TestFormatSizes,
        TestVote,
        TestRealDataFiles,
        TestStateParsing,
        TestFormatStateText,
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
