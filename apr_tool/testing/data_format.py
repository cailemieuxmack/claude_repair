"""
Binary data format for controller IPC.

Parses Vote (controller output) from the binary format defined in controller.h.
Only extracts the fields we need: idx, positions, and velocities.
"""

import struct
from dataclasses import dataclass
from pathlib import Path


# struct format for MappedJointTrajectoryPoint
# Q=size_t, 100d=double[100], i=int32, I=uint32
POINT_FORMAT = 'Q100dQ100dQ100dQ100diI'

# struct format for Vote (OutStruct): int32 idx + point
VOTE_FORMAT = 'i' + POINT_FORMAT

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
