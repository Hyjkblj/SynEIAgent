#!/usr/bin/env python3
import yourdfpy
import math

urdf_path = "D:/Develop/Project/SynEIAgent/third_party/TienKung-Lab/legged_lab/assets/tienkung2_lite/urdf/tienkung2_lite.urdf"
robot = yourdfpy.URDF.load(urdf_path)

print("Type:", type(robot))
print("\nActuated joints:", robot.actuated_joint_names)
print("\nNumber of actuated joints:", len(robot.actuated_joint_names))

# Check joint_map
print("\njoint_map type:", type(robot.joint_map))
if hasattr(robot.joint_map, 'keys'):
    print("joint_map keys:", list(robot.joint_map.keys())[:5])
    # Get a sample joint
    sample_key = list(robot.joint_map.keys())[0]
    sample_joint = robot.joint_map[sample_key]
    print(f"\nSample joint '{sample_key}':")
    print(f"  Type: {type(sample_joint)}")
    print(f"  Dir: {[x for x in dir(sample_joint) if not x.startswith('_')]}")
    if hasattr(sample_joint, 'limit'):
        print(f"  Limit: {sample_joint.limit}")
        if sample_joint.limit:
            print(f"  Lower: {sample_joint.limit.lower}")
            print(f"  Upper: {sample_joint.limit.upper}")
else:
    print("joint_map is not a dict, trying actuated_joints...")
    print("actuated_joints type:", type(robot.actuated_joints))
    if len(robot.actuated_joints) > 0:
        sample = robot.actuated_joints[0]
        print(f"\nSample actuated joint:")
        print(f"  Type: {type(sample)}")
        print(f"  Name: {sample.name if hasattr(sample, 'name') else 'N/A'}")
        print(f"  Limit: {sample.limit if hasattr(sample, 'limit') else 'N/A'}")
