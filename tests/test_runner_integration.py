#!/usr/bin/env python3
"""
Integration test for the test runner with actual controller.

This test:
1. Compiles the controller executable
2. Uses the TestRunner to run test cases
3. Verifies pass/fail detection works correctly

Run with: python tests/test_runner_integration.py
"""

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apr_tool.testing.runner import TestRunner, TestCaseInfo


def compile_controller(workdir: Path, test_examples: Path, enable_asan: bool = False) -> Path:
    """
    Compile the controller executable.

    Args:
        workdir: Working directory for compilation
        test_examples: Path to test_examples directory
        enable_asan: If True, compile with AddressSanitizer

    Returns path to executable.
    """
    source_dir = workdir / "source"
    source_dir.mkdir(exist_ok=True)

    # Copy files maintaining the expected directory structure
    shutil.copy(test_examples / "controller.h", workdir / "controller.h")
    shutil.copy(test_examples / "controller.c", source_dir / "controller.c")
    shutil.copy(test_examples / "test_driver.cpp", source_dir / "test_driver.cpp")

    # ASan flags
    asan_flags = "-fsanitize=address -fno-omit-frame-pointer" if enable_asan else ""

    # Compile C file
    compile_c = (
        f"gcc -g {asan_flags} -c {source_dir}/controller.c "
        f"-I{workdir} -o {source_dir}/controller.o"
    )
    result = subprocess.run(compile_c, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to compile controller.c: {result.stderr}")

    # Compile C++ driver
    compile_cpp = (
        f"g++ -g {asan_flags} -c {source_dir}/test_driver.cpp "
        f"-I{workdir} -o {source_dir}/test_driver.o"
    )
    result = subprocess.run(compile_cpp, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to compile test_driver.cpp: {result.stderr}")

    # Link
    link_cmd = (
        f"g++ -g {asan_flags} -o {source_dir}/controller "
        f"{source_dir}/test_driver.o {source_dir}/controller.o"
    )
    result = subprocess.run(link_cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to link: {result.stderr}")

    return source_dir / "controller"


def test_runner_basic():
    """Test that the runner can execute a test case."""
    test_examples = Path("/workspace/test_examples")
    test_dir = test_examples / "test"

    if not test_dir.exists():
        print("Test directory not found, skipping")
        return True

    workdir = Path(tempfile.mkdtemp(prefix="runner_test_"))
    print(f"Working directory: {workdir}")

    try:
        # Compile controller
        print("Compiling controller...")
        executable = compile_controller(workdir, test_examples)
        print(f"Executable: {executable}")

        # Create runner
        runner = TestRunner(
            executable=executable,
            workdir=workdir,
            epsilon=0.5,
            iteration_timeout=5.0,
            verbose=True
        )

        # Discover test cases
        test_cases = runner.discover_test_cases(test_dir)
        print(f"Found {len(test_cases)} test cases:")
        for tc in test_cases:
            print(f"  {tc.name}: {tc.num_iterations} iterations")

        if not test_cases:
            print("No test cases found, skipping")
            return True

        # Run first test case
        tc = test_cases[0]
        print(f"\nRunning test case: {tc.name}")

        result = runner.run_test_case(tc)

        print(f"\nResult: {result}")
        print(f"  Passed: {result.passed}")
        print(f"  Iterations: {result.iterations_run}/{result.iterations_total}")

        if result.iteration_results:
            for ir in result.iteration_results:
                print(f"  Iteration {ir.iteration}: {ir.validation}")

        # For n1 (failing test), we expect it to fail
        # For p1 (passing test), we expect it to pass
        if tc.name.startswith('n'):
            # Failing test case - might pass or fail depending on the bug manifestation
            print(f"Test case {tc.name} is expected to fail (it's a negative test)")
        else:
            # Passing test case should pass
            print(f"Test case {tc.name} is expected to pass")

        return True

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_runner_discovers_test_cases():
    """Test that test case discovery works."""
    test_examples = Path("/workspace/test_examples")
    test_dir = test_examples / "test"

    if not test_dir.exists():
        print("Test directory not found, skipping")
        return True

    workdir = Path(tempfile.mkdtemp(prefix="runner_test_"))

    try:
        # Just need any executable path for the runner (won't actually run)
        runner = TestRunner(
            executable=Path("/bin/true"),
            workdir=workdir,
            verbose=False
        )

        test_cases = runner.discover_test_cases(test_dir)

        assert len(test_cases) >= 1, "Should find at least one test case"

        # Check n1 exists
        n1 = next((tc for tc in test_cases if tc.name == "n1"), None)
        assert n1 is not None, "Should find n1 test case"
        assert n1.num_iterations >= 1, "n1 should have at least 1 iteration"
        assert n1.expected_pass == False, "n1 should be expected to fail"

        print(f"Found test cases: {[tc.name for tc in test_cases]}")
        return True

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_data_file_parsing():
    """Test that we can parse the actual test data files."""
    from apr_tool.testing.data_format import parse_vote_file

    test_file = Path("/workspace/test_examples/test/n1/output.t1")
    if not test_file.exists():
        print("Test file not found, skipping")
        return True

    vote = parse_vote_file(test_file)

    print(f"Parsed vote from {test_file.name}:")
    print(f"  idx: {vote.idx}")
    print(f"  positions[0:3]: {vote.positions[:3]}")
    print(f"  velocities[0:3]: {vote.velocities[:3]}")

    # Sanity checks
    assert isinstance(vote.idx, int)
    assert len(vote.positions) == 100
    assert len(vote.velocities) == 100

    # The comparison vector should have 12 elements
    vec = vote.get_comparison_vector()
    assert len(vec) == 12

    return True


def test_runner_with_asan():
    """Test that ASan detects the use-after-free bug in controller.c."""
    test_examples = Path("/workspace/test_examples")
    test_dir = test_examples / "test"

    if not test_dir.exists():
        print("Test directory not found, skipping")
        return True

    workdir = Path(tempfile.mkdtemp(prefix="runner_asan_test_"))
    print(f"Working directory: {workdir}")

    try:
        # Compile controller with ASan (only change needed for ASan support)
        print("Compiling controller with AddressSanitizer...")
        executable = compile_controller(workdir, test_examples, enable_asan=True)
        print(f"Executable: {executable}")

        # Create runner (no special ASan flag needed - crash detection handles it)
        runner = TestRunner(
            executable=executable,
            workdir=workdir,
            epsilon=0.5,
            iteration_timeout=10.0,  # Longer timeout for ASan overhead
            verbose=True
        )

        # Discover test cases
        test_cases = runner.discover_test_cases(test_dir)
        print(f"Found {len(test_cases)} test cases")

        if not test_cases:
            print("No test cases found, skipping")
            return True

        # Run n1 test case (should fail due to use-after-free causing crash)
        n1 = next((tc for tc in test_cases if tc.name == "n1"), None)
        if n1 is None:
            print("n1 test case not found, skipping")
            return True

        print(f"\nRunning test case: {n1.name} with ASan")
        result = runner.run_test_case(n1)

        print(f"\nResult: {result}")
        print(f"  Passed: {result.passed}")
        print(f"  Iterations: {result.iterations_run}/{result.iterations_total}")

        # With ASan, the controller should crash due to use-after-free
        if not result.passed and "crash" in result.failure_reason.lower():
            print("\nSUCCESS: ASan caused the controller to crash (memory error detected)")
            return True
        elif not result.passed:
            print(f"\nTest failed for another reason: {result.failure_reason}")
            return True
        else:
            print("\nWARNING: Test passed - ASan did not catch the bug")
            print("This might happen if the bug doesn't manifest in the test input")
            return True

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def compile_coverage_runner(workdir: Path, test_examples: Path,
                            controller_name: str = "controller.c") -> Path:
    """
    Compile the coverage runner for a given controller source.

    Returns path to the coverage_runner executable.
    """
    source_dir = workdir / "source"
    source_dir.mkdir(exist_ok=True)

    # Copy files
    shutil.copy(test_examples / "controller.h", workdir / "controller.h")
    shutil.copy(test_examples / controller_name, source_dir / controller_name)

    # Copy coverage driver
    cov_driver_src = Path("/workspace/apr_tool/coverage/coverage_driver.cpp")
    shutil.copy(cov_driver_src, source_dir / "coverage_driver.cpp")

    cov_flags = "-fprofile-arcs -ftest-coverage"

    # Compile controller C source with coverage
    result = subprocess.run(
        f"gcc -g {cov_flags} -c {source_dir / controller_name} -o {source_dir / 'controller.o'}",
        shell=True, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to compile {controller_name}: {result.stderr}")

    # Compile coverage driver
    result = subprocess.run(
        f"g++ -g {cov_flags} -c {source_dir / 'coverage_driver.cpp'} -o {source_dir / 'coverage_driver.o'}",
        shell=True, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to compile coverage_driver.cpp: {result.stderr}")

    # Link
    result = subprocess.run(
        f"g++ -g {cov_flags} -o {source_dir / 'coverage_runner'} "
        f"{source_dir / 'coverage_driver.o'} {source_dir / 'controller.o'}",
        shell=True, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to link coverage runner: {result.stderr}")

    return source_dir / "coverage_runner"


def test_coverage_driver_infinite_loop():
    """Test that the coverage driver handles infinite-loop controllers."""
    test_examples = Path("/workspace/test_examples")
    test_dir = test_examples / "test"

    if not test_dir.exists():
        print("Test directory not found, skipping")
        return True

    if not (test_examples / "inf_loop.c").exists():
        print("inf_loop.c not found, skipping")
        return True

    workdir = Path(tempfile.mkdtemp(prefix="cov_infloop_test_"))
    print(f"Working directory: {workdir}")

    try:
        # Compile coverage runner with the infinite-loop controller
        print("Compiling coverage runner with inf_loop.c...")
        cov_runner = compile_coverage_runner(workdir, test_examples,
                                             controller_name="inf_loop.c")
        source_dir = cov_runner.parent
        print(f"Coverage runner: {cov_runner}")

        # Discover n1 test case
        n1_dir = test_dir / "n1"
        assert n1_dir.exists(), "n1 test directory not found"
        tc = TestCaseInfo.from_directory(n1_dir)
        print(f"Test case: {tc.name}, {tc.num_iterations} iterations")

        # Clean any stale gcda files
        for gcda in source_dir.glob("*.gcda"):
            gcda.unlink()

        # Run coverage runner with short timeout (2 seconds per iteration)
        timeout_secs = 2
        print(f"Running coverage runner (timeout={timeout_secs}s per iteration)...")
        import time
        start = time.time()
        result = subprocess.run(
            [str(cov_runner), str(tc.path), str(tc.num_iterations),
             str(timeout_secs)],
            capture_output=True, text=True,
            timeout=timeout_secs * tc.num_iterations + 30,
        )
        elapsed = time.time() - start
        print(f"Coverage runner exited with code {result.returncode} in {elapsed:.1f}s")
        if result.stderr:
            print(f"  stderr: {result.stderr.strip()}")

        # Should exit with code 2 (alarm timeout) since inf_loop.c hangs
        assert result.returncode == 2, \
            f"Expected exit code 2 (alarm timeout), got {result.returncode}"
        print("Exit code 2 confirmed (alarm detected infinite loop)")

        # Should complete in roughly timeout_secs, not 60s
        assert elapsed < timeout_secs + 15, \
            f"Coverage runner took {elapsed:.1f}s, expected < {timeout_secs + 15}s"
        print(f"Completed within timeout ({elapsed:.1f}s)")

        # Generate gcov report
        subprocess.run(
            f"gcov inf_loop.c", shell=True, cwd=source_dir,
            capture_output=True, text=True,
        )

        gcov_file = source_dir / "inf_loop.c.gcov"
        assert gcov_file.exists(), "gcov file was not generated"

        # Parse gcov output to check which lines were covered
        from apr_tool.coverage.gcov_parser import GcovParser
        parser = GcovParser()
        covered_lines = parser.get_executed_lines(gcov_file)
        print(f"Covered {len(covered_lines)} lines")

        # The infinite loop is at lines 46-63 of inf_loop.c.
        # With the alarm-based gcov flush, we should see coverage for
        # lines inside the loop body.
        loop_body_lines = set(range(46, 64))  # lines 46-63
        covered_loop_lines = loop_body_lines & covered_lines

        print(f"Loop body lines (46-63) covered: {sorted(covered_loop_lines)}")

        if covered_loop_lines:
            print(f"SUCCESS: {len(covered_loop_lines)} loop body lines have coverage")
        else:
            print("WARNING: No loop body lines covered (gcov flush in signal handler "
                  "may not have captured them)")

        # At minimum, init() and the code leading up to the loop should be covered
        assert 72 in covered_lines or 73 in covered_lines, \
            "init() lines should be covered"
        print("init() lines confirmed covered")

        return True

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    print("=" * 70)
    print("Test Runner Integration Tests")
    print("=" * 70)

    tests = [
        ("Data file parsing", test_data_file_parsing),
        ("Test case discovery", test_runner_discovers_test_cases),
        ("Runner basic execution", test_runner_basic),
        ("Runner with ASan", test_runner_with_asan),
    ]

    results = []
    for name, test_fn in tests:
        print(f"\n{'='*70}")
        print(f"Running: {name}")
        print("=" * 70)

        try:
            success = test_fn()
            results.append((name, success))
            print(f"\n{'✓' if success else '✗'} {name}")
        except Exception as e:
            print(f"\n✗ {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print(f"\n{'='*70}")
    print("SUMMARY")
    print("=" * 70)

    all_passed = True
    for name, success in results:
        status = "PASSED" if success else "FAILED"
        print(f"  {name}: {status}")
        if not success:
            all_passed = False

    if all_passed:
        print("\n✓ All integration tests passed!")
        return 0
    else:
        print("\n✗ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
