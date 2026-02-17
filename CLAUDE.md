# APR Tool - Automated Program Repair for C Controllers

## Project Overview

A Python-based automated program repair tool for C controller programs. Uses spectrum-based fault localization (Ochiai) with test-case-level granularity and Claude API for repair generation.

**Target domain**: ROS2-style robot trajectory controllers with memory-mapped IPC communication.

## Repository Structure

```
/workspace/
├── CLAUDE.md                     # This file - project documentation
├── apr_tool/                     # Main tool implementation
│   ├── __init__.py
│   ├── __main__.py               # Allows `python -m apr_tool`
│   ├── main.py                   # CLI entry point & repair loop
│   ├── coverage/                 # Coverage collection
│   │   ├── __init__.py
│   │   ├── collector.py          # CoverageCollector class (unused by main.py)
│   │   ├── coverage_driver.cpp   # Lightweight C++ driver for gcov collection
│   │   └── gcov_parser.py        # Gcov output parser
│   ├── localization/             # SBFL implementation
│   │   ├── __init__.py
│   │   └── sbfl.py               # CoverageMatrix, SBFLLocalizer, metrics
│   ├── testing/                  # Test runner & validation
│   │   ├── __init__.py
│   │   ├── data_format.py        # Vote & State dataclasses, binary parsing
│   │   ├── runner.py             # TestRunner, TestCaseInfo, IPC
│   │   └── validator.py          # Cosine distance & validation
│   └── repair/                   # Claude API & prompt building
│       ├── __init__.py
│       ├── claude_client.py      # ClaudeClient (Anthropic SDK)
│       ├── prompt_builder.py     # Prompt construction with SBFL context
│       └── response_parser.py    # Extract code from LLM responses
├── tests/                        # Test suite
│   ├── __init__.py
│   ├── run_all_tests.py          # Test runner script
│   ├── test_sbfl.py              # SBFL unit tests (22 tests)
│   ├── test_gcov_parser.py       # Gcov parser tests (6 tests)
│   ├── test_data_format.py       # Data format tests (17 tests)
│   ├── test_validator.py         # Validator tests (15 tests)
│   ├── test_integration_sbfl.py  # SBFL integration test
│   ├── test_runner_integration.py # Runner integration tests (incl. ASan)
│   └── test_repair_client.py     # Manual API test (requires ANTHROPIC_API_KEY)
└── test_examples/                # Example buggy controller & test infrastructure
    ├── controller.c              # Example buggy controller (use-after-free)
    ├── controller.h              # Controller interface header
    ├── test_driver.cpp           # C++ test harness using mmap IPC
    ├── test.sh                   # Original test script
    ├── check_distance.py         # Original validation script
    └── test/
        └── n1/                   # Failing test case
            ├── t1, t2, ...       # Binary input files (State struct)
            └── output.t1, ...    # Binary expected output files (Vote struct)
```

## Key Concepts

### Test Case Semantics

**CRITICAL**: Iterations within a test case are SEQUENTIAL and STATEFUL.

- Iterations are NOT independent - t3 depends on state from t1 and t2
- Controller maintains internal state across iterations
- Bugs may only manifest after specific state accumulation
- A test case PASSES only if ALL iterations pass
- A test case FAILS if ANY iteration fails

### Test Case Naming Convention

- `n*` (n1, n2, ...): Negative/failing test cases
- `p*` (p1, p2, ...): Positive/passing test cases

### Validation Criteria

An iteration passes if BOTH conditions are met:

1. **Index Match**: `controller_output.idx == oracle_output.idx`
2. **Cosine Distance**:
   ```
   controller_vec = positions[0:6] + velocities[0:6]  (12 values)
   oracle_vec     = positions[0:6] + velocities[0:6]  (12 values)
   cosine_distance(controller_vec, oracle_vec) <= epsilon  (default: 0.5)
   ```

Cosine distance formula:
```python
def cosine_distance(v1, v2):
    if norm(v1) == 0 and norm(v2) == 0:
        return 0.0  # identical zero vectors
    if norm(v1) == 0 or norm(v2) == 0:
        return 1.0  # maximally dissimilar
    return 1.0 - (dot(v1, v2) / (norm(v1) * norm(v2)))
```

## Controller Architecture

### IPC Mechanism (Memory-Mapped Files)

- `_state`: Input to controller (State struct, ~832KB)
- `_data`: Output from controller (Vote struct, ~3.2KB)
- `_flag`: Synchronization (exists = waiting, removed = process)

### Data Structures (from controller.h)

```c
typedef struct {
    size_t positions_length;
    double positions[100];
    size_t velocities_length;
    double velocities[100];
    size_t accelerations_length;
    double accelerations[100];
    size_t effort_length;
    double effort[100];
    int32_t time_from_start_sec;
    uint32_t time_from_start_nsec;
} MappedJointTrajectoryPoint;

typedef struct {
    size_t joint_names_length;
    char joint_names[10][256];
    size_t points_length;
    MappedJointTrajectoryPoint points[256];
} MappedJointTrajectory;

typedef struct {
    MappedJointTrajectory value;
    uint32_t cur_time_seconds;
} InStruct;

typedef struct {
    MappedJointTrajectoryPoint vote;
} OutStruct;
```

### Binary Format (for struct.unpack)

```python
POINT_FORMAT = 'Q100dQ100dQ100dQ100diI'  # 3,240 bytes
VOTE_FORMAT = 'i' + POINT_FORMAT          # idx + point
TRAJECTORY_FORMAT = 'Q2560sQ' + POINT_FORMAT * 256
STATE_FORMAT = 'i' + TRAJECTORY_FORMAT + 'i'  # ~832KB
```

### Controller Interface

```c
extern InStruct *in;   // Global input pointer
extern OutStruct *out; // Global output pointer

int init();  // Called once at startup
int step();  // Called for each iteration
```

## SBFL (Spectrum-Based Fault Localization)

### Granularity

Coverage is collected at the **TEST CASE level** (not iteration level).

For each test case:
1. Clean .gcda files
2. Run entire test case (all iterations sequentially)
3. Collect cumulative coverage (union of all iterations)
4. Record pass/fail for test case as a whole

### Coverage Driver

The main IPC-based `test_driver.cpp` cannot be used for gcov because it runs in an infinite loop and must be killed (no clean exit), and buggy controllers may corrupt the heap causing gcov's atexit handler to fail.

Instead, `apr_tool/coverage/coverage_driver.cpp` is a lightweight driver that:
- Calls controller functions directly (no IPC)
- Flushes gcov data via `__gcov_dump()` after each iteration
- Uses `_exit()` to skip atexit handlers on corrupted heaps

### Ochiai Formula

```
For each line L:
    ef(L) = # of FAILING test cases that execute line L
    ep(L) = # of PASSING test cases that execute line L

    ochiai(L) = ef(L) / sqrt(total_failed * (ef(L) + ep(L)))
```

## Test Execution Flow

```
test.sh (parameter: n1)
  │
  ├──► Start controller executable (background)
  │         │
  │         ▼
  │    test_driver.cpp
  │         ├── init()
  │         └── while(true):
  │              wait for _flag removal
  │              read _state → in
  │              step()
  │              out → write _data
  │              create _flag
  │
  └──► check_distance.py
           └── for each iteration:
                write test input to _state
                remove _flag
                sleep(0.001)
                read _data
                compare with oracle (cosine distance)
```

## APR Tool Specification

### Inputs

Required:
- `--source`: Path to buggy controller.c
- `--header`: Path to controller.h
- `--driver`: Path to test_driver.cpp
- `--test-dir`: Base directory containing n1/, n2/, p1/, p2/, etc.

Optional:
- `--output`: Output directory (default: ./apr_output)
- `--max-attempts`: Max repair attempts (default: 5)
- `--epsilon`: Cosine distance threshold (default: 0.5)
- `--top-lines`: Top suspicious lines for SBFL (default: 15)
- `--enable-asan`: Enable AddressSanitizer
- `--verbose`: Enable verbose logging

### Outputs

- `controller.c`: Repaired source file
- `controller.c.patch`: Unified diff
- `repair_report.json`: Detailed repair report
- `prompt_attempt_N.txt`: Saved prompts for each attempt

### Repair Loop

1. Discover test cases (n*, p*)
2. Compile coverage runner and collect gcov coverage for all test cases
3. Compile real executable and run baseline validation via IPC
4. Update coverage matrix with actual pass/fail from baseline
5. Compute fault localization (Ochiai)
6. For each attempt (up to max_attempts):
   a. Build prompt with buggy code, fault localization, test results, previous failures
   b. Save prompt to output directory
   c. Call Claude API for repair
   d. Write repaired code to temp workdir (originals never modified)
   e. Compile and run all tests
   f. If all tests pass, save repaired source, patch, and report; exit success
   g. Otherwise, record failure and continue

### Configuration Defaults

```python
# Compilation: separate gcc/g++ compile + link (in main.py)
# gcc -g {extra_flags} -c controller.c -o controller.o
# g++ -g {extra_flags} -c test_driver.cpp -o test_driver.o
# g++ -g {extra_flags} -o controller test_driver.o controller.o
# For ASan: extra_flags = "-fsanitize=address -fno-omit-frame-pointer"
# For coverage: extra_flags = "-fprofile-arcs -ftest-coverage"
epsilon = 0.5
iteration_timeout = 5.0       # TestRunner default
startup_timeout = 10.0        # TestRunner default
claude_model = "claude-sonnet-4-20250514"
max_tokens = 8192
temperature = 0.0
max_attempts = 5
top_suspicious_lines = 15
```

## Example Buggy Controller

The example in `test_examples/controller.c` contains a **use-after-free vulnerability**:

```c
// Line 68: Buffer is freed
free(temp_buffer);

// Line 75: Buffer is accessed after free
double effort_base = temp_buffer[0];  // USE-AFTER-FREE

// Lines 78-84: Buffer continues to be used
for (int i = 0; i < buffer_size && ...; i++) {
    temp_buffer[i] = ...;  // Writing to freed memory
}
```

This bug may only manifest after multiple iterations when the freed memory gets reallocated and corrupted.

### Bug Detection with AddressSanitizer

The use-after-free bug in the example controller does NOT cause test failures when compiled normally because:
- The bug corrupts `effort_sum` which is only printed to stdout
- The validated output (positions/velocities in the Vote struct) is unaffected
- The n1 test **passes** without ASan

When compiled with AddressSanitizer:
```bash
gcc -g -fsanitize=address -fno-omit-frame-pointer -c controller.c
g++ -g -fsanitize=address -fno-omit-frame-pointer -c test_driver.cpp
g++ -g -fsanitize=address -fno-omit-frame-pointer -o controller test_driver.o controller.o
```

ASan detects the memory error and crashes the controller, causing the test to **fail** with `CONTROLLER_CRASH`. This demonstrates why ASan is valuable for detecting bugs that don't cause observable output differences.

## Development Commands

```bash
# Run tests (from test_examples/)
./test.sh n1

# Run APR tool
python -m apr_tool \
    --source test_examples/controller.c \
    --header test_examples/controller.h \
    --driver test_examples/test_driver.cpp \
    --test-dir test_examples/test \
    --verbose

# With ASan enabled
python -m apr_tool \
    --source test_examples/controller.c \
    --header test_examples/controller.h \
    --driver test_examples/test_driver.cpp \
    --test-dir test_examples/test \
    --enable-asan --verbose
```

## Implementation Status

### Completed

- [x] **SBFL Module** (`apr_tool/localization/sbfl.py`)
  - `CoverageMatrix` class for storing test case coverage data
  - `SBFLLocalizer` class with multiple metrics:
    - Ochiai (default)
    - Tarantula
    - DStar
    - Jaccard
  - Line ranking with tie-breaking by line number
  - Support for source text annotation

- [x] **Gcov Parser** (`apr_tool/coverage/gcov_parser.py`)
  - Parse gcov output files
  - Extract executed/executable lines
  - Handle various gcov format variations

- [x] **Coverage Collector** (`apr_tool/coverage/collector.py`)
  - `CoverageCollector` class for managing coverage collection
  - `TestCaseInfo` for test case discovery
  - Compilation with coverage flags
  - Working directory management
  - Note: `main.py` implements its own coverage collection using `coverage_driver.cpp` rather than using `CoverageCollector`

- [x] **Coverage Driver** (`apr_tool/coverage/coverage_driver.cpp`)
  - Lightweight C++ driver for gcov instrumentation
  - Calls controller functions directly (no IPC)
  - Flushes gcov via `__gcov_dump()` after each iteration
  - Uses `_exit()` to skip atexit handlers on corrupted heaps

- [x] **Test Runner** (`apr_tool/testing/runner.py`)
  - `TestRunner` class for running test cases via IPC
  - `TestCaseInfo` for test case metadata
  - `TestCaseResult` and `IterationResult` for results
  - Memory-mapped file IPC (_state, _data, _flag)
  - Timeout handling for hung controllers
  - Test case discovery (n*, p*)

- [x] **Validation Logic** (`apr_tool/testing/validator.py`)
  - `cosine_distance()` implementation (no numpy dependency)
  - `validate_iteration()` for comparing controller output to oracle
  - `ValidationResult` with detailed failure information
  - Support for index matching and cosine distance checks

- [x] **Binary Data Format** (`apr_tool/testing/data_format.py`)
  - `Vote` dataclass with `idx`, `positions`, `velocities` fields
  - `TrajectoryPoint` and `State` dataclasses for controller input parsing
  - Binary struct format definitions matching controller.h
  - `parse_vote()` and `parse_vote_file()` functions
  - `parse_state()` and `parse_state_file()` for parsing binary test inputs
  - `format_state_text()` for human-readable State representation (used in repair prompts)
  - `get_comparison_vector()` for cosine distance computation

- [x] **AddressSanitizer Support**
  - Compile with `-fsanitize=address -fno-omit-frame-pointer` via `--enable-asan`
  - ASan detects memory errors (use-after-free, buffer overflow, etc.)
  - Existing crash detection in TestRunner handles ASan-induced crashes
  - No special runner configuration needed - just compile with ASan flags

- [x] **Claude API Client** (`apr_tool/repair/claude_client.py`)
  - `ClaudeClient` class using Anthropic SDK
  - `repair()` method for file-based repair requests
  - `repair_from_context()` for pre-built prompt contexts
  - `RepairResponse` dataclass with repaired code, token usage, model info

- [x] **Prompt Builder** (`apr_tool/repair/prompt_builder.py`)
  - `RepairPromptContext` and `PreviousAttempt` dataclasses
  - `build_repair_prompt()` constructs prompts with SBFL results, test results, failing test input, and previous attempt feedback
  - `failing_test_input` field: deserialized binary input from the first failing test iteration, giving Claude concrete context about what data triggers the bug
  - `SYSTEM_PROMPT` instructs Claude to return raw repaired code
  - `load_repair_context()` for loading source/header from files
  - Numbered source code formatting for line reference

- [x] **Response Parser** (`apr_tool/repair/response_parser.py`)
  - `parse_repair_response()` extracts code from LLM responses
  - Handles markdown code fences (```c, ```cpp, etc.)
  - Falls back to raw text if no fences found

- [x] **Main CLI** (`apr_tool/main.py`)
  - Full CLI with argparse
  - Three-phase repair loop: setup, coverage/SBFL, iterative repair
  - All work happens in a temp directory (originals never modified)
  - Saves prompts, patches, and repair reports to output directory
  - Separate compilation for coverage runner vs. validation executable

- [x] **Test Suite** (`tests/`)
  - 60 unit tests across 4 test files using a custom test runner
  - `test_sbfl.py` (22 tests): coverage matrix, all metrics, ranking, edge cases, realistic scenarios
  - `test_gcov_parser.py` (6 tests): parsing, executed/executable/not-executed lines
  - `test_data_format.py` (17 tests): struct sizes, vote parsing, state parsing, format_state_text, real data files
  - `test_validator.py` (15 tests): cosine distance, validation logic, result formatting
  - Integration tests:
    - `test_integration_sbfl.py`: end-to-end SBFL with real controller.c
    - `test_runner_integration.py`: runner execution, test discovery, ASan test
    - `test_repair_client.py`: manual API test (requires ANTHROPIC_API_KEY)

### Known Issues

- `CoverageCollector` in `collector.py` is not used by `main.py`, which has its own coverage collection logic using `coverage_driver.cpp`.

## Running Tests

```bash
# Run unit tests only (fast)
python3 tests/run_all_tests.py

# Run all tests including integration test with real controller.c
python3 tests/run_all_tests.py --include-integration

# Run individual test files
python3 tests/test_sbfl.py
python3 tests/test_gcov_parser.py
python3 tests/test_data_format.py
python3 tests/test_validator.py

# Run integration tests
python3 tests/test_integration_sbfl.py
python3 tests/test_runner_integration.py

# Run repair client test (requires ANTHROPIC_API_KEY)
python3 tests/test_repair_client.py
```

### Integration Tests

The SBFL integration test (`tests/test_integration_sbfl.py`) verifies the end-to-end SBFL flow:
1. Compiles `controller.c` with gcov instrumentation
2. Runs simulated failing tests (n1, n2) that trigger the buggy code path
3. Runs simulated passing tests (p1, p2) that don't trigger the bug
4. Collects coverage data via gcov
5. Runs SBFL analysis
6. Verifies that the buggy lines (68: `free(temp_buffer)` and 75: `temp_buffer[0]`) are ranked highly suspicious

The test correctly identifies lines 68 and 75 with suspiciousness score 1.0 (maximum).

The runner integration test (`tests/test_runner_integration.py`) includes an ASan test:
1. Compiles `controller.c` with ASan flags
2. Runs the n1 test case
3. Verifies that ASan detects the use-after-free and crashes the controller
4. Confirms the test fails with `CONTROLLER_CRASH`
