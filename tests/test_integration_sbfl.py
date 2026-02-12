#!/usr/bin/env python3
"""
Integration test for SBFL with actual controller.c coverage collection.

This test:
1. Compiles controller.c with gcov instrumentation
2. Runs a simulated test (without full IPC)
3. Generates gcov data
4. Parses coverage
5. Runs SBFL

Since we can't easily run the full IPC-based test without numpy,
we'll create a simpler test that directly calls the controller functions.
"""

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apr_tool.coverage.gcov_parser import GcovParser
from apr_tool.localization.sbfl import CoverageMatrix, SBFLLocalizer, read_source_lines


def create_simple_test_driver():
    """Create a simple test driver that exercises the controller code paths."""
    return '''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern "C" {
    #include "../controller.h"
}

// Simulate different test scenarios
int run_test(int test_num) {
    // Initialize
    init();

    // Create input data
    in->cur_time_seconds = 1;
    in->value.points_length = 10;

    // Set up trajectory points
    for (int i = 0; i < 10; i++) {
        in->value.points[i].positions_length = 6;
        in->value.points[i].velocities_length = 6;
        in->value.points[i].time_from_start_sec = i;
        in->value.points[i].time_from_start_nsec = 0;

        for (int j = 0; j < 6; j++) {
            in->value.points[i].positions[j] = (double)(i * 10 + j);
            in->value.points[i].velocities[j] = (double)(i + j) * 0.1;
        }

        // For tests n1, n2: set accelerations and effort to trigger the buggy path
        if (test_num == 1 || test_num == 2) {
            in->value.points[i].accelerations_length = 10;
            in->value.points[i].accelerations[0] = 5.0;  // buffer_size
            for (int j = 2; j < 10; j++) {
                in->value.points[i].accelerations[j] = (double)j;
            }

            in->value.points[i].effort_length = 10;
            in->value.points[i].effort[0] = 5.0;  // buffer_size
            for (int j = 2; j < 10; j++) {
                in->value.points[i].effort[j] = (double)(j * 2);
            }
        } else {
            // For tests p1, p2: don't trigger the buggy path
            in->value.points[i].accelerations_length = 0;
            in->value.points[i].effort_length = 0;
        }
    }

    // Run step
    step();

    // For this test, we just check it runs without crashing
    // (The real bug is use-after-free which may not crash immediately)
    printf("Test %d completed, output position[0] = %f\\n",
           test_num, out->vote.positions[0]);

    // Note: We intentionally don't clean up here to keep it simple
    // The real cleanup would be more complex since point_interp is internal
    // For test purposes, we just let the process exit

    return 0;
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <test_num>\\n", argv[0]);
        return 1;
    }

    int test_num = atoi(argv[1]);
    return run_test(test_num);
}
'''


def test_coverage_collection():
    """Test that we can collect coverage from controller.c"""

    # Create temp directory
    workdir = Path(tempfile.mkdtemp(prefix="sbfl_test_"))
    print(f"Working directory: {workdir}")

    try:
        # Set up directory structure
        source_dir = workdir / "source"
        source_dir.mkdir()

        # Copy files
        test_examples = Path("/workspace/test_examples")
        shutil.copy(test_examples / "controller.h", workdir / "controller.h")
        shutil.copy(test_examples / "controller.c", source_dir / "controller.c")

        # Write simple test driver
        driver_path = source_dir / "simple_driver.cpp"
        driver_path.write_text(create_simple_test_driver())

        # Compile with coverage
        compile_cmd = (
            f"gcc -g -fprofile-arcs -ftest-coverage -c {source_dir}/controller.c "
            f"-I{workdir} -o {source_dir}/controller.o"
        )
        print(f"Compiling controller.c...")
        result = subprocess.run(compile_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Compile error: {result.stderr}")
            return False

        compile_cmd = (
            f"g++ -g -fprofile-arcs -ftest-coverage -c {source_dir}/simple_driver.cpp "
            f"-I{workdir} -o {source_dir}/simple_driver.o"
        )
        result = subprocess.run(compile_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Compile error: {result.stderr}")
            return False

        link_cmd = (
            f"g++ -g -fprofile-arcs -ftest-coverage "
            f"-o {source_dir}/test_runner {source_dir}/simple_driver.o {source_dir}/controller.o"
        )
        result = subprocess.run(link_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Link error: {result.stderr}")
            return False

        print("Compilation successful!")

        # Run tests and collect coverage
        coverage_matrix = CoverageMatrix(source_file=str(source_dir / "controller.c"))
        parser = GcovParser()

        test_cases = [
            ("n1", 1, False),  # Failing test - triggers buggy path
            ("n2", 2, False),  # Failing test - triggers buggy path
            ("p1", 3, True),   # Passing test - doesn't trigger bug
            ("p2", 4, True),   # Passing test - doesn't trigger bug
        ]

        for test_name, test_num, expected_pass in test_cases:
            print(f"\nRunning test {test_name}...")

            # Clean gcda files
            for gcda in source_dir.glob("*.gcda"):
                gcda.unlink()

            # Run test
            run_cmd = f"{source_dir}/test_runner {test_num}"
            result = subprocess.run(
                run_cmd, shell=True, capture_output=True, text=True,
                cwd=source_dir
            )
            print(f"  Output: {result.stdout.strip()}")
            if result.returncode != 0:
                print(f"  Error: {result.stderr}")

            # Generate gcov
            gcov_cmd = f"gcov controller.c"
            result = subprocess.run(
                gcov_cmd, shell=True, capture_output=True, text=True,
                cwd=source_dir
            )

            # Parse coverage
            gcov_file = source_dir / "controller.c.gcov"
            if gcov_file.exists():
                covered_lines = parser.get_executed_lines(gcov_file)
                print(f"  Covered {len(covered_lines)} lines")
                coverage_matrix.add_test_case(test_name, covered_lines, expected_pass)
            else:
                print(f"  No gcov file generated!")
                return False

        # Now run SBFL
        print("\n" + "="*60)
        print("SBFL Analysis")
        print("="*60)

        # Read source for annotation
        source_lines = read_source_lines(source_dir / "controller.c")

        localizer = SBFLLocalizer(coverage_matrix, source_lines)
        ranked = localizer.rank_lines(top_n=20)

        print(f"\nTotal failing tests: {coverage_matrix.num_failing}")
        print(f"Total passing tests: {coverage_matrix.num_passing}")
        print(f"\nTop 20 suspicious lines:")
        print("-" * 80)

        for i, score in enumerate(ranked[:20], 1):
            code = score.source_text.strip()[:50]
            print(f"{i:2}. Line {score.line:3}: {score.score:.3f} | {code}")

        # Verify the buggy lines are highly ranked
        # Lines 68 (free) and 75 (use-after-free) should be suspicious
        top_lines = {s.line for s in ranked[:15]}

        # The bug is around lines 68 and 75
        # Let's check if any lines in that region are flagged
        buggy_region = set(range(65, 90))  # Lines around the bug
        flagged_buggy = top_lines & buggy_region

        print(f"\nBuggy region lines (65-90) in top 15: {sorted(flagged_buggy)}")

        if flagged_buggy:
            print("\n✓ SBFL successfully identified suspicious lines in the buggy region!")
            return True
        else:
            print("\n✗ SBFL did not flag the buggy region")
            # This might happen if the test doesn't properly trigger the different paths
            return False

    finally:
        # Cleanup
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    print("="*60)
    print("Integration Test: SBFL with Real Controller Code")
    print("="*60)

    try:
        success = test_coverage_collection()
        if success:
            print("\n" + "="*60)
            print("Integration test PASSED")
            print("="*60)
            return 0
        else:
            print("\n" + "="*60)
            print("Integration test FAILED")
            print("="*60)
            return 1
    except Exception as e:
        print(f"\nTest failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
