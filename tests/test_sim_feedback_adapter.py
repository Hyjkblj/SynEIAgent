from __future__ import annotations

import types

from ros_bridge_lite.sim_feedback_adapter import (
    URDF_JOINT_ORDER,
    SimFeedbackAdapter,
    cmd_motor_ctrl_to_urdf_targets,
)


def _cmd(name: int, pos: float) -> types.SimpleNamespace:
    return types.SimpleNamespace(name=name, pos=pos)


def test_cmd_motor_ctrl_to_urdf_targets_maps_can_ids_to_official_lite_joint_names() -> None:
    msg = types.SimpleNamespace(
        cmds=[
            _cmd(55, -0.42),  # l_ankle_pitch
            _cmd(66, 0.18),   # r_ankle_roll
            _cmd(14, -0.31),  # l_elbow
        ]
    )

    targets = cmd_motor_ctrl_to_urdf_targets(msg)

    assert targets == {
        "ankle_pitch_l_joint": -0.42,
        "ankle_roll_r_joint": 0.18,
        "elbow_pitch_l_joint": -0.31,
    }


def test_sim_adapter_merges_leg_and_arm_cmd_ctrl_before_publishing() -> None:
    published: list[types.SimpleNamespace] = []

    adapter = types.SimpleNamespace(
        _have_leg_cmd=False,
        _have_arm_cmd=False,
        _latest_joint_targets={},
        _joint_state_type=lambda: types.SimpleNamespace(
            header=types.SimpleNamespace(stamp=None),
            name=[],
            position=[],
            velocity=[],
            effort=[],
        ),
        _joint_cmd_pub=types.SimpleNamespace(publish=lambda msg: published.append(msg)),
        _node=None,
        _cmd_count=0,
    )

    from ros_bridge_lite.sim_feedback_adapter import SimFeedbackAdapter
    adapter._publish_joint_targets = lambda joint_targets: SimFeedbackAdapter._publish_joint_targets(adapter, joint_targets)
    adapter._on_cmd_motor_ctrl = lambda msg: SimFeedbackAdapter._on_cmd_motor_ctrl(adapter, msg)

    SimFeedbackAdapter._on_leg_cmd_ctrl(
        adapter,
        types.SimpleNamespace(cmds=[_cmd(51, 0.11), _cmd(55, -0.22)]),
    )
    assert published == []

    SimFeedbackAdapter._on_arm_cmd_ctrl(
        adapter,
        types.SimpleNamespace(cmds=[_cmd(11, 0.33), _cmd(24, -0.44)]),
    )

    assert len(published) == 1
    out = published[0]
    assert out.velocity == []
    assert out.effort == []
    assert adapter._cmd_count == 1

    published_targets = dict(zip(out.name, out.position, strict=False))
    assert published_targets["hip_roll_l_joint"] == 0.11
    assert published_targets["ankle_pitch_l_joint"] == -0.22
    assert published_targets["shoulder_pitch_l_joint"] == 0.33
    assert published_targets["elbow_pitch_r_joint"] == -0.44

    # The merged payload should preserve the canonical whole-body ordering
    # for any joints that are present in this frame.
    expected_order = [name for name in URDF_JOINT_ORDER if name in published_targets]
    assert out.name == expected_order


def test_sim_adapter_joint_states_publish_top_level_motor_status_items() -> None:
    published_leg: list[types.SimpleNamespace] = []
    published_arm: list[types.SimpleNamespace] = []
    published_imu: list[types.SimpleNamespace] = []

    class _MotorStatus:
        def __init__(self) -> None:
            self.name = 0
            self.pos = 0.0
            self.speed = 0.0
            self.current = 0.0

    class _MotorStatusMsg:
        def __init__(self) -> None:
            self.header = types.SimpleNamespace(stamp=None)
            self.status = []

    adapter = types.SimpleNamespace(
        _motor_status_type=_MotorStatusMsg,
        _motor_status_item_type=_MotorStatus,
        _leg_pub=types.SimpleNamespace(publish=lambda msg: published_leg.append(msg)),
        _arm_pub=types.SimpleNamespace(publish=lambda msg: published_arm.append(msg)),
        _imu_pub=types.SimpleNamespace(publish=lambda msg: published_imu.append(msg)),
        _imu_type=lambda: types.SimpleNamespace(
            header=types.SimpleNamespace(stamp=None),
            euler=types.SimpleNamespace(yaw=0.0, pitch=0.0, roll=0.0),
            angular_velocity=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
            linear_acceleration=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
        ),
        _node=None,
        _js_count=0,
        _publish_imu=lambda: SimFeedbackAdapter._publish_imu(adapter),
    )

    msg = types.SimpleNamespace(
        name=["hip_roll_l_joint", "shoulder_pitch_r_joint"],
        position=[0.1, -0.2],
        velocity=[0.3, -0.4],
        effort=[0.5, -0.6],
    )

    SimFeedbackAdapter._on_joint_states(adapter, msg)

    assert len(published_leg) == 1
    assert len(published_arm) == 1
    assert len(published_imu) == 1
    assert isinstance(published_leg[0].status[0], _MotorStatus)
    assert isinstance(published_arm[0].status[0], _MotorStatus)
