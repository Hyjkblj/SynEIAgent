#!/usr/bin/env python3
import yourdfpy
import numpy as np
import math

urdf_path = 'D:/Develop/Project/SynEIAgent/third_party/TienKung-Lab/legged_lab/assets/tienkung2_lite/urdf/tienkung2_lite.urdf'
robot = yourdfpy.URDF.load(urdf_path, build_scene_graph=True)

print('Actuated joints:', robot.actuated_joint_names)
print('Num dofs:', robot.num_dofs)

# Test update_cfg
cfg = robot.zero_cfg.copy()
print('\nBefore update - cfg[16] (shoulder_pitch_r):', math.degrees(cfg[16]))

# Set shoulder_pitch_r_joint to -45 degrees
cfg[16] = math.radians(-45)
robot.update_cfg(cfg)
print('After update - cfg[16]:', math.degrees(cfg[16]))

# Check scene graph transforms
flattened = robot.scene.graph.to_flattened()
print('\nScene graph nodes (first 10):')
for i, (key, val) in enumerate(flattened.items()):
    if i >= 10:
        break
    print(f'  {key}')

# Check if shoulder link moved
for key in flattened:
    if 'shoulder' in key.lower() and 'r' in key.lower():
        print(f'\n{key} transform:')
        print(flattened[key])
        break
