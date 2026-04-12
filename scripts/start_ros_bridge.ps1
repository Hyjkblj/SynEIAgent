param(
  [string]$Host = "0.0.0.0",
  [int]$Port = 8080,
  [string]$CmdVelTopic = "/cmd_vel",
  [string]$NodeName = "gateway_lite_bridge",
  [string]$SetMotionService = "/set_motion_number"
)

$ErrorActionPreference = "Stop"

python -m ros_bridge_lite.main --host $Host --port $Port --cmd-vel-topic $CmdVelTopic --node-name $NodeName --set-motion-service $SetMotionService
