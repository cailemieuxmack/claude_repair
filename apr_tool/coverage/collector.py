"""
Coverage collection for C programs using gcov.

This module handles:
1. Compiling C programs with coverage instrumentation
2. Running test cases and collecting coverage data
3. Building a CoverageMatrix for SBFL
"""

import os
import glob
import shutil
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from .gcov_parser import GcovParser
from ..localization.sbfl import CoverageMatrix
from ..testing.runner import TestCaseInfo


@dataclass
class CompileResult:
    """Result of a compilation attempt."""
    success: bool
    executable: Optional[Path] = None
    error: Optional[str] = None
    command: str = ""


@dataclass
class TestResult:
    """Result of running a test case."""
    passed: bool
    iterations_run: int
    failed_at_iteration: Optional[int] = None
    failure_reason: Optional[str] = None


@dataclass
class Config:
    """Configuration for coverage collection."""
    compile_command: str = (
        "g++ -g -fprofile-arcs -ftest-coverage "
        "-o {executable} {driver} {source}"
    )
    gcov_command: str = "gcov {source}"
    test_timeout: float = 30.0
    iteration_timeout: float = 1.0
    epsilon: float = 0.5


class CoverageCollector:
    """
    Collects line-level coverage for each test case.

    Coverage is cumulative across all iterations within a test case.
    The test case is treated as an atomic unit.
    """

    def __init__(
        self,
        source_file: Path,
        header_file: Path,
        driver_file: Path,
        test_base_dir: Path,
        workdir: Optional[Path] = None,
        config: Optional[Config] = None
    ):
        """
        Initialize the coverage collector.

        Args:
            source_file: Path to the controller .c file
            header_file: Path to the controller .h file
            driver_file: Path to test_driver.cpp
            test_base_dir: Directory containing test case subdirectories (n1/, p1/, etc.)
            workdir: Working directory (default: create temp directory)
            config: Configuration options
        """
        self.source_file = Path(source_file)
        self.header_file = Path(header_file)
        self.driver_file = Path(driver_file)
        self.test_base_dir = Path(test_base_dir)
        self.config = config or Config()

        # Setup working directory
        if workdir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="apr_coverage_")
            self.workdir = Path(self._temp_dir)
        else:
            self._temp_dir = None
            self.workdir = Path(workdir)
            self.workdir.mkdir(parents=True, exist_ok=True)

        self.gcov_parser = GcovParser()
        self.executable: Optional[Path] = None

    def cleanup(self):
        """Clean up temporary directory if we created one."""
        if self._temp_dir is not None:
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def setup_workdir(self) -> None:
        """Copy source files to working directory."""
        # Copy source files
        shutil.copy(self.source_file, self.workdir / self.source_file.name)
        shutil.copy(self.header_file, self.workdir / self.header_file.name)
        shutil.copy(self.driver_file, self.workdir / self.driver_file.name)

    def compile_with_coverage(self) -> CompileResult:
        """
        Compile the controller with gcov instrumentation.

        Returns:
            CompileResult indicating success/failure
        """
        self.setup_workdir()

        executable = self.workdir / "controller"
        source = self.source_file.name
        driver = self.driver_file.name

        cmd = self.config.compile_command.format(
            executable=executable,
            source=source,
            driver=driver
        )

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                return CompileResult(
                    success=False,
                    error=result.stderr or result.stdout,
                    command=cmd
                )

            self.executable = executable
            return CompileResult(
                success=True,
                executable=executable,
                command=cmd
            )

        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                error="Compilation timed out",
                command=cmd
            )
        except Exception as e:
            return CompileResult(
                success=False,
                error=str(e),
                command=cmd
            )

    def discover_test_cases(self) -> list[TestCaseInfo]:
        """
        Discover all test cases in the test base directory.

        Looks for directories starting with 'n' (failing) or 'p' (passing).

        Returns:
            List of TestCaseInfo objects sorted by name
        """
        test_cases = []

        for item in sorted(self.test_base_dir.iterdir()):
            if item.is_dir() and (item.name.startswith('n') or item.name.startswith('p')):
                tc = TestCaseInfo.from_directory(item)
                if tc.num_iterations > 0:
                    test_cases.append(tc)

        return test_cases

    def _clean_gcov_data(self) -> None:
        """Remove any existing .gcda and .gcov files."""
        for pattern in ['*.gcda', '*.gcov']:
            for f in glob.glob(str(self.workdir / pattern)):
                os.remove(f)

    def _generate_gcov(self) -> Optional[Path]:
        """
        Run gcov to generate coverage report.

        Returns:
            Path to the .gcov file, or None if generation failed
        """
        source_name = self.source_file.name
        cmd = self.config.gcov_command.format(source=source_name)

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=30
            )

            gcov_file = self.workdir / f"{source_name}.gcov"
            if gcov_file.exists():
                return gcov_file

            return None

        except Exception:
            return None

    def _run_test_case_for_coverage(
        self,
        test_case: TestCaseInfo,
        test_runner
    ) -> tuple[TestResult, set[int]]:
        """
        Run a test case and collect coverage.

        Args:
            test_case: The test case to run
            test_runner: A callable that runs the test and returns TestResult

        Returns:
            Tuple of (TestResult, set of covered lines)
        """
        # Clean previous coverage data
        self._clean_gcov_data()

        # Run the test case
        result = test_runner(test_case)

        # Generate and parse gcov output
        gcov_file = self._generate_gcov()

        if gcov_file is None:
            return result, set()

        covered_lines = self.gcov_parser.get_executed_lines(gcov_file)

        return result, covered_lines

    def collect_coverage(
        self,
        test_runner,
        test_cases: Optional[list[TestCaseInfo]] = None
    ) -> CoverageMatrix:
        """
        Collect coverage for all test cases.

        Args:
            test_runner: A callable that takes TestCaseInfo and returns TestResult
            test_cases: List of test cases to run (default: discover automatically)

        Returns:
            CoverageMatrix with coverage and results for each test case
        """
        if test_cases is None:
            test_cases = self.discover_test_cases()

        matrix = CoverageMatrix(source_file=str(self.source_file))

        for tc in test_cases:
            result, covered_lines = self._run_test_case_for_coverage(tc, test_runner)
            matrix.add_test_case(tc.name, covered_lines, result.passed)

        return matrix


class MockTestRunner:
    """
    Mock test runner for testing the coverage collector.

    This simulates running tests without actually executing anything.
    Useful for unit testing the SBFL implementation.
    """

    def __init__(self, results: dict[str, bool]):
        """
        Initialize with predetermined results.

        Args:
            results: Mapping from test case name to pass/fail
        """
        self.results = results

    def __call__(self, test_case: TestCaseInfo) -> TestResult:
        """Run a test case (simulated)."""
        passed = self.results.get(test_case.name, False)

        if passed:
            return TestResult(
                passed=True,
                iterations_run=test_case.num_iterations
            )
        else:
            # Simulate failure at some iteration
            fail_at = min(3, test_case.num_iterations)
            return TestResult(
                passed=False,
                iterations_run=fail_at,
                failed_at_iteration=fail_at,
                failure_reason="cosine_distance=0.7 > 0.5"
            )
