"""
APR Tool - Main CLI entry point.

Repair loop:
1. Discover test cases and run baseline tests
2. Collect coverage and compute fault localization (SBFL)
3. For each attempt: call Claude API, compile, validate

NOTE: The original source files are NEVER modified. All compilation and
repair work happens in a temporary directory. Outputs go to --output dir.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .coverage.gcov_parser import GcovParser
from .localization.sbfl import CoverageMatrix, SBFLLocalizer, read_source_lines
from .testing.runner import TestRunner, TestCaseInfo, TestCaseResult
from .testing.data_format import parse_state_file, format_state_text
from .repair.claude_client import ClaudeClient
from .repair.prompt_builder import (
    RepairPromptContext, PreviousAttempt, SYSTEM_PROMPT, build_repair_prompt,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="APR Tool - Automated Program Repair for C Controllers"
    )
    parser.add_argument("--source", required=True, help="Path to buggy controller.c")
    parser.add_argument("--header", required=True, help="Path to controller.h")
    parser.add_argument("--driver", required=True, help="Path to test_driver.cpp")
    parser.add_argument("--test-dir", required=True, help="Base directory containing test cases")
    parser.add_argument("--output", default="./apr_output", help="Output directory")
    parser.add_argument("--max-attempts", type=int, default=5, help="Max repair attempts")
    parser.add_argument("--epsilon", type=float, default=0.5, help="Cosine distance threshold")
    parser.add_argument("--top-lines", type=int, default=15, help="Top suspicious lines for SBFL")
    parser.add_argument("--enable-asan", action="store_true", help="Enable AddressSanitizer")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args(argv)


def log(msg, verbose=True):
    if verbose:
        print(f"[APR] {msg}")


def setup_workdir(workdir: Path, source: Path, header: Path, driver: Path) -> Path:
    """
    Copy source files into a temp working directory. Originals are never modified.

    Both controller.c and test_driver.cpp use #include "../controller.h",
    so the header must be one level above the source files.

    Layout:
        workdir/
        ├── controller.h
        └── source/
            ├── controller.c
            └── test_driver.cpp

    Returns the source_dir path.
    """
    source_dir = workdir / "source"
    source_dir.mkdir(exist_ok=True)

    shutil.copy(header, workdir / header.name)
    shutil.copy(source, source_dir / source.name)
    shutil.copy(driver, source_dir / driver.name)

    return source_dir


# Path to the coverage driver source, shipped alongside this module
COVERAGE_DRIVER_PATH = Path(__file__).parent / "coverage" / "coverage_driver.cpp"


def compile_controller(
    source_dir: Path,
    source_name: str,
    driver_name: str,
    extra_flags: str = "",
) -> tuple[Optional[Path], Optional[str]]:
    """
    Compile controller from separate C and C++ files, then link.

    Returns (executable_path, None) on success or (None, error_message) on failure.
    """
    c_stem = Path(source_name).stem
    cpp_stem = Path(driver_name).stem
    c_obj = source_dir / f"{c_stem}.o"
    cpp_obj = source_dir / f"{cpp_stem}.o"
    executable = source_dir / "controller"

    # Compile C source
    cmd = f"gcc -g {extra_flags} -c {source_dir / source_name} -o {c_obj}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()

    # Compile C++ driver
    cmd = f"g++ -g {extra_flags} -c {source_dir / driver_name} -o {cpp_obj}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()

    # Link
    cmd = f"g++ -g {extra_flags} -o {executable} {cpp_obj} {c_obj}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()

    return executable, None


def compile_coverage_runner(
    source_dir: Path,
    source_name: str,
    extra_flags: str = "",
) -> tuple[Optional[Path], Optional[str]]:
    """
    Compile the lightweight coverage runner (controller + coverage_driver.cpp).

    This builds a separate executable used only for gcov coverage collection.
    Returns (executable_path, None) on success or (None, error_message) on failure.
    """
    c_stem = Path(source_name).stem
    c_obj = source_dir / f"{c_stem}.o"
    cov_driver = source_dir / "coverage_driver.cpp"
    cov_obj = source_dir / "coverage_driver.o"
    executable = source_dir / "coverage_runner"

    # Copy coverage driver into source_dir (needs ../controller.h)
    shutil.copy(COVERAGE_DRIVER_PATH, cov_driver)

    # Compile C source
    cmd = f"gcc -g {extra_flags} -c {source_dir / source_name} -o {c_obj}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()

    # Compile coverage driver
    cmd = f"g++ -g {extra_flags} -c {cov_driver} -o {cov_obj}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()

    # Link
    cmd = f"g++ -g {extra_flags} -o {executable} {cov_obj} {c_obj}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()

    return executable, None


def collect_coverage(
    source_dir: Path,
    source_name: str,
    coverage_runner: Path,
    test_cases: list[TestCaseInfo],
    verbose: bool,
) -> CoverageMatrix:
    """
    Collect gcov coverage for each test case using the lightweight coverage runner.

    Pass/fail for SBFL is determined by the test case naming convention
    (n* = failing, p* = passing). Actual validation happens separately
    via the TestRunner.

    Returns a CoverageMatrix.
    """
    parser = GcovParser()
    matrix = CoverageMatrix(source_file=source_name)

    for tc in test_cases:
        log(f"Collecting coverage for {tc.name}...", verbose)

        # Clean .gcda files so we get per-test-case coverage
        for gcda in source_dir.glob("*.gcda"):
            gcda.unlink()

        cov_result = subprocess.run(
            [str(coverage_runner), str(tc.path), str(tc.num_iterations)],
            capture_output=True, text=True, timeout=60,
        )
        if cov_result.returncode != 0:
            log(f"  Coverage runner exited {cov_result.returncode}", verbose)

        # Generate gcov report
        subprocess.run(
            f"gcov {source_name}",
            shell=True, cwd=source_dir,
            capture_output=True, text=True, timeout=30,
        )

        gcov_file = source_dir / f"{source_name}.gcov"
        if gcov_file.exists():
            covered_lines = parser.get_executed_lines(gcov_file)
            log(f"  Covered {len(covered_lines)} lines", verbose)
        else:
            covered_lines = set()
            log(f"  WARNING: No gcov file generated", verbose)

        # Use naming convention for SBFL pass/fail (n* = fail, p* = pass)
        matrix.add_test_case(tc.name, covered_lines, tc.expected_pass)

    return matrix


def run_all_tests(
    executable: Path,
    run_dir: Path,
    test_cases: list[TestCaseInfo],
    epsilon: float,
    verbose: bool,
) -> dict[str, TestCaseResult]:
    """Run all test cases via the real IPC-based TestRunner."""
    runner = TestRunner(
        executable=executable,
        workdir=run_dir,
        epsilon=epsilon,
        verbose=verbose,
    )
    results = {}
    for tc in test_cases:
        results[tc.name] = runner.run_test_case(tc)
    return results


def main(argv=None):
    args = parse_args(argv)

    source = Path(args.source).resolve()
    header = Path(args.header).resolve()
    driver = Path(args.driver).resolve()
    test_dir = Path(args.test_dir).resolve()
    output_dir = Path(args.output).resolve()

    for path, name in [
        (source, "--source"),
        (header, "--header"),
        (driver, "--driver"),
        (test_dir, "--test-dir"),
    ]:
        if not path.exists():
            print(f"Error: {name} path does not exist: {path}")
            sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="apr_"))
    run_dir = workdir / "run"
    run_dir.mkdir()

    log(f"Working directory: {workdir}", args.verbose)

    try:
        # --- Phase 1: Setup and discover test cases ---
        log("Phase 1: Setup", args.verbose)

        # All work happens in the temp workdir; original files are never modified
        source_dir = setup_workdir(workdir, source, header, driver)

        # Discover test cases (n*, p* directories)
        test_cases = []
        for item in sorted(test_dir.iterdir()):
            if item.is_dir() and (item.name.startswith('n') or item.name.startswith('p')):
                tc = TestCaseInfo.from_directory(item)
                if tc.num_iterations > 0:
                    test_cases.append(tc)

        if not test_cases:
            print("Error: No test cases found in", test_dir)
            sys.exit(1)

        log(f"Found {len(test_cases)} test cases: {[tc.name for tc in test_cases]}", args.verbose)

        # --- Phase 2: Coverage, baseline validation, SBFL ---
        log("Phase 2: Coverage collection", args.verbose)

        asan_flags = "-fsanitize=address -fno-omit-frame-pointer" if args.enable_asan else ""

        # Build coverage runner (lightweight driver for gcov)
        cov_runner, error = compile_coverage_runner(
            source_dir, source.name, extra_flags="-fprofile-arcs -ftest-coverage",
        )
        if cov_runner is None:
            print(f"Error: Coverage runner compilation failed:\n{error}")
            sys.exit(1)

        # Collect coverage (uses coverage_driver only)
        coverage_matrix = collect_coverage(
            source_dir, source.name, cov_runner, test_cases, args.verbose,
        )

        # Build real executable for validation
        log("Running baseline validation...", args.verbose)
        executable, error = compile_controller(
            source_dir, source.name, driver.name, extra_flags=asan_flags,
        )
        if executable is None:
            print(f"Error: Controller compilation failed:\n{error}")
            sys.exit(1)

        # Run baseline tests via real IPC driver
        baseline_results = run_all_tests(
            executable, run_dir, test_cases, args.epsilon, args.verbose,
        )

        log("Baseline test results:", args.verbose)
        for r in baseline_results.values():
            log(f"  {r}", args.verbose)

        # Update coverage matrix with actual pass/fail from baseline
        for tc_name, result in baseline_results.items():
            coverage_matrix.results[tc_name] = result.passed

        if coverage_matrix.num_failing == 0:
            print("All tests already pass - nothing to repair!")
            sys.exit(0)

        # SBFL
        log("Running fault localization...", args.verbose)
        source_lines = read_source_lines(source_dir / source.name)
        localizer = SBFLLocalizer(coverage_matrix, source_lines)
        ranked = localizer.rank_lines(top_n=args.top_lines)

        log(f"Top {len(ranked)} suspicious lines:", args.verbose)
        for i, s in enumerate(ranked, 1):
            code = s.source_text.strip()[:60]
            log(f"  {i:2}. Line {s.line}: {s.score:.3f}  {code}", args.verbose)

        # --- Phase 3: Repair loop ---
        log("Phase 3: Repair loop", args.verbose)

        # Build deserialized input text for the first failing test iteration
        failing_test_input = None
        tc_by_name = {tc.name: tc for tc in test_cases}
        for name, result in baseline_results.items():
            if not result.passed and result.failed_at_iteration is not None:
                tc = tc_by_name.get(name)
                if tc is None:
                    continue
                input_file = tc.path / f"t{result.failed_at_iteration}"
                if input_file.exists():
                    try:
                        state = parse_state_file(input_file)
                        failing_test_input = (
                            f"Test case {name}, iteration {result.failed_at_iteration}:\n"
                            + format_state_text(state)
                        )
                        log(f"Parsed failing input: {name}/t{result.failed_at_iteration} "
                            f"({len(failing_test_input)} chars)", args.verbose)
                    except Exception as e:
                        log(f"Warning: failed to parse input {input_file}: {e}", args.verbose)
                break  # only include the first failing test

        client = ClaudeClient()
        original_source = source.read_text()
        previous_attempts: list[PreviousAttempt] = []

        for attempt in range(1, args.max_attempts + 1):
            log(f"=== Attempt {attempt}/{args.max_attempts} ===", True)

            # Build prompt context
            context = RepairPromptContext(
                source_code=original_source,
                source_filename=source.name,
                header_code=header.read_text(),
                header_filename=header.name,
                suspicious_lines=ranked,
                test_results=list(baseline_results.values()),
                previous_attempts=previous_attempts,
                failing_test_input=failing_test_input,
            )

            # Save the prompt being sent
            user_prompt = build_repair_prompt(context)
            prompt_file = output_dir / f"prompt_attempt_{attempt}.txt"
            prompt_file.write_text(
                f"=== SYSTEM PROMPT ===\n{SYSTEM_PROMPT}\n\n"
                f"=== USER PROMPT ===\n{user_prompt}\n"
            )
            log(f"Prompt saved to {prompt_file}", args.verbose)

            # Call Claude
            log("Calling Claude API...", args.verbose)
            try:
                response = client.repair_from_context(context)
            except Exception as e:
                log(f"API error: {e}", True)
                continue

            log(
                f"Received repair ({response.input_tokens} in, {response.output_tokens} out)",
                args.verbose,
            )

            repaired_code = response.repaired_code

            # Write repaired source to temp workdir (never the original)
            (source_dir / source.name).write_text(repaired_code)

            # Compile for validation (no coverage flags)
            executable, error = compile_controller(
                source_dir, source.name, driver.name, extra_flags=asan_flags,
            )

            if executable is None:
                log(f"Compilation failed: {error}", True)
                previous_attempts.append(PreviousAttempt(
                    attempt_number=attempt,
                    code=repaired_code,
                    test_results=[],
                    compile_error=error,
                ))
                (source_dir / source.name).write_text(original_source)
                continue

            # Run all tests
            log("Running tests...", args.verbose)
            results = run_all_tests(
                executable, run_dir, test_cases, args.epsilon, args.verbose,
            )

            for r in results.values():
                status = "PASS" if r.passed else "FAIL"
                log(f"  {r.test_name}: {status}", args.verbose)

            if all(r.passed for r in results.values()):
                log("REPAIR SUCCESSFUL!", True)

                # Save repaired source to output dir
                (output_dir / source.name).write_text(repaired_code)

                # Generate unified diff against the original
                diff = subprocess.run(
                    ["diff", "-u", str(source), str(output_dir / source.name)],
                    capture_output=True,
                    text=True,
                )
                (output_dir / f"{source.name}.patch").write_text(diff.stdout)

                # Save report
                report = {
                    "success": True,
                    "attempt": attempt,
                    "model": response.model,
                    "tokens": {
                        "input": response.input_tokens,
                        "output": response.output_tokens,
                    },
                    "test_results": {
                        name: {
                            "passed": r.passed,
                            "iterations": f"{r.iterations_run}/{r.iterations_total}",
                        }
                        for name, r in results.items()
                    },
                }
                (output_dir / "repair_report.json").write_text(
                    json.dumps(report, indent=2)
                )

                print(f"Repaired source saved to {output_dir / source.name}")
                print(f"Patch saved to {output_dir / source.name}.patch")
                sys.exit(0)

            # Failed attempt - record and continue
            previous_attempts.append(PreviousAttempt(
                attempt_number=attempt,
                code=repaired_code,
                test_results=list(results.values()),
            ))
            (source_dir / source.name).write_text(original_source)

        # All attempts exhausted
        print(f"Failed to repair after {args.max_attempts} attempts")

        report = {
            "success": False,
            "attempts": args.max_attempts,
            "baseline_results": {
                name: {"passed": r.passed}
                for name, r in baseline_results.items()
            },
        }
        (output_dir / "repair_report.json").write_text(json.dumps(report, indent=2))
        sys.exit(1)

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
