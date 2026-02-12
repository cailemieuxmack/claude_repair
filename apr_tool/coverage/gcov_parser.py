"""
Parser for gcov output files.

Gcov produces .gcov files that show line-by-line execution counts.
This module parses those files to extract which lines were executed.
"""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class GcovLine:
    """Parsed information about a single line from gcov output."""
    line_number: int
    execution_count: Optional[int]  # None for non-executable lines
    source_text: str
    is_executable: bool

    @property
    def was_executed(self) -> bool:
        """Return True if this line was executed at least once."""
        return self.execution_count is not None and self.execution_count > 0


class GcovParser:
    """
    Parser for gcov .gcov files.

    Gcov file format:
        execution_count:line_number:source_text

    Where execution_count can be:
        - A number (times executed)
        - '-' (non-executable line, e.g., blank or comment)
        - '#####' (executable but never executed)
        - '=====' (exceptional case, treated as not executed)
    """

    # Regex to match gcov line format
    # Format: <count>:<line_no>:<source>
    LINE_PATTERN = re.compile(
        r'^\s*([0-9]+|-|#####|=====|\*+):\s*(\d+):(.*)$'
    )

    def parse_file(self, gcov_path: Path) -> list[GcovLine]:
        """
        Parse a .gcov file and return list of GcovLine objects.

        Args:
            gcov_path: Path to the .gcov file

        Returns:
            List of GcovLine objects for each line in the file
        """
        lines = []

        with open(gcov_path, 'r', errors='replace') as f:
            for raw_line in f:
                parsed = self._parse_line(raw_line)
                if parsed is not None:
                    lines.append(parsed)

        return lines

    def _parse_line(self, raw_line: str) -> Optional[GcovLine]:
        """Parse a single line from gcov output."""
        match = self.LINE_PATTERN.match(raw_line)
        if not match:
            return None

        count_str, line_num_str, source_text = match.groups()
        line_number = int(line_num_str)

        # Line 0 is the header, skip it
        if line_number == 0:
            return None

        # Parse execution count
        if count_str == '-':
            # Non-executable line (blank, comment, etc.)
            execution_count = None
            is_executable = False
        elif count_str in ('#####', '=====') or count_str.startswith('*'):
            # Executable but not executed
            execution_count = 0
            is_executable = True
        else:
            # Executed some number of times
            try:
                execution_count = int(count_str)
                is_executable = True
            except ValueError:
                execution_count = None
                is_executable = False

        return GcovLine(
            line_number=line_number,
            execution_count=execution_count,
            source_text=source_text,
            is_executable=is_executable
        )

    def get_executed_lines(self, gcov_path: Path) -> set[int]:
        """
        Get set of line numbers that were executed.

        Args:
            gcov_path: Path to the .gcov file

        Returns:
            Set of line numbers that were executed at least once
        """
        lines = self.parse_file(gcov_path)
        return {line.line_number for line in lines if line.was_executed}

    def get_executable_lines(self, gcov_path: Path) -> set[int]:
        """
        Get set of line numbers that are executable (could be executed).

        Args:
            gcov_path: Path to the .gcov file

        Returns:
            Set of line numbers that are executable
        """
        lines = self.parse_file(gcov_path)
        return {line.line_number for line in lines if line.is_executable}

    def get_not_executed_lines(self, gcov_path: Path) -> set[int]:
        """
        Get set of executable line numbers that were NOT executed.

        Args:
            gcov_path: Path to the .gcov file

        Returns:
            Set of line numbers that could have been executed but weren't
        """
        lines = self.parse_file(gcov_path)
        return {
            line.line_number for line in lines
            if line.is_executable and not line.was_executed
        }
