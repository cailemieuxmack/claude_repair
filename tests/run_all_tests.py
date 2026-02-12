#!/usr/bin/env python3
"""
Run all SBFL tests.

Usage: python tests/run_all_tests.py
       python tests/run_all_tests.py --include-integration
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.test_sbfl import run_tests as run_sbfl_tests
from tests.test_gcov_parser import run_tests as run_gcov_tests
from tests.test_data_format import run_tests as run_data_format_tests
from tests.test_validator import run_tests as run_validator_tests


def main():
    include_integration = "--include-integration" in sys.argv

    print("=" * 70)
    print("APR Tool - Test Suite")
    print("=" * 70)

    results = []

    print("\n\n" + "=" * 70)
    print("GCOV PARSER TESTS")
    print("=" * 70)
    results.append(("Gcov Parser", run_gcov_tests()))

    print("\n\n" + "=" * 70)
    print("SBFL TESTS")
    print("=" * 70)
    results.append(("SBFL", run_sbfl_tests()))

    print("\n\n" + "=" * 70)
    print("DATA FORMAT TESTS")
    print("=" * 70)
    results.append(("Data Format", run_data_format_tests()))

    print("\n\n" + "=" * 70)
    print("VALIDATOR TESTS")
    print("=" * 70)
    results.append(("Validator", run_validator_tests()))

    if include_integration:
        print("\n\n" + "=" * 70)
        print("INTEGRATION TEST (with real controller.c)")
        print("=" * 70)
        from tests.test_integration_sbfl import main as run_integration
        results.append(("Integration", run_integration()))

    print("\n\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    all_passed = True
    for name, result in results:
        status = "PASSED" if result == 0 else "FAILED"
        print(f"  {name}: {status}")
        if result != 0:
            all_passed = False

    if all_passed:
        print("\n✓ All test suites passed!")
        return 0
    else:
        print("\n✗ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
