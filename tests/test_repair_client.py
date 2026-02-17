"""
Manual integration test for the repair module.

This test actually calls the Claude API and requires:
1. pip install anthropic
2. ANTHROPIC_API_KEY environment variable set

Run with:
    python tests/test_repair_client.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from apr_tool.repair import ClaudeClient
from apr_tool.repair.prompt_builder import RepairPromptContext


def test_repair_from_file():
    """Test repairing the example buggy controller."""
    client = ClaudeClient()

    response = client.repair(
        source_path=Path("test_examples/controller.c"),
        header_path=Path("test_examples/controller.h"),
    )

    print("=== Repair Response ===")
    print(f"Model: {response.model}")
    print(f"Input tokens: {response.input_tokens}")
    print(f"Output tokens: {response.output_tokens}")
    print()
    print("=== Repaired Code ===")
    print(response.repaired_code)


def test_repair_from_code():
    """Test repairing from code strings."""
    client = ClaudeClient()

    buggy_code = """\
#include <stdlib.h>

int main() {
    int *p = malloc(sizeof(int));
    *p = 42;
    free(p);
    return *p;  // use-after-free
}
"""

    context = RepairPromptContext(
        source_code=buggy_code,
        source_filename="buggy.c",
    )
    response = client.repair_from_context(context)

    print("=== Repair Response ===")
    print(f"Model: {response.model}")
    print(f"Input tokens: {response.input_tokens}")
    print(f"Output tokens: {response.output_tokens}")
    print()
    print("=== Repaired Code ===")
    print(response.repaired_code)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test the repair client")
    parser.add_argument(
        "--test",
        choices=["file", "code", "both"],
        default="file",
        help="Which test to run (default: file)",
    )
    args = parser.parse_args()

    if args.test in ("file", "both"):
        print("\n>>> Running test_repair_from_file\n")
        test_repair_from_file()

    if args.test in ("code", "both"):
        print("\n>>> Running test_repair_from_code\n")
        test_repair_from_code()
