"""
Prompt builder for repair requests.

Builds prompts for the LLM including fault localization,
test results, and previous attempt feedback.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..localization.sbfl import SuspiciousnessScore
from ..testing.runner import TestCaseResult


@dataclass
class PreviousAttempt:
    """A previous repair attempt that failed."""
    attempt_number: int
    code: str
    test_results: list[TestCaseResult]
    compile_error: Optional[str] = None


@dataclass
class RepairPromptContext:
    """Context for building a repair prompt."""
    source_code: str
    source_filename: str = "controller.c"
    header_code: Optional[str] = None
    header_filename: Optional[str] = None
    suspicious_lines: list[SuspiciousnessScore] = field(default_factory=list)
    test_results: list[TestCaseResult] = field(default_factory=list)
    previous_attempts: list[PreviousAttempt] = field(default_factory=list)
    failing_test_input: Optional[str] = None


SYSTEM_PROMPT = """\
You are an expert C programmer specializing in debugging and repairing buggy code.
Your task is to analyze the provided C source code and fix any bugs you find.

IMPORTANT INSTRUCTIONS:
1. Return ONLY the complete, repaired source code file
2. Do NOT include any explanations, comments about your changes, or markdown formatting
3. Do NOT use code fences (```) or any other markup
4. The code must compile without errors
5. Preserve the original structure and formatting where possible
6. Only modify what is necessary to fix the bug(s)

Your response should be the raw C source code that can be directly saved to a file and compiled.
"""


def _numbered_source(code: str) -> str:
    """Add line numbers to source code."""
    lines = code.split('\n')
    width = len(str(len(lines)))
    return '\n'.join(f"{i+1:>{width}} | {line}" for i, line in enumerate(lines))


def _format_suspicious_lines(scores: list[SuspiciousnessScore]) -> str:
    """Format SBFL results as a ranked list."""
    parts = []
    for rank, s in enumerate(scores, 1):
        text = s.source_text.strip() if s.source_text else ""
        parts.append(f"  {rank:>2}. Line {s.line}: score={s.score:.3f}  {text}")
    return '\n'.join(parts)


def _format_test_results(results: list[TestCaseResult]) -> str:
    """Format test case results."""
    parts = []
    for r in results:
        if r.passed:
            parts.append(f"  {r.test_name}: PASS ({r.iterations_run}/{r.iterations_total} iterations)")
        else:
            parts.append(f"  {r.test_name}: FAIL at iteration {r.failed_at_iteration} — {r.failure_reason}")
    return '\n'.join(parts)


def _format_previous_attempt(attempt: PreviousAttempt) -> str:
    """Format a single previous attempt."""
    parts = [f"Attempt {attempt.attempt_number}:"]
    if attempt.compile_error:
        parts.append(f"  Compilation failed: {attempt.compile_error}")
    else:
        parts.append(_format_test_results(attempt.test_results))
    return '\n'.join(parts)


def build_repair_prompt(context: RepairPromptContext) -> str:
    """Build the user prompt for a repair request."""
    parts = []

    # Header file
    if context.header_code and context.header_filename:
        parts.append(f"=== Header: {context.header_filename} ===")
        parts.append(context.header_code)
        parts.append("")

    # Source with line numbers
    parts.append(f"=== Source: {context.source_filename} ===")
    parts.append(_numbered_source(context.source_code))
    parts.append("")

    # Fault localization
    if context.suspicious_lines:
        parts.append("=== Fault Localization (most suspicious lines) ===")
        parts.append(_format_suspicious_lines(context.suspicious_lines))
        parts.append("")

    # Test results
    if context.test_results:
        parts.append("=== Test Results ===")
        parts.append(_format_test_results(context.test_results))
        parts.append("")

    # Failing test input data
    if context.failing_test_input:
        parts.append("=== Failing Test Input (deserialized binary) ===")
        parts.append(context.failing_test_input)
        parts.append("")

    # Previous attempts
    if context.previous_attempts:
        parts.append("=== Previous Failed Attempts ===")
        for attempt in context.previous_attempts:
            parts.append(_format_previous_attempt(attempt))
            parts.append("")

    parts.append("Fix the bug(s) and return the complete repaired source file.")

    return '\n'.join(parts)


def load_repair_context(
    source_path: Path,
    header_path: Optional[Path] = None
) -> RepairPromptContext:
    """Load repair context from file paths (source and header only)."""
    source_code = Path(source_path).read_text()
    source_filename = Path(source_path).name

    header_code = None
    header_filename = None
    if header_path:
        hp = Path(header_path)
        if hp.exists():
            header_code = hp.read_text()
            header_filename = hp.name

    return RepairPromptContext(
        source_code=source_code,
        source_filename=source_filename,
        header_code=header_code,
        header_filename=header_filename,
    )
