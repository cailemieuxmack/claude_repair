"""
Claude API client for code repair.

Uses the Anthropic SDK to call the Claude API.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

from .prompt_builder import (
    SYSTEM_PROMPT,
    RepairPromptContext,
    build_repair_prompt,
    load_repair_context,
)
from .response_parser import parse_repair_response


@dataclass
class RepairResponse:
    """Response from a repair request."""
    repaired_code: str
    raw_response: str
    model: str
    input_tokens: int
    output_tokens: int


class ClaudeClient:
    """
    Client for calling Claude API to repair code.

    Usage:
        client = ClaudeClient()
        response = client.repair(source_path="controller.c")
        print(response.repaired_code)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def repair(
        self,
        source_path: Path,
        header_path: Optional[Path] = None,
    ) -> RepairResponse:
        """Request a repair for the given source file."""
        context = load_repair_context(source_path, header_path)
        return self.repair_from_context(context)

    def repair_from_context(self, context: RepairPromptContext) -> RepairResponse:
        """Request a repair using a pre-built context."""
        user_prompt = build_repair_prompt(context)

        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
        )

        raw_response = message.content[0].text
        repaired_code = parse_repair_response(raw_response)

        return RepairResponse(
            repaired_code=repaired_code,
            raw_response=raw_response,
            model=self.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
