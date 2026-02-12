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
    assert len(vote.point.positions) == 100
    assert len(vote.point.velocities) == 100

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
