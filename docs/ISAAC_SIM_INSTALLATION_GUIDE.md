# Isaac Sim 本地安装指南

本文档说明如何在本地安装 NVIDIA Isaac Sim 仿真环境。

## 系统要求

### 硬件要求

| 组件 | 最低要求 | 推荐配置 |
|------|----------|----------|
| GPU | RTX 2060 (8GB) | RTX 3080+ (12GB+) |
| CPU | Intel i5 / AMD Ryzen 5 | Intel i7 / AMD Ryzen 7 |
| RAM | 16GB | 32GB |
| 存储 | 50GB SSD | 100GB NVMe SSD |
| 操作系统 | Windows 10/11, Ubuntu 20.04/22.04 | Ubuntu 22.04 |

### GPU 驱动要求

```bash
# 检查 NVIDIA 驱动版本（需要 525+）
nvidia-smi
```

## 安装方式

### 方式一：通过 Omniverse Launcher 安装（推荐）

#### Windows

1. **下载 Omniverse Launcher**
   - 访问：https://www.nvidia.com/en-us/omniverse/download/
   - 选择 Windows 版本下载

2. **安装 Omniverse Launcher**
   - 运行下载的安装程序
   - 按提示完成安装

3. **安装 Isaac Sim**
   - 打开 Omniverse Launcher
   - 登录 NVIDIA 账号（免费注册）
   - 在 "Exchange" 标签页找到 "Isaac Sim"
   - 点击 "Install"
   - 选择安装路径（建议 SSD，至少 50GB 空间）
   - 等待下载和安装（约 30-60 分钟）

4. **验证安装**
   - 在 Launcher 中点击 "Launch" 启动 Isaac Sim
   - 首次启动需要较长时间

#### Linux (Ubuntu)

```bash
# 1. 下载 Omniverse Launcher
wget https://install.omniverse.nvidia.com/installers/omniverse-launcher-linux.AppImage

# 2. 添加执行权限
chmod +x omniverse-launcher-linux.AppImage

# 3. 运行 Launcher
./omniverse-launcher-linux.AppImage

# 4. 在 Launcher 中安装 Isaac Sim
# 步骤同 Windows
```

### 方式二：离线安装包

如果网络较慢，可以下载离线安装包：

1. 访问 NVIDIA 官方下载页面
2. 下载 Isaac Sim 完整安装包（约 15-20GB）
3. 解压到目标目录
4. 运行启动脚本

## 安装后配置

### 1. 配置环境变量

#### Windows

```powershell
# 添加到系统环境变量
ISAAC_SIM_PATH=C:\Users\<用户名>\AppData\Local\ov\pkg\isaac-sim-*
```

#### Linux

```bash
# 添加到 ~/.bashrc
export ISAAC_SIM_PATH=~/.local/share/ov/pkg/isaac-sim-*
export PATH=$ISAAC_SIM_PATH:$PATH
```

### 2. 安装 Python 依赖

Isaac Sim 自带 Python 环境，需要安装额外依赖：

```bash
# Windows
%ISAAC_SIM_PATH%\python.bat -m pip install httpx pillow numpy

# Linux
$ISAAC_SIM_PATH/python.sh -m pip install httpx pillow numpy
```

### 3. 验证 ROS2 集成

```bash
# 检查 ROS2 环境
source /opt/ros/humble/setup.bash

# 测试 Isaac Sim Python 环境
%ISAAC_SIM_PATH%\python.bat -c "import rclpy; print('ROS2 OK')"
```

## 项目配置

### 1. 更新 URDF 路径

项目已获取天工机器人 URDF，位于：
```
TGrobot4s/lite_urdf_publish/x_humanoid_0430_newfeet_newbody_publish/urdf/humanoid_publish.urdf
```

### 2. 更新启动脚本

修改 `import_tienkung_urdf.py` 中的默认路径：

```python
def get_default_urdf_path(version="lite"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    
    # 更新为新路径
    return os.path.join(
        repo_root, 
        "lite_urdf_publish", 
        "x_humanoid_0430_newfeet_newbody_publish", 
        "urdf", 
        "humanoid_publish.urdf"
    )
```

## 启动仿真

### 方式一：一键启动

```bash
# Windows
%ISAAC_SIM_PATH%\python.bat TGrobot4s\isaac_sim\simulation_launcher.py --urdf TGrobot4s\lite_urdf_publish\x_humanoid_0430_newfeet_newbody_publish\urdf\humanoid_publish.urdf

# Linux
$ISAAC_SIM_PATH/python.sh TGrobot4s/isaac_sim/simulation_launcher.py --urdf TGrobot4s/lite_urdf_publish/x_humanoid_0430_newfeet_newbody_publish/urdf/humanoid_publish.urdf
```

### 方式二：在 Isaac Sim GUI 中运行

1. 启动 Isaac Sim
2. 打开 Script Editor (Window -> Script Editor)
3. 加载 `simulation_launcher.py`
4. 点击 Run

## 常见问题

### 问题 1：启动失败 - GPU 内存不足

**解决方案：**
- 降低渲染分辨率
- 使用 `--headless` 模式
- 关闭其他 GPU 密集型应用

### 问题 2：URDF 导入失败

**解决方案：**
- 检查 URDF 文件路径是否正确
- 确保 meshes 文件夹与 urdf 文件在同一目录
- 检查 STL 文件是否完整

### 问题 3：ROS2 节点无法创建

**解决方案：**
```bash
# 确保 ROS2 环境已加载
source /opt/ros/humble/setup.bash

# 检查 RMW 实现
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

### 问题 4：Python 包找不到

**解决方案：**
```bash
# 使用 Isaac Sim 的 Python 安装
%ISAAC_SIM_PATH%\python.bat -m pip install <package>
```

## 性能优化建议

### 1. 降低渲染质量

在 `simulation_launcher.py` 中：
```python
app_config = {
    "headless": True,  # 无头模式
    "width": 640,      # 降低分辨率
    "height": 480,
}
```

### 2. 降低物理精度

```python
config = SimulationConfig(
    physics_dt=1.0 / 30.0,  # 降低物理频率
    render_dt=1.0 / 30.0,   # 降低渲染频率
)
```

### 3. 禁用不必要的功能

```bash
# 禁用视频流
python simulation_launcher.py --no-video

# 禁用关节状态发布
# 在配置中设置 joint_states_publish_hz=0
```

## 下一步

安装完成后：

1. **验证 URDF 导入**
   ```bash
   python import_tienkung_urdf.py --urdf <path-to-urdf>
   ```

2. **启动完整仿真**
   ```bash
   python simulation_launcher.py --urdf <path-to-urdf>
   ```

3. **测试移动端控制**
   - 启动 Gateway Lite
   - 启动 ROS Bridge Lite
   - 移动端连接测试

## 参考链接

- [Isaac Sim 官方文档](https://docs.omniverse.nvidia.com/isaacsim/latest/)
- [Isaac Sim ROS2 桥接](https://docs.omniverse.nvidia.com/isaacsim/latest/features/ros2_tutorial.html)
- [Omniverse Launcher 下载](https://www.nvidia.com/en-us/omniverse/download/)
