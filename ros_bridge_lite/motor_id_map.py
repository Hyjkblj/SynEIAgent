"""Motor CAN ID ↔ joint index mapping for 天工 Lite (20 joints).

Port of bodyIdMap.h. Index order: left leg(0-5), right leg(6-11),
left arm(12-15), right arm(16-19).
"""

from __future__ import annotations

# Index → CAN ID
INDEX_TO_CAN_ID: dict[int, int] = {
    0: 51, 1: 52, 2: 53, 3: 54, 4: 55, 5: 56,   # left leg
    6: 61, 7: 62, 8: 63, 9: 64, 10: 65, 11: 66,  # right leg
    12: 11, 13: 12, 14: 13, 15: 14,               # left arm
    16: 21, 17: 22, 18: 23, 19: 24,               # right arm
}

# CAN ID → Index
CAN_ID_TO_INDEX: dict[int, int] = {v: k for k, v in INDEX_TO_CAN_ID.items()}

# Index → joint name
INDEX_TO_NAME: dict[int, str] = {
    0: "l_hip_roll", 1: "l_hip_pitch", 2: "l_hip_yaw",
    3: "l_knee", 4: "l_ankle_pitch", 5: "l_ankle_roll",
    6: "r_hip_roll", 7: "r_hip_pitch", 8: "r_hip_yaw",
    9: "r_knee", 10: "r_ankle_pitch", 11: "r_ankle_roll",
    12: "l_shoulder_pitch", 13: "l_shoulder_roll",
    14: "l_shoulder_yaw", 15: "l_elbow",
    16: "r_shoulder_pitch", 17: "r_shoulder_roll",
    18: "r_shoulder_yaw", 19: "r_elbow",
}

# Joint name → Index
NAME_TO_INDEX: dict[str, int] = {v: k for k, v in INDEX_TO_NAME.items()}

# Ordered joint names (index 0-19)
JOINT_NAMES: tuple[str, ...] = tuple(INDEX_TO_NAME[i] for i in range(20))

# Ankle joint indices (serial-parallel mechanism)
ANKLE_INDICES: tuple[int, ...] = (4, 5, 10, 11)  # l_ankle_pitch, l_ankle_roll, r_ankle_pitch, r_ankle_roll


def get_index_by_id(can_id: int) -> int:
    return CAN_ID_TO_INDEX.get(can_id, -1)


def get_id_by_index(index: int) -> int:
    return INDEX_TO_CAN_ID.get(index, -1)


def get_name_by_index(index: int) -> str:
    return INDEX_TO_NAME.get(index, "")


def get_index_by_name(name: str) -> int:
    return NAME_TO_INDEX.get(name, -1)
