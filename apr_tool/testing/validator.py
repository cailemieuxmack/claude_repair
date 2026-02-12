"""
Validation logic for controller outputs.

Compares controller output against oracle using:
1. Index match: controller.idx == oracle.idx
2. Cosine distance on positions[0:6] + velocities[0:6] <= epsilon
"""

import math
from dataclasses import dataclass

from .data_format import Vote


@dataclass
class ValidationResult:
    """Result of validating a single iteration."""
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        return self.detail if self.detail else ("PASS" if self.passed else "FAIL")


def cosine_distance(vec1: list[float], vec2: list[float]) -> float:
    """
    Cosine distance = 1 - cosine_similarity.

    Returns 0.0 if both zero, 1.0 if one is zero.
    """
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(x * x for x in vec1))
    norm2 = math.sqrt(sum(x * x for x in vec2))

    if norm1 == 0 and norm2 == 0:
        return 0.0
    if norm1 == 0 or norm2 == 0:
        return 1.0

    similarity = max(-1.0, min(1.0, dot / (norm1 * norm2)))
    return 1.0 - similarity


def validate_iteration(
    controller_vote: Vote,
    oracle_vote: Vote,
    epsilon: float = 0.5,
    num_joints: int = 6
) -> ValidationResult:
    """Validate controller output against oracle."""
    if controller_vote.idx != oracle_vote.idx:
        return ValidationResult(
            passed=False,
            detail=f"FAIL: index mismatch ({controller_vote.idx} != {oracle_vote.idx})"
        )

    controller_vec = controller_vote.get_comparison_vector(num_joints)
    oracle_vec = oracle_vote.get_comparison_vector(num_joints)
    distance = cosine_distance(controller_vec, oracle_vec)

    if distance <= epsilon:
        return ValidationResult(passed=True, detail=f"PASS (distance={distance:.4f})")
    else:
        return ValidationResult(
            passed=False,
            detail=f"FAIL: cosine_distance={distance:.4f} > {epsilon}"
        )
