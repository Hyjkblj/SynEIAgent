"""Meshcat 实时可视化 — 从 Isaac Sim HTTP 拉取关节数据，在浏览器中显示 URDF 机器人。

用法：
  conda activate SE3nv
  python scripts/meshcat_viewer.py

浏览器会自动打开 meshcat 页面。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import meshcat
import meshcat.geometry as g
import meshcat.transformations as tf
import numpy as np
import requests
import xml.etree.ElementTree as ET

ISAAC_SIM_URL = "http://localhost:9200"
URDF_PATH = r"D:\Develop\Project\SynEIAgent\TGrobot4s\lite_urdf_publish\x_humanoid_0430_newfeet_newbody_publish\urdf\humanoid_publish.urdf"


def parse_urdf(path: str) -> dict:
    """Parse URDF to extract joint and link info."""
    tree = ET.parse(path)
    root = tree.getroot()

    urdf_dir = Path(path).parent

    joints = {}
    for joint in root.findall("joint"):
        name = joint.get("name")
        jtype = joint.get("type", "fixed")
        parent = joint.find("parent")
        child = joint.find("child")
        origin = joint.find("origin")
        axis = joint.find("axis")

        xyz = [0, 0, 0]
        rpy = [0, 0, 0]
        if origin is not None:
            if origin.get("xyz"):
                xyz = [float(x) for x in origin.get("xyz").split()]
            if origin.get("rpy"):
                rpy = [float(x) for x in origin.get("rpy").split()]

        axis_vec = [0, 0, 1]
        if axis is not None and axis.get("xyz"):
            axis_vec = [float(x) for x in axis.get("xyz").split()]

        joints[name] = {
            "type": jtype,
            "parent": parent.get("link") if parent is not None else "",
            "child": child.get("link") if child is not None else "",
            "xyz": xyz,
            "rpy": rpy,
            "axis": axis_vec,
        }

    links = {}
    for link in root.findall("link"):
        name = link.get("name")
        visual = link.find("visual")
        geometry = None
        origin_xyz = [0, 0, 0]
        origin_rpy = [0, 0, 0]

        if visual is not None:
            # visual origin offset
            vorigin = visual.find("origin")
            if vorigin is not None:
                if vorigin.get("xyz"):
                    origin_xyz = [float(x) for x in vorigin.get("xyz").split()]
                if vorigin.get("rpy"):
                    origin_rpy = [float(x) for x in vorigin.get("rpy").split()]

            geom = visual.find("geometry")
            if geom is not None:
                box = geom.find("box")
                cyl = geom.find("cylinder")
                sphere = geom.find("sphere")
                mesh = geom.find("mesh")
                if box is not None:
                    size = [float(x) for x in box.get("size", "0.1 0.1 0.1").split()]
                    geometry = ("box", size)
                elif cyl is not None:
                    radius = float(cyl.get("radius", 0.05))
                    length = float(cyl.get("length", 0.1))
                    geometry = ("cylinder", radius, length)
                elif sphere is not None:
                    radius = float(sphere.get("radius", 0.05))
                    geometry = ("sphere", radius)
                elif mesh is not None:
                    mesh_file = mesh.get("filename", "")
                    # Resolve relative path against URDF directory
                    mesh_path = (urdf_dir / mesh_file).resolve()
                    geometry = ("mesh", str(mesh_path))

        links[name] = {"geometry": geometry, "origin_xyz": origin_xyz, "origin_rpy": origin_rpy}

    return {"joints": joints, "links": links}


def build_transform(xyz, rpy):
    """Build 4x4 transform from xyz and rpy (roll-pitch-yaw, ZYX convention)."""
    T = np.eye(4)
    T[:3, 3] = xyz
    cr, sr = np.cos(rpy[0]), np.sin(rpy[0])
    cp, sp = np.cos(rpy[1]), np.sin(rpy[1])
    cy, sy = np.cos(rpy[2]), np.sin(rpy[2])
    R = np.array([
        [cy*cp, cy*sp*sr - sy*cr, cy*sp*cr + sy*sr],
        [sy*cp, sy*sp*sr + cy*cr, sy*sp*cr - cy*sr],
        [-sp,   cp*sr,            cp*cr],
    ])
    T[:3, :3] = R
    return T


def create_geometry(geom_info):
    """Create meshcat geometry from URDF geometry info, including STL meshes."""
    if geom_info is None:
        return g.Box([0.05, 0.05, 0.05])
    kind = geom_info[0]
    if kind == "box":
        return g.Box(geom_info[1])
    elif kind == "cylinder":
        return g.Cylinder(geom_info[2], radius=geom_info[1])
    elif kind == "sphere":
        return g.Sphere(geom_info[1])
    elif kind == "mesh":
        mesh_path = geom_info[1]
        try:
            return g.StlMeshGeometry.from_file(mesh_path)
        except Exception as e:
            print(f"[Viewer] WARN: Failed to load mesh {mesh_path}: {e}")
            return g.Box([0.1, 0.1, 0.1])
    return g.Box([0.05, 0.05, 0.05])


def fetch_joint_states(url: str) -> dict[str, float] | None:
    try:
        resp = requests.get(f"{url}/joint_states", timeout=0.1)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return dict(zip(data["name"], data["position"]))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Meshcat URDF viewer with Isaac Sim feedback")
    parser.add_argument("--urdf", default=URDF_PATH, help="URDF file path")
    parser.add_argument("--url", default=ISAAC_SIM_URL, help="Isaac Sim HTTP URL")
    parser.add_argument("--hz", type=float, default=20, help="Refresh rate")
    parser.add_argument("--static", action="store_true", help="Static mode (no polling, just show URDF)")
    args = parser.parse_args()

    print(f"[Viewer] Parsing URDF: {args.urdf}")
    urdf = parse_urdf(args.urdf)
    joints = urdf["joints"]
    links = urdf["links"]
    print(f"[Viewer] {len(joints)} joints, {len(links)} links")

    # Create meshcat visualizer
    vis = meshcat.Visualizer()
    vis.open()
    print(f"[Viewer] Meshcat URL: {vis.url()}")

    # Build parent -> children index
    children_of: dict[str, list[str]] = {}
    joint_by_child: dict[str, str] = {}
    for jname, jinfo in joints.items():
        parent = jinfo["parent"]
        child = jinfo["child"]
        children_of.setdefault(parent, []).append(child)
        joint_by_child[child] = jname

    # Find root link (has no parent joint)
    all_links = set(links.keys())
    child_links = set(joint_by_child.keys())
    root_links = all_links - child_links
    root_link = root_links.pop() if root_links else "base_link"
    print(f"[Viewer] Root link: {root_link}")

    # Render each link's geometry under a hierarchical path: /robot/<link_name>
    rendered_links: set[str] = set()
    colors = [
        [0.6, 0.6, 0.7, 1],  # steel blue-grey
        [0.8, 0.3, 0.2, 1],  # red
        [0.2, 0.6, 0.8, 1],  # blue
        [0.3, 0.7, 0.3, 1],  # green
        [0.8, 0.7, 0.2, 1],  # yellow
        [0.7, 0.3, 0.7, 1],  # magenta
    ]

    def render_link_tree(link_name: str, color_idx: int = 0):
        """Recursively render link and its children under /robot/<path>."""
        link_info = links.get(link_name)
        if link_info and link_info["geometry"]:
            geom = create_geometry(link_info["geometry"])
            color = colors[color_idx % len(colors)]
            # Apply visual origin offset
            origin_T = build_transform(link_info["origin_xyz"], link_info["origin_rpy"])
            vis["robot"][link_name].set_object(geom, g.MeshLambertMaterial(color=color))
            if not np.allclose(origin_T, np.eye(4)):
                vis["robot"][link_name].set_transform(origin_T)
            rendered_links.add(link_name)

        for child_name in children_of.get(link_name, []):
            render_link_tree(child_name, color_idx + 1)

    render_link_tree(root_link)
    print(f"[Viewer] Rendered {len(rendered_links)} links")

    # Compute world transforms for each link (BFS from root)
    def compute_link_transforms(joint_positions: dict[str, float]) -> dict[str, np.ndarray]:
        transforms = {root_link: np.eye(4)}
        visited = {root_link}
        queue = [root_link]

        while queue:
            parent_link = queue.pop(0)
            parent_T = transforms[parent_link]

            for child_name in children_of.get(parent_link, []):
                if child_name in visited:
                    continue

                jname = joint_by_child.get(child_name)
                if jname is None:
                    transforms[child_name] = parent_T
                    visited.add(child_name)
                    queue.append(child_name)
                    continue

                jinfo = joints[jname]
                T_joint = build_transform(jinfo["xyz"], jinfo["rpy"])

                T_rot = np.eye(4)
                if jinfo["type"] in ("revolute", "continuous") and jname in joint_positions:
                    angle = joint_positions[jname]
                    axis = np.array(jinfo["axis"])
                    axis = axis / (np.linalg.norm(axis) + 1e-10)
                    K = np.array([
                        [0, -axis[2], axis[1]],
                        [axis[2], 0, -axis[0]],
                        [-axis[1], axis[0], 0],
                    ])
                    R = np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)
                    T_rot[:3, :3] = R

                child_T = parent_T @ T_joint @ T_rot

                # Include visual origin offset
                link_info = links.get(child_name)
                if link_info:
                    T_vis = build_transform(link_info["origin_xyz"], link_info["origin_rpy"])
                    child_T = child_T @ T_vis

                transforms[child_name] = child_T
                visited.add(child_name)
                queue.append(child_name)

        return transforms

    if args.static:
        print("[Viewer] Static mode — showing default pose. Press Ctrl+C to exit.")
        # Set zero-pose transforms
        zero_pos = {jname: 0.0 for jname in joints if joints[jname]["type"] in ("revolute", "continuous")}
        transforms = compute_link_transforms(zero_pos)
        for link_name, T in transforms.items():
            if link_name in rendered_links:
                vis["robot"][link_name].set_transform(T)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Viewer] Stopped")
        return 0

    # Live polling mode
    print(f"[Viewer] Polling {args.url}/joint_states at {args.hz} Hz")
    print(f"[Viewer] Open the URL above in your browser")

    dt = 1.0 / args.hz
    frame_count = 0
    last_print = time.time()

    try:
        while True:
            states = fetch_joint_states(args.url)
            if states:
                transforms = compute_link_transforms(states)
                for link_name, T in transforms.items():
                    if link_name in rendered_links:
                        vis["robot"][link_name].set_transform(T)

            time.sleep(dt)

            frame_count += 1
            now = time.time()
            if now - last_print >= 2.0:
                actual_hz = frame_count / (now - last_print)
                print(f"[Viewer] {actual_hz:.0f} Hz, {len(states or {})} joints")
                frame_count = 0
                last_print = now

    except KeyboardInterrupt:
        print("\n[Viewer] Stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
