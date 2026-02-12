"""Spectrum-based fault localization module."""

from .sbfl import CoverageMatrix, SBFLLocalizer, SuspiciousnessMetric

__all__ = ["CoverageMatrix", "SBFLLocalizer", "SuspiciousnessMetric"]
