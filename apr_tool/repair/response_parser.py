"""
Response parser for repair responses.

Extracts the repaired code from the LLM response.
"""

import re


def _strip_prompt_scaffolding(text: str) -> str:
    """
    Strip prompt scaffolding that the model may have echoed back.

    Handles two cases:
    1. The model echoed the full prompt (=== Header/Source === sections with
       line-numbered source). Extract only the === Source === section content.
    2. Lines prefixed with line numbers from _numbered_source ("  1 | code").
       Strip the prefix so the result is plain C source.
    """
    # If the text contains prompt section markers, extract the Source section
    if '=== Source:' in text:
        # Find the source section and grab everything up to the next === or end
        source_match = re.search(
            r'=== Source:[^\n]*\n(.*?)(?===|\Z)', text, re.DOTALL
        )
        if source_match:
            text = source_match.group(1).strip()

    # Strip line-number prefixes of the form "  42 | " added by _numbered_source
    line_number_prefix = re.compile(r'^\s*\d+\s*\| ?', re.MULTILINE)
    if line_number_prefix.search(text):
        text = line_number_prefix.sub('', text)

    return text.strip()


def parse_repair_response(response_text: str) -> str:
    """
    Parse the LLM response to extract the repaired code.

    The LLM is instructed to return raw code only, but this function
    handles cases where it might include markdown code fences or echo
    back the prompt scaffolding (=== Header/Source === sections).

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
        return _strip_prompt_scaffolding(match.group(1))

    # Also handle case where there might be text before/after fences
    fence_pattern_loose = r'```(?:\w+)?\s*\n(.*?)\n```'
    match = re.search(fence_pattern_loose, text, re.DOTALL)
    if match:
        return _strip_prompt_scaffolding(match.group(1))

    # No fences found — strip scaffolding from raw text
    return _strip_prompt_scaffolding(text)
