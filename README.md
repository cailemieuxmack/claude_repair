# APR Tool - Automated Program Repair for C Controllers

## Project Overview

A Python-based automated program repair tool for C controller programs. Uses spectrum-based fault localization (Ochiai) with test-case-level granularity and Claude API for repair generation.

**Target domain**: ROS2-style robot trajectory controllers with memory-mapped IPC communication.

## Repository Structure

```
/workspace/
├── CLAUDE.md                     # This file - project documentation
├── apr_tool/                     # Main tool implementation (to be created)
│   ├── __init__.py
│   ├── main.py                   # CLI entry point & repair loop
│   ├── config.py                 # Configuration dataclass
│   ├── coverage/                 # Coverage collection
│   ├── localization/             # SBFL implementation
│   ├── testing/                  # Test runner & validation
│   ├── repair/                   # Claude API & prompt building
│   └── utils/                    # Utilities
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
- `--config`: Path to configuration JSON
- `--output`: Output directory (default: ./apr_output)
- `--max-attempts`: Max repair attempts (default: 5)
- `--epsilon`: Cosine distance threshold (default: 0.5)
- `--verbose`: Enable verbose logging

### Outputs

- `controller.c`: Repaired source file
- `controller.c.patch`: Unified diff
- `repair_report.json`: Detailed repair report

### Repair Loop

1. Discover test cases (n*, p*)
2. Collect coverage for all test cases
3. Compute fault localization (Ochiai)
4. For each attempt (up to max_attempts):
   a. Build prompt with buggy code, fault localization, test results
   b. Call Claude API for repair
   c. Parse response (extract ANALYSIS, FIX, CODE)
   d. Compile and validate repair
   e. If all tests pass, return success
   f. Otherwise, include failure in next prompt

### Configuration Defaults

```python
compile_command = "g++ -g -fprofile-arcs -ftest-coverage -o controller test_driver.cpp controller.c"
# For ASan: add "-fsanitize=address -fno-omit-frame-pointer" to compile flags
epsilon = 0.5
iteration_timeout = 1.0
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

# Run APR tool (once implemented)
python -m apr_tool \
    --source test_examples/controller.c \
    --header test_examples/controller.h \
    --driver test_examples/test_driver.cpp \
    --test-dir test_examples/test \
    --verbose
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

- [x] **Test Suite** (`tests/`)
  - 28 tests covering all SBFL functionality
  - Tests for gcov parser
  - Tests for all metrics (Ochiai, Tarantula, DStar, Jaccard)
  - Edge case tests
  - Realistic scenario tests

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
  - `Vote` and `MappedJointTrajectoryPoint` dataclasses
  - Binary struct format definitions matching controller.h
  - `parse_vote()` and `parse_vote_file()` functions
  - Handles struct alignment/padding correctly

- [x] **AddressSanitizer Support**
  - Compile with `-fsanitize=address -fno-omit-frame-pointer` to enable ASan
  - ASan detects memory errors (use-after-free, buffer overflow, etc.)
  - Existing crash detection in TestRunner handles ASan-induced crashes
  - No special runner configuration needed - just compile with ASan flags

### TODO / Open Items

- [ ] Implement Claude API client (`apr_tool/repair/claude_client.py`)
- [ ] Implement prompt builder (`apr_tool/repair/prompt_builder.py`)
- [ ] Implement response parser (`apr_tool/repair/response_parser.py`)
- [ ] Implement main CLI (`apr_tool/main.py`)

## Running Tests

```bash
# Run unit tests only (fast)
python3 tests/run_all_tests.py

# Run all tests including integration test with real controller.c
python3 tests/run_all_tests.py --include-integration

# Run individual test files
python3 tests/test_sbfl.py
python3 tests/test_gcov_parser.py
python3 tests/test_integration_sbfl.py

# Run runner integration tests (includes ASan test)
python3 tests/test_runner_integration.py
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
