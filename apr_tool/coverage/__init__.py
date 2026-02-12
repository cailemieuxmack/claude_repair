"""Coverage collection module for SBFL."""

from .collector import CoverageCollector
from .gcov_parser import GcovParser

__all__ = ["CoverageCollector", "GcovParser"]
