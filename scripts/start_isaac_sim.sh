#!/bin/bash
# Isaac Sim 仿真启动脚本 (Linux/Mac)
# 使用方法: ./start_isaac_sim.sh

set -e

# 参数
ISAAC_SIM_PATH="${ISAAC_SIM_PATH:-}"
URDF_PATH="${URDF_PATH:-}"
HEADLESS="${HEADLESS:-false}"
NO_VIDEO="${NO_VIDEO:-false}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8088}"

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# 默认 URDF 路径
if [ -z "$URDF_PATH" ]; then
    URDF_PATH="$REPO_ROOT/TGrobot4s/lite_urdf_publish/x_humanoid_0430_newfeet_newbody_publish/urdf/humanoid_publish.urdf"
fi

# 检查 URDF 文件
if [ ! -f "$URDF_PATH" ]; then
    echo -e "\033[31m[Error] URDF file not found: $URDF_PATH\033[0m"
    exit 1
fi

echo -e "\033[36m========================================"
echo -e "  Isaac Sim Simulation Launcher"
echo -e "========================================\033[0m"
echo ""
echo -e "\033[32mURDF: $URDF_PATH\033[0m"
echo -e "\033[32mGateway: $GATEWAY_URL\033[0m"
echo -e "\033[32mHeadless: $HEADLESS\033[0m"
echo ""

# 查找 Isaac Sim 安装路径
if [ -z "$ISAAC_SIM_PATH" ]; then
    # 常见安装路径
    POSSIBLE_PATHS=(
        "$HOME/.local/share/ov/pkg/isaac-sim-*"
        "/opt/nvidia/isaac-sim-*"
        "$HOME/isaac-sim-*"
    )
    
    for PATTERN in "${POSSIBLE_PATHS[@]}"; do
        FOUND=$(ls -d $PATTERN 2>/dev/null | head -1)
        if [ -n "$FOUND" ]; then
            ISAAC_SIM_PATH="$FOUND"
            break
        fi
    done
fi

if [ -z "$ISAAC_SIM_PATH" ]; then
    echo -e "\033[31m[Error] Isaac Sim not found. Please set ISAAC_SIM_PATH\033[0m"
    echo ""
    echo -e "\033[33mExample:\033[0m"
    echo -e "\033[33m  export ISAAC_SIM_PATH=~/.local/share/ov/pkg/isaac-sim-4.2.0\033[0m"
    echo -e "\033[33m  ./start_isaac_sim.sh\033[0m"
    exit 1
fi

echo -e "\033[32mIsaac Sim: $ISAAC_SIM_PATH\033[0m"
echo ""

# 构建 Python 命令
PYTHON_EXE="$ISAAC_SIM_PATH/python.sh"
LAUNCHER_SCRIPT="$REPO_ROOT/TGrobot4s/isaac_sim/simulation_launcher.py"

# 构建参数
ARGS=(
    "$LAUNCHER_SCRIPT"
    "--urdf" "$URDF_PATH"
    "--gateway-url" "$GATEWAY_URL"
)

if [ "$HEADLESS" = "true" ]; then
    ARGS+=("--headless")
fi

if [ "$NO_VIDEO" = "true" ]; then
    ARGS+=("--no-video")
fi

echo -e "\033[36mStarting simulation...\033[0m"
echo ""

# 启动仿真
"$PYTHON_EXE" "${ARGS[@]}"
