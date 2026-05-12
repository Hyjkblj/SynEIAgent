from __future__ import annotations

import time
import types
from pathlib import Path

import numpy as np
import pytest

from ros_bridge_lite.fsm_states import FSMStateName, RobotData, StateMLP, XboxFlag
from ros_bridge_lite.policy_config import PolicyConfig
from ros_bridge_lite.rl_policy_controller import RLPolicyController


def make_controller() -> RLPolicyController:
    return RLPolicyController(PolicyConfig(), None)


def test_transition_request_advances_stop_and_zero_with_zero_velocity() -> None:
    controller = make_controller()
    controller.request_gait_transition(1.0)
    controller.set_command(0.0, 0.0)

    controller._robot_fsm._current_name = FSMStateName.STOP
    assert controller._get_fsm_command() == "gotoZero"

    controller._robot_fsm._current_name = FSMStateName.ZERO
    assert controller._get_fsm_command() == "gotoMLP"


def test_stop_state_is_seeded_with_default_stand_pose_on_startup() -> None:
    controller = make_controller()
    stop_state = controller._robot_fsm._states[FSMStateName.STOP]

    assert np.allclose(stop_state._init_joint_pos, controller.cfg.default_dof_pos_np)


def test_clear_transition_request_cancels_zero_to_mlp_progression() -> None:
    controller = make_controller()
    controller.request_gait_transition(1.0)
    controller.clear_gait_transition_request()
    controller.set_command(0.0, 0.0)

    controller._robot_fsm._current_name = FSMStateName.STOP
    assert controller._get_fsm_command() == ""

    controller._robot_fsm._current_name = FSMStateName.ZERO
    assert controller._get_fsm_command() == ""


def test_pending_transition_keeps_zero_progress_alive_after_grace_expiry() -> None:
    controller = make_controller()
    controller.request_gait_transition(0.0)
    controller.set_command(0.0, 0.0)
    controller._robot_fsm._current_name = FSMStateName.ZERO

    assert controller._get_fsm_command() == "gotoMLP"


def test_pending_transition_clears_after_mlp_entry() -> None:
    controller = make_controller()
    zero_state = controller._robot_fsm._states[FSMStateName.ZERO]
    controller._robot_fsm._current_name = FSMStateName.ZERO
    controller._robot_fsm._current_state = zero_state
    controller._pending_gait_transition = True
    controller._transition_request_until = time.monotonic() - 1.0
    zero_state._zero_finish = True

    controller.update(controller.cfg.dt)

    assert controller._robot_fsm.current_state == FSMStateName.MLP
    assert controller._pending_gait_transition is False


def test_mlp_ignores_latched_transition_request() -> None:
    controller = make_controller()
    controller.request_gait_transition(1.0)
    controller.set_command(0.0, 0.0)
    controller._robot_fsm._current_name = FSMStateName.MLP

    assert controller._get_fsm_command() == ""


def test_mlp_stays_active_when_command_and_latch_are_cleared() -> None:
    controller = make_controller()
    controller.clear_gait_transition_request()
    controller.set_command(0.0, 0.0)
    controller._robot_fsm._current_name = FSMStateName.MLP

    assert controller._get_fsm_command() == ""


def test_zero_state_holds_zero_pose_until_explicit_stop() -> None:
    controller = make_controller()
    zero_state = controller._robot_fsm._states[FSMStateName.ZERO]
    zero_state._zero_finish = True

    assert zero_state.check_transition(XboxFlag(fsm_state_command="")) == FSMStateName.ZERO


def test_zero_to_stop_holds_default_stand_pose() -> None:
    controller = make_controller()
    controller._robot_data.q_a[:] = np.full(20, 0.25, dtype=np.float64)
    zero_state = controller._robot_fsm._states[FSMStateName.ZERO]
    controller._robot_fsm._current_name = FSMStateName.ZERO
    controller._robot_fsm._current_state = zero_state
    zero_state._zero_finish = True

    controller._robot_fsm.run(XboxFlag(fsm_state_command="gotoStop"))

    stop_state = controller._robot_fsm._states[FSMStateName.STOP]
    assert controller._robot_fsm.current_state == FSMStateName.STOP
    assert np.allclose(stop_state._init_joint_pos, controller.cfg.default_dof_pos_np)


def test_state_mlp_uses_raw_policy_output_when_entry_blend_is_disabled() -> None:
    cfg = PolicyConfig()
    robot_data = RobotData()
    robot_data.q_a[:] = cfg.default_dof_pos_np

    class _OutputTensor:
        def __init__(self) -> None:
            self.data = np.full(20, 2.0, dtype=np.float32)

    class _InferRequest:
        def infer(self, _inputs) -> None:
            return None

        def get_output_tensor(self):
            return _OutputTensor()

    state = StateMLP(robot_data, cfg, _InferRequest(), object())
    state.on_enter()
    state.run(XboxFlag())

    expected = cfg.default_dof_pos_np + (cfg.action_scales * 2.0)
    assert np.allclose(robot_data.q_d, expected, atol=1e-6)


def test_state_mlp_refreshes_inference_only_every_policy_dt() -> None:
    cfg = PolicyConfig()
    robot_data = RobotData()
    robot_data.q_a[:] = cfg.default_dof_pos_np

    class _OutputTensor:
        def __init__(self) -> None:
            self.data = np.zeros(20, dtype=np.float32)

    class _InferRequest:
        def __init__(self) -> None:
            self.calls = 0
            self._output = _OutputTensor()

        def infer(self, _inputs) -> None:
            self.calls += 1
            self._output.data = np.full(20, float(self.calls), dtype=np.float32)

        def get_output_tensor(self):
            return self._output

    infer = _InferRequest()
    state = StateMLP(robot_data, cfg, infer, object())
    state.on_enter()
    state.dt = cfg.control_dt * 3.0

    state.run(XboxFlag())
    first_expected = cfg.default_dof_pos_np + cfg.action_scales
    assert infer.calls == 1
    assert np.allclose(robot_data.q_d, first_expected, atol=1e-6)

    for _ in range(2):
        state.run(XboxFlag())

    assert infer.calls == 1
    assert np.allclose(robot_data.q_d, first_expected, atol=1e-6)

    state.run(XboxFlag())
    second_expected = cfg.default_dof_pos_np + (cfg.action_scales * 2.0)
    assert infer.calls == 2
    assert np.allclose(robot_data.q_d, second_expected, atol=1e-6)


def test_state_mlp_updates_imu_every_control_step_but_builds_obs_on_policy_ticks() -> None:
    cfg = PolicyConfig()
    robot_data = RobotData()
    robot_data.q_a[:] = cfg.default_dof_pos_np
    state = StateMLP(robot_data, cfg, None, None)
    state.on_enter()

    process_calls = 0
    build_calls = 0

    def _process(yaw, pitch, roll, omega):
        nonlocal process_calls
        process_calls += 1
        return np.zeros(3, dtype=np.float64), np.array([0.0, 0.0, -1.0], dtype=np.float64)

    def _build(**kwargs):
        nonlocal build_calls
        build_calls += 1
        return np.zeros(750, dtype=np.float32)

    state._imu_processor = types.SimpleNamespace(process=_process)
    state._obs_builder = types.SimpleNamespace(build=_build, reset=lambda: None)

    for _ in range(9):
        state.run(XboxFlag())

    assert process_calls == 9
    assert build_calls == 2


def test_state_mlp_debug_snapshot_exposes_obs_and_policy_terms() -> None:
    cfg = PolicyConfig()
    robot_data = RobotData()
    robot_data.q_a[:] = cfg.default_dof_pos_np
    robot_data.q_dot_a[:] = 0.0
    robot_data.q_a[4] = -0.25
    robot_data.q_dot_a[4] = 0.42
    robot_data.imu_data[1] = 0.12
    robot_data.imu_data[2] = -0.07
    robot_data.imu_data[3:6] = np.array([0.1, 0.2, 0.3], dtype=np.float64)

    class _OutputTensor:
        def __init__(self) -> None:
            self.data = np.arange(20, dtype=np.float32)

    class _InferRequest:
        def __init__(self) -> None:
            self._output = _OutputTensor()

        def infer(self, _inputs) -> None:
            return None

        def get_output_tensor(self):
            return self._output

    state = StateMLP(robot_data, cfg, _InferRequest(), object())
    state.on_enter()
    state.run(XboxFlag())
    snapshot = state.debug_snapshot()

    assert snapshot["inference_count"] == 1
    assert snapshot["obs"]["joint_pos_terms"]["l_ankle_pitch"] == pytest.approx(0.25)
    assert snapshot["obs"]["joint_vel_terms"]["l_ankle_pitch"] == pytest.approx(0.42)
    assert snapshot["policy"]["raw_output_mujoco_order"]["l_ankle_pitch"] == pytest.approx(16.0)
    assert snapshot["policy"]["post_entry_targets"]["l_ankle_pitch"] == pytest.approx(-0.5 + 16.0 * cfg.action_scales)
    assert snapshot["feedback_joint_pos"]["l_ankle_pitch"] == pytest.approx(-0.25)


def test_controller_update_uses_outer_loop_dt_for_state_timers() -> None:
    controller = make_controller()
    controller.set_joint_feedback(controller.cfg.default_dof_pos_np.tolist(), [0.0] * 20, [0.0] * 20)
    controller.set_imu_feedback(0.0, 0.0, 0.0, [0.0, 0.0, 0.0], [0.0, 0.0, 9.81])
    stop_state = controller._robot_fsm._states[FSMStateName.STOP]

    controller.update(controller.cfg.dt)

    assert controller._robot_fsm.current_state == FSMStateName.STOP
    assert stop_state.timer == pytest.approx(controller.cfg.dt)


def test_controller_update_splits_outer_loop_into_control_substeps() -> None:
    controller = make_controller()
    controller.set_joint_feedback(controller.cfg.default_dof_pos_np.tolist(), [0.0] * 20, [0.0] * 20)
    controller.set_imu_feedback(0.0, 0.0, 0.0, [0.0, 0.0, 0.0], [0.0, 0.0, 9.81])
    step_dts: list[float] = []

    def _run(flag) -> None:
        step_dts.append(float(controller._robot_fsm._current_state.dt))

    controller._robot_fsm.run = _run

    controller.update(0.01)

    assert len(step_dts) == 4
    assert all(dt == pytest.approx(0.0025) for dt in step_dts)


def test_controller_clamps_sim_targets_to_official_joint_ranges() -> None:
    controller = RLPolicyController(PolicyConfig(clamp_joint_targets=True), None)
    controller._robot_data.q_d[:] = np.array([
        9.0, -9.0, 9.0, -9.0, 9.0, -9.0,
        9.0, -9.0, 9.0, -9.0, 9.0, -9.0,
        9.0, -9.0, 9.0, -9.0,
        9.0, -9.0, 9.0, -9.0,
    ], dtype=np.float64)
    controller._robot_fsm.run = lambda flag: None

    targets = controller.update(controller.cfg.dt)

    assert targets["l_ankle_roll"] == pytest.approx(controller.cfg.joint_pos_lower[5])
    assert targets["l_ankle_pitch"] == pytest.approx(controller.cfg.joint_pos_upper[4])
    assert targets["r_shoulder_roll"] == pytest.approx(controller.cfg.joint_pos_lower[17])
    assert targets["l_shoulder_roll"] == pytest.approx(controller.cfg.joint_pos_lower[13])


def test_controller_can_clamp_only_selected_joint_targets() -> None:
    controller = RLPolicyController(
        PolicyConfig(clamp_joint_target_names=["l_ankle_roll", "r_ankle_roll"]),
        None,
    )
    controller._robot_data.q_d[:] = np.array([
        9.0, -9.0, 9.0, -9.0, 9.0, -9.0,
        9.0, -9.0, 9.0, -9.0, 9.0, -9.0,
        9.0, -9.0, 9.0, -9.0,
        9.0, -9.0, 9.0, -9.0,
    ], dtype=np.float64)
    controller._robot_fsm.run = lambda flag: None

    targets = controller.update(controller.cfg.dt)

    assert targets["l_ankle_roll"] == pytest.approx(controller.cfg.joint_pos_lower[5])
    assert targets["r_ankle_roll"] == pytest.approx(controller.cfg.joint_pos_lower[11])
    assert targets["l_ankle_pitch"] == pytest.approx(9.0)
    assert targets["r_shoulder_roll"] == pytest.approx(-9.0)


def test_controller_can_clamp_only_selected_joint_upper_bounds() -> None:
    controller = RLPolicyController(
        PolicyConfig(
            clamp_joint_target_upper_only_names=["l_ankle_pitch", "r_ankle_pitch"],
        ),
        None,
    )
    controller._robot_data.q_d[:] = np.array([
        0.0, 0.0, 0.0, 0.0, 2.0, 0.0,
        0.0, 0.0, 0.0, 0.0, -2.0, 0.0,
        0.5, -0.5, 0.5, -0.5,
        0.5, -0.5, 0.5, -0.5,
    ], dtype=np.float64)
    controller._robot_fsm.run = lambda flag: None

    targets = controller.update(controller.cfg.dt)

    assert targets["l_ankle_pitch"] == pytest.approx(controller.cfg.joint_pos_upper[4])
    assert targets["r_ankle_pitch"] == pytest.approx(-2.0)
    assert targets["l_shoulder_pitch"] == pytest.approx(0.5)


def test_controller_upper_only_clamp_can_wait_for_mlp_delay_and_margin() -> None:
    controller = RLPolicyController(
        PolicyConfig(
            clamp_joint_target_upper_only_names=["l_ankle_pitch", "r_ankle_pitch"],
            clamp_joint_target_upper_only_margin_rad=0.4,
            clamp_joint_target_upper_only_delay_s=2.5,
        ),
        None,
    )
    controller._robot_fsm._current_name = FSMStateName.MLP
    controller._robot_fsm._current_state = controller._robot_fsm._states[FSMStateName.MLP]
    controller._robot_fsm._current_state.timer = 2.6
    controller._robot_data.q_d[:] = np.array([
        0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.7, 0.0,
        0.5, -0.5, 0.5, -0.5,
        0.5, -0.5, 0.5, -0.5,
    ], dtype=np.float64)
    controller._robot_fsm.run = lambda flag: None

    targets = controller.update(controller.cfg.dt)

    assert targets["l_ankle_pitch"] == pytest.approx(controller.cfg.joint_pos_upper[4])
    assert targets["r_ankle_pitch"] == pytest.approx(0.7)


def test_controller_upper_only_clamp_does_not_apply_before_delay() -> None:
    controller = RLPolicyController(
        PolicyConfig(
            clamp_joint_target_upper_only_names=["l_ankle_pitch"],
            clamp_joint_target_upper_only_margin_rad=0.1,
            clamp_joint_target_upper_only_delay_s=3.0,
        ),
        None,
    )
    controller._robot_fsm._current_name = FSMStateName.MLP
    controller._robot_fsm._current_state = controller._robot_fsm._states[FSMStateName.MLP]
    controller._robot_fsm._current_state.timer = 1.5
    controller._robot_data.q_d[:] = np.array([
        0.0, 0.0, 0.0, 0.0, 2.0, 0.0,
        0.0, 0.0, 0.0, 0.0, -0.2, 0.0,
        0.5, -0.5, 0.5, -0.5,
        0.5, -0.5, 0.5, -0.5,
    ], dtype=np.float64)
    controller._robot_fsm.run = lambda flag: None

    targets = controller.update(controller.cfg.dt)

    assert targets["l_ankle_pitch"] == pytest.approx(2.0)


def test_controller_can_slew_only_selected_joint_targets() -> None:
    controller = RLPolicyController(
        PolicyConfig(
            slew_joint_target_names=["l_ankle_pitch", "r_ankle_pitch"],
            slew_joint_target_rate_rad_s=1.0,
        ),
        None,
    )
    controller._robot_data.q_d[:] = np.array([
        0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 0.0, -2.0, 0.0,
        0.5, -0.5, 0.5, -0.5,
        0.5, -0.5, 0.5, -0.5,
    ], dtype=np.float64)
    controller._robot_fsm.run = lambda flag: None

    targets = controller.update(0.1)

    assert targets["l_ankle_pitch"] == pytest.approx(-0.4)
    assert targets["r_ankle_pitch"] == pytest.approx(-0.6)
    assert targets["l_shoulder_pitch"] == pytest.approx(0.5)


def test_policy_config_reads_sim_override_fields_from_yaml(tmp_path: Path) -> None:
    cfg_path = tmp_path / "sim.yaml"
    cfg_path.write_text(
        "clamp_joint_targets: true\n"
        "clamp_joint_target_names:\n"
        "  - l_ankle_roll\n"
        "  - r_ankle_roll\n"
        "clamp_joint_target_upper_only_names:\n"
        "  - l_ankle_pitch\n"
        "  - r_ankle_pitch\n"
        "clamp_joint_target_upper_only_margin_rad: 0.4\n"
        "clamp_joint_target_upper_only_delay_s: 2.5\n"
        "slew_joint_target_names:\n"
        "  - l_ankle_pitch\n"
        "  - r_ankle_pitch\n"
        "slew_joint_target_rate_rad_s: 2.5\n"
        "mlp_entry_blend_s: 0.35\n"
        "max_control_substeps: 24\n"
        "freq_ratio: 10\n",
        encoding="utf-8",
    )

    cfg = PolicyConfig.from_yaml(str(cfg_path))

    assert cfg.clamp_joint_targets is True
    assert cfg.clamp_joint_target_names == ["l_ankle_roll", "r_ankle_roll"]
    assert cfg.clamp_joint_target_upper_only_names == ["l_ankle_pitch", "r_ankle_pitch"]
    assert cfg.clamp_joint_target_upper_only_margin_rad == pytest.approx(0.4)
    assert cfg.clamp_joint_target_upper_only_delay_s == pytest.approx(2.5)
    assert cfg.slew_joint_target_names == ["l_ankle_pitch", "r_ankle_pitch"]
    assert cfg.slew_joint_target_rate_rad_s == pytest.approx(2.5)
    assert cfg.mlp_entry_blend_s == pytest.approx(0.35)
    assert cfg.max_control_substeps == 24
    assert cfg.freq_ratio == 10


def test_short_move_request_reaches_mlp_and_stays_there_after_timeout() -> None:
    controller = make_controller()
    stand = controller.cfg.default_dof_pos_np.tolist()
    controller.set_joint_feedback(stand, [0.0] * 20, [0.0] * 20)
    controller.set_imu_feedback(0.0, 0.0, 0.0, [0.0, 0.0, 0.0], [0.0, 0.0, 9.81])
    controller.set_command(0.08, 0.0)
    controller.request_gait_transition(2.5)

    for step in range(140):
        if step == 20:
            controller.set_command(0.0, 0.0)
        controller.update(controller.cfg.dt)

    assert controller._robot_fsm.current_state == FSMStateName.MLP


def test_force_stop_hold_returns_controller_to_nominal_stop_pose() -> None:
    controller = make_controller()
    controller._robot_fsm._current_name = FSMStateName.MLP
    controller._pending_gait_transition = True
    controller._robot_data.q_a[:] = np.full(20, 0.25, dtype=np.float64)

    controller.force_stop_hold()

    stop_state = controller._robot_fsm._states[FSMStateName.STOP]
    assert controller._robot_fsm.current_state == FSMStateName.STOP
    assert controller._pending_gait_transition is False
    assert np.allclose(stop_state._init_joint_pos, controller.cfg.default_dof_pos_np)


def test_mlp_joint_limit_uses_20d_joint_indices_not_legacy_base_offset() -> None:
    cfg = PolicyConfig(joint_pos_limit=1.0)
    robot_data = RobotData()
    state = StateMLP(robot_data, cfg, None, None)

    robot_data.q_a[13] = 1.2
    assert state.check_transition(XboxFlag()) == FSMStateName.MLP

    robot_data.q_a[:] = 0.0
    robot_data.q_a[1] = 1.2
    assert state.check_transition(XboxFlag()) == FSMStateName.STOP


def test_mlp_state_ignores_goto_zero_without_explicit_stop() -> None:
    cfg = PolicyConfig(joint_pos_limit=1.0)
    robot_data = RobotData()
    state = StateMLP(robot_data, cfg, None, None)

    assert state.check_transition(XboxFlag(fsm_state_command="gotoZero")) == FSMStateName.MLP
    assert state.check_transition(XboxFlag(fsm_state_command="gotoStop")) == FSMStateName.STOP
