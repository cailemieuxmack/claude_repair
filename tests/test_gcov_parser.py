#!/usr/bin/env python3
"""
Test script for gcov parser.

Run with: python -m pytest tests/test_gcov_parser.py -v
Or directly: python tests/test_gcov_parser.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apr_tool.coverage.gcov_parser import GcovParser, GcovLine


class TestGcovParser:
    """Tests for GcovParser class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = GcovParser()

    def test_parse_executed_line(self):
        """Test parsing a line that was executed."""
        # Create a temporary gcov file
        gcov_content = """\
        -:    0:Source:test.c
        -:    1:#include <stdio.h>
        1:    2:int main() {
       10:    3:    for (int i = 0; i < 10; i++) {
       10:    4:        printf("hello\\n");
        -:    5:    }
        1:    6:    return 0;
        -:    7:}
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gcov', delete=False) as f:
            f.write(gcov_content)
            gcov_path = Path(f.name)

        try:
            lines = self.parser.parse_file(gcov_path)

            # Check line 2 (executed once)
            line2 = next(l for l in lines if l.line_number == 2)
            assert line2.execution_count == 1
            assert line2.is_executable == True
            assert line2.was_executed == True

            # Check line 3 (executed 10 times)
            line3 = next(l for l in lines if l.line_number == 3)
            assert line3.execution_count == 10

            # Check line 5 (non-executable - closing brace)
            line5 = next(l for l in lines if l.line_number == 5)
            assert line5.execution_count is None
            assert line5.is_executable == False

        finally:
            gcov_path.unlink()

    def test_parse_not_executed_line(self):
        """Test parsing a line that was not executed (####)."""
        gcov_content = """\
        -:    0:Source:test.c
        1:    1:int foo(int x) {
    #####:    2:    if (x < 0) {
    #####:    3:        return -1;
        -:    4:    }
        1:    5:    return x;
        -:    6:}
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gcov', delete=False) as f:
            f.write(gcov_content)
            gcov_path = Path(f.name)

        try:
            lines = self.parser.parse_file(gcov_path)

            # Line 2 is executable but not executed
            line2 = next(l for l in lines if l.line_number == 2)
            assert line2.execution_count == 0
            assert line2.is_executable == True
            assert line2.was_executed == False

        finally:
            gcov_path.unlink()

    def test_get_executed_lines(self):
        """Test getting set of executed line numbers."""
        gcov_content = """\
        -:    0:Source:test.c
        1:    1:int x = 0;
    #####:    2:int y = 1;
        5:    3:int z = 2;
        -:    4:// comment
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gcov', delete=False) as f:
            f.write(gcov_content)
            gcov_path = Path(f.name)

        try:
            executed = self.parser.get_executed_lines(gcov_path)
            assert executed == {1, 3}

        finally:
            gcov_path.unlink()

    def test_get_executable_lines(self):
        """Test getting set of executable line numbers."""
        gcov_content = """\
        -:    0:Source:test.c
        1:    1:int x = 0;
    #####:    2:int y = 1;
        5:    3:int z = 2;
        -:    4:// comment
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gcov', delete=False) as f:
            f.write(gcov_content)
            gcov_path = Path(f.name)

        try:
            executable = self.parser.get_executable_lines(gcov_path)
            assert executable == {1, 2, 3}

        finally:
            gcov_path.unlink()

    def test_get_not_executed_lines(self):
        """Test getting executable lines that were not executed."""
        gcov_content = """\
        -:    0:Source:test.c
        1:    1:int x = 0;
    #####:    2:int y = 1;
        5:    3:int z = 2;
    #####:    4:int w = 3;
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gcov', delete=False) as f:
            f.write(gcov_content)
            gcov_path = Path(f.name)

        try:
            not_executed = self.parser.get_not_executed_lines(gcov_path)
            assert not_executed == {2, 4}

        finally:
            gcov_path.unlink()

    def test_real_gcov_format(self):
        """Test with realistic gcov output format."""
        gcov_content = """\
        -:    0:Source:controller.c
        -:    0:Graph:controller.gcno
        -:    0:Data:controller.gcda
        -:    0:Runs:1
        -:    1:#include "controller.h"
        -:    2:#include <stdio.h>
        -:    3:#include <stdlib.h>
        -:    4:
        -:    5:#define MIN(a, b) ((a) < (b) ? (a) : (b))
        -:    6:
        -:    7:InStruct *in;
        -:    8:OutStruct *out;
        -:    9:MappedJointTrajectoryPoint *point_interp;
        -:   10:static double *temp_buffer = NULL;
        -:   11:
        2:   12:void interpolate_point(
        -:   13:    const MappedJointTrajectoryPoint point_1,
        -:   14:    const MappedJointTrajectoryPoint point_2,
        -:   15:    MappedJointTrajectoryPoint * point_interp, double delta)
        -:   16:{
       12:   17:    for (size_t i = 0; i < point_1.positions_length; i++)
        -:   18:    {
       12:   19:        point_interp->positions[i] = delta * point_2.positions[i] + (1.0 - delta) * point_1.positions[i];
        -:   20:    }
       12:   21:    for (size_t i = 0; i < point_1.positions_length; i++)
        -:   22:    {
       12:   23:        point_interp->velocities[i] = delta * point_2.velocities[i] + (1.0 - delta) * point_1.velocities[i];
        -:   24:    }
        -:   25:
        2:   26:}
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gcov', delete=False) as f:
            f.write(gcov_content)
            gcov_path = Path(f.name)

        try:
            executed = self.parser.get_executed_lines(gcov_path)

            # Should include executed code lines
            assert 12 in executed  # function definition
            assert 17 in executed  # for loop
            assert 19 in executed  # interpolation
            assert 21 in executed  # second for loop
            assert 23 in executed  # second interpolation
            assert 26 in executed  # function end

            # Should not include non-executable lines
            assert 1 not in executed   # include
            assert 5 not in executed   # define
            assert 10 not in executed  # static variable

        finally:
            gcov_path.unlink()


def run_tests():
    """Run all tests and report results."""
    test_class = TestGcovParser()
    test_methods = [m for m in dir(test_class) if m.startswith('test_')]

    total = len(test_methods)
    passed = 0
    failed = []

    print(f"Running {total} gcov parser tests...\n")

    for method_name in test_methods:
        test_class.setup_method()
        method = getattr(test_class, method_name)

        try:
            method()
            print(f"  ✓ {method_name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {method_name}: {e}")
            failed.append((method_name, str(e)))

    print(f"\nResults: {passed}/{total} tests passed")

    if failed:
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}: {error}")
        return 1

    print("\nAll tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
