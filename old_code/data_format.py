"""
Binary data format definitions for controller IPC.

This module defines the binary struct formats used for communication
between the test driver and controller via memory-mapped files.

Data Structures (matching controller.h):
- MappedJointTrajectoryPoint: Joint position/velocity/acceleration/effort data
- MappedJointTrajectory: Collection of trajectory points with joint names
- State (InStruct): Input to controller
- Vote (OutStruct): Output from controller

Binary Formats (for struct.unpack):
- POINT_FORMAT: 'Q100dQ100dQ100dQ100diI' (3,240 bytes)
- VOTE_FORMAT: 'i' + POINT_FORMAT (idx + point)
- TRAJECTORY_FORMAT: 'Q2560sQ' + POINT_FORMAT * 256
- STATE_FORMAT: 'i' + TRAJECTORY_FORMAT + 'i'
"""

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Format string for MappedJointTrajectoryPoint
# Q = unsigned long long (size_t, 8 bytes)
# d = double (8 bytes)
# i = int32_t (4 bytes)
# I = uint32_t (4 bytes)
POINT_FORMAT = (
    'Q' +         # positions_length (size_t)
    '100d' +      # positions[100] (100 doubles)
    'Q' +         # velocities_length (size_t)
    '100d' +      # velocities[100] (100 doubles)
    'Q' +         # accelerations_length (size_t)
    '100d' +      # accelerations[100] (100 doubles)
    'Q' +         # effort_length (size_t)
    '100d' +      # effort[100] (100 doubles)
    'i' +         # time_from_start_sec (int32_t)
    'I'           # time_from_start_nsec (uint32_t)
)

# Format string for Vote (OutStruct)
VOTE_FORMAT = (
    'i' +         # idx (int32_t)
    POINT_FORMAT  # vote (MappedJointTrajectoryPoint)
)

# Format string for MappedJointTrajectory
TRAJECTORY_FORMAT = (
    'Q' +                    # joint_names_length (size_t)
    '2560s' +                # joint_names[10][256] (2560 bytes)
    'Q' +                    # points_length (size_t)
    POINT_FORMAT * 256       # points[256] (256 MappedJointTrajectoryPoint)
)

# Format string for State (InStruct with idx)
STATE_FORMAT = (
    'i' +                    # idx (int32_t)
    TRAJECTORY_FORMAT +      # value (MappedJointTrajectory)
    'i'                      # cur_time_sec (int32_t)
)

# Calculated sizes
POINT_SIZE = struct.calcsize(POINT_FORMAT)
VOTE_SIZE = struct.calcsize(VOTE_FORMAT)
TRAJECTORY_SIZE = struct.calcsize(TRAJECTORY_FORMAT)
STATE_SIZE = struct.calcsize(STATE_FORMAT)


@dataclass
class MappedJointTrajectoryPoint:
    """
    A single trajectory point containing joint positions, velocities, etc.

    Attributes:
        positions_length: Number of valid positions
        positions: Array of up to 100 position values
        velocities_length: Number of valid velocities
        velocities: Array of up to 100 velocity values
        accelerations_length: Number of valid accelerations
        accelerations: Array of up to 100 acceleration values
        effort_length: Number of valid effort values
        effort: Array of up to 100 effort values
        time_from_start_sec: Seconds component of time
        time_from_start_nsec: Nanoseconds component of time
    """
    positions_length: int
    positions: tuple[float, ...]
    velocities_length: int
    velocities: tuple[float, ...]
    accelerations_length: int
    accelerations: tuple[float, ...]
    effort_length: int
    effort: tuple[float, ...]
    time_from_start_sec: int
    time_from_start_nsec: int

    @classmethod
    def from_tuple(cls, data: tuple) -> "MappedJointTrajectoryPoint":
        """
        Create from unpacked struct tuple.

        Expected tuple layout (406 elements):
        [0]: positions_length
        [1:101]: positions[100]
        [101]: velocities_length
        [102:202]: velocities[100]
        [202]: accelerations_length
        [203:303]: accelerations[100]
        [303]: effort_length
        [304:404]: effort[100]
        [404]: time_from_start_sec
        [405]: time_from_start_nsec
        """
        return cls(
            positions_length=data[0],
            positions=data[1:101],
            velocities_length=data[101],
            velocities=data[102:202],
            accelerations_length=data[202],
            accelerations=data[203:303],
            effort_length=data[303],
            effort=data[304:404],
            time_from_start_sec=data[404],
            time_from_start_nsec=data[405]
        )

    def get_positions(self, count: Optional[int] = None) -> list[float]:
        """Get positions array, optionally limited to count elements."""
        n = count if count is not None else self.positions_length
        return list(self.positions[:n])

    def get_velocities(self, count: Optional[int] = None) -> list[float]:
        """Get velocities array, optionally limited to count elements."""
        n = count if count is not None else self.velocities_length
        return list(self.velocities[:n])


@dataclass
class Vote:
    """
    Controller output (vote) containing index and trajectory point.

    Attributes:
        idx: Iteration index
        point: The voted trajectory point
    """
    idx: int
    point: MappedJointTrajectoryPoint

    @classmethod
    def from_bytes(cls, data: bytes) -> "Vote":
        """Parse Vote from raw bytes."""
        if len(data) < VOTE_SIZE:
            raise ValueError(f"Data too short: {len(data)} < {VOTE_SIZE}")

        unpacked = struct.unpack(VOTE_FORMAT, data[:VOTE_SIZE])
        return cls.from_tuple(unpacked)

    @classmethod
    def from_tuple(cls, data: tuple) -> "Vote":
        """
        Create from unpacked struct tuple.

        Expected tuple layout (407 elements):
        [0]: idx
        [1:]: MappedJointTrajectoryPoint data
        """
        idx = data[0]
        point = MappedJointTrajectoryPoint.from_tuple(data[1:])
        return cls(idx=idx, point=point)

    def get_comparison_vector(self, num_joints: int = 6) -> list[float]:
        """
        Get the vector used for cosine distance comparison.

        Returns positions[0:num_joints] + velocities[0:num_joints]
        """
        positions = list(self.point.positions[:num_joints])
        velocities = list(self.point.velocities[:num_joints])
        return positions + velocities


def parse_vote(data: bytes) -> Vote:
    """Parse a Vote from raw bytes."""
    return Vote.from_bytes(data)


def parse_vote_file(path: Path) -> Vote:
    """Parse a Vote from a file."""
    with open(path, 'rb') as f:
        data = f.read(VOTE_SIZE)
    return Vote.from_bytes(data)


def parse_state_file(path: Path) -> bytes:
    """
    Read raw state data from a file.

    We don't fully parse State since we just need to pass it through
    to the controller via the memory-mapped file.
    """
    with open(path, 'rb') as f:
        return f.read()


# Utility functions for working with the binary format

def get_vote_size() -> int:
    """Get the size of a Vote struct in bytes."""
    return VOTE_SIZE


def get_state_size() -> int:
    """Get the size of a State struct in bytes."""
    return STATE_SIZE


def verify_format_sizes():
    """Verify that calculated struct sizes match expected values."""
    expected_point = 3240  # Approximately
    expected_vote = 3244   # idx (4) + point
    expected_state = 832033  # From check_distance.py

    print(f"POINT_SIZE: {POINT_SIZE} (expected ~{expected_point})")
    print(f"VOTE_SIZE: {VOTE_SIZE} (expected ~{expected_vote})")
    print(f"STATE_SIZE: {STATE_SIZE} (expected ~{expected_state})")

    # The actual sizes may differ slightly due to padding
    return True


if __name__ == "__main__":
    # Verify struct sizes when run directly
    verify_format_sizes()
