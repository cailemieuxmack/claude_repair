"""
Binary data format for controller IPC.

Parses Vote (controller output) and State (controller input) from the
binary formats defined in controller.h.
"""

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# struct format for MappedJointTrajectoryPoint
# Q=size_t, 100d=double[100], i=int32, I=uint32
POINT_FORMAT = 'Q100dQ100dQ100dQ100diI'

# struct format for Vote (OutStruct): int32 idx + point
VOTE_FORMAT = 'i' + POINT_FORMAT

POINT_SIZE = struct.calcsize(POINT_FORMAT)
VOTE_SIZE = struct.calcsize(VOTE_FORMAT)


@dataclass
class Vote:
    """Controller output: index + positions and velocities."""
    idx: int
    positions: list[float]
    velocities: list[float]

    def get_comparison_vector(self, num_joints: int = 6) -> list[float]:
        """positions[:num_joints] + velocities[:num_joints] for cosine distance."""
        return self.positions[:num_joints] + self.velocities[:num_joints]


def parse_vote(data: bytes) -> Vote:
    """Parse a Vote from raw bytes."""
    unpacked = struct.unpack(VOTE_FORMAT, data[:VOTE_SIZE])
    idx = unpacked[0]
    # offsets: [0]=idx, [1]=positions_length, [2:102]=positions,
    #          [102]=velocities_length, [103:203]=velocities
    positions = list(unpacked[2:102])
    velocities = list(unpacked[103:203])
    return Vote(idx=idx, positions=positions, velocities=velocities)


def parse_vote_file(path: Path) -> Vote:
    """Parse a Vote from a binary file."""
    with open(path, 'rb') as f:
        return parse_vote(f.read(VOTE_SIZE))


# ---------------------------------------------------------------------------
# State (controller input) parsing
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryPoint:
    """A single trajectory point with all fields from MappedJointTrajectoryPoint."""
    positions_length: int
    positions: list[float]
    velocities_length: int
    velocities: list[float]
    accelerations_length: int
    accelerations: list[float]
    effort_length: int
    effort: list[float]
    time_from_start_sec: int
    time_from_start_nsec: int


@dataclass
class State:
    """Controller input parsed from a binary test input file.

    Layout (CovState from coverage_driver.cpp / test_driver.cpp):
        int idx
        MappedJointTrajectory value  (joint_names + points[256])
        int32_t cur_time_seconds
    """
    idx: int
    cur_time_seconds: int
    joint_names: list[str]
    points_length: int
    points: list[TrajectoryPoint] = field(default_factory=list)


def _parse_point(data: bytes, offset: int) -> TrajectoryPoint:
    """Parse a single MappedJointTrajectoryPoint at the given byte offset."""
    pt = struct.unpack_from(POINT_FORMAT, data, offset)
    pos_len = int(pt[0])
    vel_len = int(pt[101])
    acc_len = int(pt[202])
    eff_len = int(pt[303])
    return TrajectoryPoint(
        positions_length=pos_len,
        positions=list(pt[1:1 + min(pos_len, 100)]),
        velocities_length=vel_len,
        velocities=list(pt[102:102 + min(vel_len, 100)]),
        accelerations_length=acc_len,
        accelerations=list(pt[203:203 + min(acc_len, 100)]),
        effort_length=eff_len,
        effort=list(pt[304:304 + min(eff_len, 100)]),
        time_from_start_sec=pt[404],
        time_from_start_nsec=pt[405],
    )


def parse_state(data: bytes) -> State:
    """Parse a State from raw bytes.

    Uses manual offsets because the actual binary layout has padding
    that doesn't match struct.calcsize exactly.
    """
    offset = 0

    # int idx (4 bytes) + 4 bytes padding to align to 8-byte boundary
    idx = struct.unpack_from('i', data, offset)[0]
    offset += 8

    # MappedJointTrajectory.joint_names_length (size_t = 8 bytes)
    joint_names_length = struct.unpack_from('Q', data, offset)[0]
    offset += 8

    # joint_names[10][256] = 2560 bytes
    joint_names = []
    for j in range(10):
        name_bytes = data[offset + j * 256:offset + (j + 1) * 256]
        name = name_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
        if name:
            joint_names.append(name)
    offset += 2560

    # points_length (size_t = 8 bytes)
    points_length = struct.unpack_from('Q', data, offset)[0]
    offset += 8

    # Parse trajectory points (up to points_length, max 256)
    num_points = min(int(points_length), 256)
    points = []
    for p in range(num_points):
        points.append(_parse_point(data, offset + p * POINT_SIZE))

    # cur_time_seconds is after the full 256-point array
    cur_time_offset = offset + 256 * POINT_SIZE
    cur_time_seconds = struct.unpack_from('i', data, cur_time_offset)[0]

    return State(
        idx=idx,
        cur_time_seconds=cur_time_seconds,
        joint_names=joint_names,
        points_length=int(points_length),
        points=points,
    )


def parse_state_file(path: Path) -> State:
    """Parse a State from a binary test input file."""
    with open(path, 'rb') as f:
        return parse_state(f.read())


def format_state_text(state: State) -> str:
    """Format a State as human-readable text for inclusion in a repair prompt."""
    lines = [
        f"idx: {state.idx}",
        f"cur_time_seconds: {state.cur_time_seconds}",
        f"joint_names ({len(state.joint_names)}): {state.joint_names}",
        f"points_length: {state.points_length}",
    ]
    for i, pt in enumerate(state.points):
        fields = [
            f"positions({pt.positions_length})={pt.positions}",
            f"velocities({pt.velocities_length})={pt.velocities}",
            f"accelerations({pt.accelerations_length})={pt.accelerations}",
            f"effort({pt.effort_length})={pt.effort}",
            f"time={pt.time_from_start_sec}s+{pt.time_from_start_nsec}ns",
        ]
        lines.append(f"  point[{i}]: " + ", ".join(fields))
    return "\n".join(lines)
