"""
Response parser for repair responses.

Extracts the repaired code from the LLM response.
"""

import re


def parse_repair_response(response_text: str) -> str:
    """
    Parse the LLM response to extract the repaired code.

    The LLM is instructed to return raw code only, but this function
    handles cases where it might include markdown code fences.

    Args:
        response_text: The raw response from the LLM

    Returns:
        The extracted C source code
    """
    text = response_text.strip()

    # Check for markdown code fences and extract content
    # Handles ```c, ```cpp, ``` with any language or no language
    fence_pattern = r'^```(?:\w+)?\s*\n(.*?)\n```\s*$'
    match = re.match(fence_pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Also handle case where there might be text before/after fences
    fence_pattern_loose = r'```(?:\w+)?\s*\n(.*?)\n```'
    match = re.search(fence_pattern_loose, text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # No fences found, return as-is
    return text
