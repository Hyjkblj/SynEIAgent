$env:ISAAC_STARTUP_BASE_POSITION = "0,0,0.77255"
$env:ISAAC_STARTUP_ORIENTATION_WXYZ = "1,0,0,0"
$env:ISAAC_STARTUP_POSE_HOLD_S = "3.0"
$env:ISAAC_STARTUP_NOMINAL_HOLD_TOLERANCE_RAD = "0.08"

# The default validation baseline now aligns both joint gains and
# effort/velocity limits with the checked-in official Lite actuator profile.
# Use empty-string env overrides to A/B back to policy_config gains or to
# disable the explicit limit profile when needed.
$ActuatorGainProfile = if (Test-Path Env:ISAAC_ACTUATOR_GAIN_PROFILE) { $env:ISAAC_ACTUATOR_GAIN_PROFILE } else { "official_lite" }
$ActuatorLimitProfile = if (Test-Path Env:ISAAC_ACTUATOR_LIMIT_PROFILE) { $env:ISAAC_ACTUATOR_LIMIT_PROFILE } else { "official_lite" }
$JointTargetSignOverrides = if (Test-Path Env:ISAAC_JOINT_TARGET_SIGN_OVERRIDES) { $env:ISAAC_JOINT_TARGET_SIGN_OVERRIDES } else { "" }
$JointFeedbackSignOverrides = if (Test-Path Env:ISAAC_JOINT_FEEDBACK_SIGN_OVERRIDES) { $env:ISAAC_JOINT_FEEDBACK_SIGN_OVERRIDES } else { "" }

Write-Host "[Isaac] actuator_gain_profile=$ActuatorGainProfile"
Write-Host "[Isaac] actuator_limit_profile=$ActuatorLimitProfile"
Write-Host "[Isaac] joint_target_sign_overrides=$($JointTargetSignOverrides -replace '^$','<none>')"
Write-Host "[Isaac] joint_feedback_sign_overrides=$($JointFeedbackSignOverrides -replace '^$','<none>')"

$args = @(
    "D:\Develop\Project\SynEIAgent\TGrobot4s\isaac_sim\ros2_control_bridge.py",
    "--headless",
    "--physics-dt", "0.005",
    "--joint-stiffness", "700",
    "--joint-damping", "20",
    "--ground-static-friction", "2.0",
    "--ground-dynamic-friction", "1.8",
    "--ground-restitution", "0.0",
    "--solver-position-iterations", "32",
    "--solver-velocity-iterations", "8",
    "--official-lite-usd",
    "--robot-prim", "/World/humanoid",
    "--policy-config", "D:\Develop\Project\SynEIAgent\DeployTienkug\Deploy_Tienkung\rl_control_new\config\tg22_http_sim.yaml",
    "--actuator-gain-profile", $ActuatorGainProfile,
    "--actuator-limit-profile", $ActuatorLimitProfile
)

if ($JointTargetSignOverrides) {
    $args += @("--joint-target-sign-overrides", $JointTargetSignOverrides)
}
if ($JointFeedbackSignOverrides) {
    $args += @("--joint-feedback-sign-overrides", $JointFeedbackSignOverrides)
}

& "D:\isaacsim5.1\python.bat" @args
