"""
Test runner for controller test cases.

This module manages:
1. Starting/stopping the controller process
2. IPC via memory-mapped files (_state, _data, _flag)
3. Running test iterations sequentially
4. Collecting pass/fail results

Test Execution Flow:
1. Start controller executable (background process)
2. For each iteration:
   a. Wait for controller ready (_flag exists)
   b. Write test input to _state
   c. Remove _flag to signal controller
   d. Wait for response (with timeout)
   e. Read output from _data
   f. Validate against oracle
3. Kill controller process
"""

import mmap
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .data_format import VOTE_SIZE, parse_vote, parse_vote_file
from .validator import validate_iteration, ValidationResult


@dataclass
class IterationResult:
    """Result of a single test iteration."""
    iteration: int
    validation: ValidationResult
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.validation.passed


@dataclass
class TestCaseResult:
    """Result of running a complete test case."""
    test_name: str
    passed: bool
    iterations_run: int
    iterations_total: int
    failed_at_iteration: Optional[int] = None
    failure_reason: Optional[str] = None
    iteration_results: list[IterationResult] = field(default_factory=list)
    duration_ms: float = 0.0

    def __str__(self) -> str:
        if self.passed:
            return f"{self.test_name}: PASS ({self.iterations_run}/{self.iterations_total} iterations)"
        else:
            return f"{self.test_name}: FAIL at iteration {self.failed_at_iteration} - {self.failure_reason}"


@dataclass
class TestCaseInfo:
    """Information about a test case directory."""
    name: str
    path: Path
    num_iterations: int
    expected_pass: bool  # True for p*, False for n*

    @classmethod
    def from_directory(cls, test_dir: Path) -> "TestCaseInfo":
        """Create TestCaseInfo from a test case directory."""
        name = test_dir.name
        expected_pass = name.startswith('p')

        # Count iterations by finding t1, t2, t3, ... files
        num_iterations = 0
        i = 1
        while (test_dir / f"t{i}").exists():
            num_iterations = i
            i += 1

        return cls(
            name=name,
            path=test_dir,
            num_iterations=num_iterations,
            expected_pass=expected_pass
        )


class TestRunner:
    """
    Runs test cases against a controller executable.

    The runner manages the IPC mechanism using memory-mapped files:
    - _state: Input to controller (written by test runner)
    - _data: Output from controller (read by test runner)
    - _flag: Synchronization (exists = controller waiting, removed = process)
    """

    def __init__(
        self,
        executable: Path,
        workdir: Path,
        epsilon: float = 0.5,
        iteration_timeout: float = 5.0,
        startup_timeout: float = 10.0,
        verbose: bool = False
    ):
        """
        Initialize the test runner.

        Args:
            executable: Path to the controller executable
            workdir: Working directory for IPC files
            epsilon: Cosine distance threshold for validation
            iteration_timeout: Max seconds to wait for each iteration
            startup_timeout: Max seconds to wait for controller startup
            verbose: Enable verbose logging
        """
        self.executable = Path(executable)
        self.workdir = Path(workdir)
        self.epsilon = epsilon
        self.iteration_timeout = iteration_timeout
        self.startup_timeout = startup_timeout
        self.verbose = verbose

        # IPC file paths
        self.state_file = self.workdir / "_state"
        self.data_file = self.workdir / "_data"
        self.flag_file = self.workdir / "_flag"

        # Controller process handle
        self.process: Optional[subprocess.Popen] = None

        # Memory maps
        self._state_mmap: Optional[mmap.mmap] = None
        self._data_mmap: Optional[mmap.mmap] = None
        self._state_fd = None
        self._data_fd = None

    def _log(self, msg: str) -> None:
        """Log a message if verbose mode is enabled."""
        if self.verbose:
            print(f"[TestRunner] {msg}")

    def _setup_ipc_files(self, state_size: int = 832033) -> None:
        """
        Create and initialize IPC files.

        Args:
            state_size: Size for the state file. Default matches actual test files.
                        The calculated size may differ due to alignment padding.
        """
        vote_size = VOTE_SIZE

        # Create _state file with proper size
        # Note: We use 832033 as default because that's the actual size of test files,
        # which differs from struct.calcsize due to alignment/padding differences
        with open(self.state_file, 'wb') as f:
            f.write(b'\x00' * state_size)

        # Create _data file with proper size
        with open(self.data_file, 'wb') as f:
            f.write(b'\x00' * vote_size)

        self._log(f"Created IPC files: _state ({state_size} bytes), _data ({vote_size} bytes)")

    def _open_mmaps(self) -> None:
        """Open memory-mapped files for IPC."""
        # Open file descriptors
        self._state_fd = open(self.state_file, 'r+b')
        self._data_fd = open(self.data_file, 'r+b')

        # Create memory maps
        self._state_mmap = mmap.mmap(self._state_fd.fileno(), 0)
        self._data_mmap = mmap.mmap(self._data_fd.fileno(), 0, access=mmap.ACCESS_READ)

    def _close_mmaps(self) -> None:
        """Close memory-mapped files."""
        if self._state_mmap:
            self._state_mmap.close()
            self._state_mmap = None
        if self._data_mmap:
            self._data_mmap.close()
            self._data_mmap = None
        if self._state_fd:
            self._state_fd.close()
            self._state_fd = None
        if self._data_fd:
            self._data_fd.close()
            self._data_fd = None

    def _cleanup_ipc_files(self) -> None:
        """Remove IPC files."""
        for f in [self.state_file, self.data_file, self.flag_file]:
            try:
                f.unlink()
            except FileNotFoundError:
                pass

    def _start_controller(self) -> bool:
        """
        Start the controller process.

        Returns:
            True if controller started and is ready, False otherwise
        """
        self._log(f"Starting controller: {self.executable}")

        # Remove flag file if it exists (controller will create it when ready)
        try:
            self.flag_file.unlink()
        except FileNotFoundError:
            pass

        # Start controller process with output redirected
        log_file = self.workdir / "controller.log"
        with open(log_file, 'w') as log:
            self.process = subprocess.Popen(
                [str(self.executable)],
                cwd=str(self.workdir),
                stdout=log,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setpgrp  # Create new process group
            )

        # Wait for controller to be ready (creates _flag file)
        start_time = time.time()
        while time.time() - start_time < self.startup_timeout:
            if self.flag_file.exists():
                self._log("Controller is ready")
                return True
            if self.process.poll() is not None:
                self._log(f"Controller exited with code {self.process.returncode}")
                return False
            time.sleep(0.01)

        self._log("Controller startup timeout")
        return False

    def _stop_controller(self) -> None:
        """Stop the controller process."""
        if self.process is None:
            return

        self._log("Stopping controller")

        # Try graceful termination first
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't terminate
                self.process.kill()
                self.process.wait()
        except Exception as e:
            self._log(f"Error stopping controller: {e}")

        self.process = None

    def _wait_for_flag(self, timeout: float) -> bool:
        """
        Wait for the _flag file to exist (controller ready).

        Returns:
            True if flag appeared, False on timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.flag_file.exists():
                return True
            # Check if controller crashed
            if self.process and self.process.poll() is not None:
                return False
            time.sleep(0.001)  # 1ms poll interval
        return False

    def _signal_controller(self) -> None:
        """Signal controller to process by removing the flag file."""
        try:
            self.flag_file.unlink()
        except FileNotFoundError:
            pass

    def _write_state(self, data: bytes) -> None:
        """Write test input to the _state file."""
        self._state_mmap.seek(0)
        self._state_mmap.write(data)
        self._state_mmap.flush()

    def _read_data(self) -> bytes:
        """Read controller output from the _data file."""
        self._data_mmap.seek(0)
        return self._data_mmap.read(VOTE_SIZE)

    def run_iteration(
        self,
        test_case: TestCaseInfo,
        iteration: int
    ) -> IterationResult:
        """
        Run a single test iteration.

        Args:
            test_case: The test case being run
            iteration: 1-based iteration number

        Returns:
            IterationResult with validation outcome
        """
        start_time = time.time()

        # Load test input
        input_file = test_case.path / f"t{iteration}"
        oracle_file = test_case.path / f"output.t{iteration}"

        if not input_file.exists():
            return IterationResult(
                iteration=iteration,
                validation=ValidationResult(False, f"Input file not found: {input_file}")
            )

        if not oracle_file.exists():
            return IterationResult(
                iteration=iteration,
                validation=ValidationResult(False, f"Oracle file not found: {oracle_file}")
            )

        # Wait for controller to be ready
        if not self._wait_for_flag(self.iteration_timeout):
            if self.process and self.process.poll() is not None:
                return IterationResult(
                    iteration=iteration,
                    validation=ValidationResult(False, f"Controller exited with code {self.process.returncode}")
                )
            return IterationResult(
                iteration=iteration,
                validation=ValidationResult(False, "Timeout waiting for controller to be ready")
            )

        # Write test input
        with open(input_file, 'rb') as f:
            input_data = f.read()
        self._write_state(input_data)

        # Signal controller to process
        self._signal_controller()

        # Wait for response
        if not self._wait_for_flag(self.iteration_timeout):
            if self.process and self.process.poll() is not None:
                return IterationResult(
                    iteration=iteration,
                    validation=ValidationResult(False, "Controller crashed during iteration")
                )
            return IterationResult(
                iteration=iteration,
                validation=ValidationResult(False, "Timeout waiting for controller response")
            )

        # Read controller output
        output_data = self._read_data()

        # Parse and validate
        try:
            controller_vote = parse_vote(output_data)
            oracle_vote = parse_vote_file(oracle_file)

            validation = validate_iteration(
                controller_vote,
                oracle_vote,
                self.epsilon
            )
        except Exception as e:
            validation = ValidationResult(False, f"Parse error: {e}")

        duration_ms = (time.time() - start_time) * 1000

        return IterationResult(
            iteration=iteration,
            validation=validation,
            duration_ms=duration_ms
        )

    def run_test_case(self, test_case: TestCaseInfo) -> TestCaseResult:
        """
        Run a complete test case (all iterations sequentially).

        Args:
            test_case: The test case to run

        Returns:
            TestCaseResult with overall pass/fail and iteration details
        """
        self._log(f"Running test case: {test_case.name} ({test_case.num_iterations} iterations)")

        start_time = time.time()

        # Determine state file size from first input file
        first_input = test_case.path / "t1"
        if first_input.exists():
            state_size = first_input.stat().st_size
        else:
            state_size = 832033  # Default fallback

        # Setup
        self._setup_ipc_files(state_size)
        self._open_mmaps()

        try:
            # Start controller
            if not self._start_controller():
                return TestCaseResult(
                    test_name=test_case.name,
                    passed=False,
                    iterations_run=0,
                    iterations_total=test_case.num_iterations,
                    failed_at_iteration=0,
                    failure_reason="Controller failed to start"
                )

            # Run all iterations
            iteration_results = []
            for i in range(1, test_case.num_iterations + 1):
                self._log(f"  Iteration {i}/{test_case.num_iterations}")

                result = self.run_iteration(test_case, i)
                iteration_results.append(result)

                if not result.passed:
                    duration_ms = (time.time() - start_time) * 1000
                    return TestCaseResult(
                        test_name=test_case.name,
                        passed=False,
                        iterations_run=i,
                        iterations_total=test_case.num_iterations,
                        failed_at_iteration=i,
                        failure_reason=str(result.validation),
                        iteration_results=iteration_results,
                        duration_ms=duration_ms
                    )

            # All iterations passed
            duration_ms = (time.time() - start_time) * 1000
            return TestCaseResult(
                test_name=test_case.name,
                passed=True,
                iterations_run=test_case.num_iterations,
                iterations_total=test_case.num_iterations,
                iteration_results=iteration_results,
                duration_ms=duration_ms
            )

        finally:
            # Cleanup
            self._stop_controller()
            self._close_mmaps()
            self._cleanup_ipc_files()

    def discover_test_cases(self, test_base_dir: Path) -> list[TestCaseInfo]:
        """
        Discover all test cases in a directory.

        Looks for subdirectories starting with 'n' (failing) or 'p' (passing).

        Args:
            test_base_dir: Directory containing test case subdirectories

        Returns:
            List of TestCaseInfo sorted by name
        """
        test_cases = []

        for item in sorted(test_base_dir.iterdir()):
            if item.is_dir() and (item.name.startswith('n') or item.name.startswith('p')):
                tc = TestCaseInfo.from_directory(item)
                if tc.num_iterations > 0:
                    test_cases.append(tc)

        return test_cases

    def run_all_test_cases(
        self,
        test_base_dir: Path,
        test_cases: Optional[list[TestCaseInfo]] = None
    ) -> dict[str, TestCaseResult]:
        """
        Run all test cases in a directory.

        Args:
            test_base_dir: Directory containing test cases
            test_cases: Optional list of specific test cases to run

        Returns:
            Dict mapping test case name to result
        """
        if test_cases is None:
            test_cases = self.discover_test_cases(test_base_dir)

        results = {}
        for tc in test_cases:
            result = self.run_test_case(tc)
            results[tc.name] = result

            status = "PASS" if result.passed else "FAIL"
            self._log(f"{tc.name}: {status}")

        return results
