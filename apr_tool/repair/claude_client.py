"""
Claude API client for code repair.

Uses the Anthropic SDK to call the Claude API.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import requests
import os

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
        #self.client = anthropic.Anthropic(api_key=api_key)
        self.api_key = api_key
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

        response = requests.post(
            "https://o.cumberland.isis.vanderbilt.edu/api/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['API_KEY']}",
                "Content-Type": "application/json"
            },
            json={
                "model": "nemotron-3-nano:30b-a3b-q8_0",
                "messages": [
                    {"role": "user", "content": user_prompt}
                ]
            }
        )

        data = response.json()
        print(data["choices"][0]["message"]["content"])

        repaired_code = parse_repair_response(data) # data["choices"][0]["message"]["content"] # 

        return RepairResponse(
            repaired_code=repaired_code,
            raw_response=data,
            model=self.model,
            input_tokens=0, # FIXME
            output_tokens=0, # FIXME
        )
