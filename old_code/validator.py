"""
Validation logic for controller outputs.

This module implements the validation criteria for determining if a
controller's output matches the expected oracle output.

Validation Criteria:
1. Index Match: controller_output.idx == oracle_output.idx
2. Cosine Distance: cosine_distance(controller_vec, oracle_vec) <= epsilon

Where:
- controller_vec = positions[0:6] + velocities[0:6] (12 values)
- oracle_vec = positions[0:6] + velocities[0:6] (12 values)
- epsilon = 0.5 (default)
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .data_format import Vote


class FailureReason(Enum):
    """Reasons why validation can fail."""
    NONE = "none"
    INDEX_MISMATCH = "index_mismatch"
    COSINE_DISTANCE_EXCEEDED = "cosine_distance_exceeded"
    TIMEOUT = "timeout"
    CONTROLLER_CRASH = "controller_crash"
    PARSE_ERROR = "parse_error"


@dataclass
class ValidationResult:
    """
    Result of validating a single iteration.

    Attributes:
        passed: Whether the iteration passed validation
        reason: Why validation failed (if it failed)
        controller_idx: Index returned by controller
        oracle_idx: Expected index from oracle
        cosine_distance: Computed cosine distance (if applicable)
        epsilon: Threshold used for comparison
        details: Additional details about the failure
    """
    passed: bool
    reason: FailureReason = FailureReason.NONE
    controller_idx: Optional[int] = None
    oracle_idx: Optional[int] = None
    cosine_distance: Optional[float] = None
    epsilon: Optional[float] = None
    details: Optional[str] = None

    def __str__(self) -> str:
        if self.passed:
            return f"PASS (distance={self.cosine_distance:.4f})" if self.cosine_distance else "PASS"

        if self.reason == FailureReason.INDEX_MISMATCH:
            return f"FAIL: index mismatch ({self.controller_idx} != {self.oracle_idx})"
        elif self.reason == FailureReason.COSINE_DISTANCE_EXCEEDED:
            return f"FAIL: cosine_distance={self.cosine_distance:.4f} > {self.epsilon}"
        elif self.reason == FailureReason.TIMEOUT:
            return f"FAIL: timeout - {self.details}"
        elif self.reason == FailureReason.CONTROLLER_CRASH:
            return f"FAIL: controller crash - {self.details}"
        elif self.reason == FailureReason.PARSE_ERROR:
            return f"FAIL: parse error - {self.details}"
        else:
            return f"FAIL: {self.details}"


def dot_product(v1: list[float], v2: list[float]) -> float:
    """Compute dot product of two vectors."""
    if len(v1) != len(v2):
        raise ValueError(f"Vector lengths don't match: {len(v1)} != {len(v2)}")
    return sum(a * b for a, b in zip(v1, v2))


def vector_norm(v: list[float]) -> float:
    """Compute Euclidean norm (L2 norm) of a vector."""
    return math.sqrt(sum(x * x for x in v))


def cosine_distance(vec1: list[float], vec2: list[float]) -> float:
    """
    Calculate cosine distance between two vectors.

    Cosine distance = 1 - cosine_similarity
    Range: [0, 2] where 0 means identical direction, 2 means opposite

    Special cases:
    - If both vectors are zero: return 0.0 (identical)
    - If only one vector is zero: return 1.0 (maximally dissimilar)

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine distance between the vectors
    """
    if len(vec1) != len(vec2):
        raise ValueError(f"Vector lengths don't match: {len(vec1)} != {len(vec2)}")

    norm1 = vector_norm(vec1)
    norm2 = vector_norm(vec2)

    # Handle zero vectors
    if norm1 == 0 and norm2 == 0:
        return 0.0  # Both zero vectors are considered identical

    if norm1 == 0 or norm2 == 0:
        return 1.0  # One zero vector means maximally dissimilar

    # Compute cosine similarity
    dot = dot_product(vec1, vec2)
    cosine_similarity = dot / (norm1 * norm2)

    # Clamp to [-1, 1] to handle floating point errors
    cosine_similarity = max(-1.0, min(1.0, cosine_similarity))

    # Convert to distance
    return 1.0 - cosine_similarity


def validate_iteration(
    controller_vote: Vote,
    oracle_vote: Vote,
    epsilon: float = 0.5,
    num_joints: int = 6
) -> ValidationResult:
    """
    Validate a single iteration's output against the oracle.

    Checks:
    1. Index match: controller_vote.idx == oracle_vote.idx
    2. Cosine distance: distance(controller_vec, oracle_vec) <= epsilon

    Args:
        controller_vote: Output from the controller
        oracle_vote: Expected output from oracle file
        epsilon: Maximum allowed cosine distance (default: 0.5)
        num_joints: Number of joints to use for comparison (default: 6)

    Returns:
        ValidationResult indicating pass/fail and details
    """
    # Check index match
    if controller_vote.idx != oracle_vote.idx:
        return ValidationResult(
            passed=False,
            reason=FailureReason.INDEX_MISMATCH,
            controller_idx=controller_vote.idx,
            oracle_idx=oracle_vote.idx,
            details=f"Controller index {controller_vote.idx} != oracle index {oracle_vote.idx}"
        )

    # Get comparison vectors
    controller_vec = controller_vote.get_comparison_vector(num_joints)
    oracle_vec = oracle_vote.get_comparison_vector(num_joints)

    # Compute cosine distance
    distance = cosine_distance(controller_vec, oracle_vec)

    # Check if within epsilon
    if distance <= epsilon:
        return ValidationResult(
            passed=True,
            reason=FailureReason.NONE,
            controller_idx=controller_vote.idx,
            oracle_idx=oracle_vote.idx,
            cosine_distance=distance,
            epsilon=epsilon
        )
    else:
        return ValidationResult(
            passed=False,
            reason=FailureReason.COSINE_DISTANCE_EXCEEDED,
            controller_idx=controller_vote.idx,
            oracle_idx=oracle_vote.idx,
            cosine_distance=distance,
            epsilon=epsilon,
            details=f"Cosine distance {distance:.4f} exceeds threshold {epsilon}"
        )


def validate_votes_raw(
    controller_data: bytes,
    oracle_data: bytes,
    epsilon: float = 0.5,
    num_joints: int = 6
) -> ValidationResult:
    """
    Validate controller output against oracle from raw bytes.

    Args:
        controller_data: Raw bytes of controller's Vote output
        oracle_data: Raw bytes of oracle's expected Vote
        epsilon: Maximum allowed cosine distance
        num_joints: Number of joints to compare

    Returns:
        ValidationResult
    """
    from .data_format import parse_vote

    try:
        controller_vote = parse_vote(controller_data)
    except Exception as e:
        return ValidationResult(
            passed=False,
            reason=FailureReason.PARSE_ERROR,
            details=f"Failed to parse controller output: {e}"
        )

    try:
        oracle_vote = parse_vote(oracle_data)
    except Exception as e:
        return ValidationResult(
            passed=False,
            reason=FailureReason.PARSE_ERROR,
            details=f"Failed to parse oracle output: {e}"
        )

    return validate_iteration(controller_vote, oracle_vote, epsilon, num_joints)
