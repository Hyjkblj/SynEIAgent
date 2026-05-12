"""IMU coordinate transforms and low-pass filtering for RL policy.

Port of FSMStateImpl.cpp (lines 189-216) and BasicFunction.cpp.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray


def rot_x(angle: float) -> NDArray[np.float64]:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def rot_y(angle: float) -> NDArray[np.float64]:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def rot_z(angle: float) -> NDArray[np.float64]:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def euler_zyx_to_matrix(yaw: float, pitch: float, roll: float) -> NDArray[np.float64]:
    """ZYX Euler angles to rotation matrix (R = Rz * Ry * Rx)."""
    return rot_z(yaw) @ rot_y(pitch) @ rot_x(roll)


def euler_xyz_to_matrix(roll: float, pitch: float, yaw: float) -> NDArray[np.float64]:
    """XYZ Euler angles to rotation matrix (R = Rx * Ry * Rz)."""
    return rot_x(roll) @ rot_y(pitch) @ rot_z(yaw)


def matrix_to_euler_xyz(r: NDArray[np.float64]) -> tuple[float, float, float]:
    """Rotation matrix to XYZ Euler angles (roll, pitch, yaw)."""
    pitch = math.asin(np.clip(r[0, 2], -1.0, 1.0))
    cp = math.cos(pitch)
    if abs(cp) < 1e-10:
        yaw = 0.0
        roll = math.atan2(-r[1, 2], r[2, 2])
    else:
        sinz = -r[0, 1] / cp
        cosz = r[0, 0] / cp
        yaw = math.atan2(sinz, cosz)
        sinx = -r[1, 2] / cp
        cosx = r[2, 2] / cp
        roll = math.atan2(sinx, cosx)
    return roll, pitch, yaw


class LowPassFilter:
    """2nd order Butterworth low-pass filter (port of BasicFunction.cpp)."""

    def __init__(self, cutoff_hz: float, damping: float, dt: float, n: int = 3) -> None:
        self._sig_in_1 = np.zeros(n, dtype=np.float64)
        self._sig_in_2 = np.zeros(n, dtype=np.float64)
        self._sig_out_1 = np.zeros(n, dtype=np.float64)
        self._sig_out_2 = np.zeros(n, dtype=np.float64)

        freq_rad = 2.0 * math.pi * cutoff_hz
        c = 2.0 / dt
        c2 = c * c
        w2 = freq_rad * freq_rad

        b2 = c2 + 2.0 * damping * freq_rad * c + w2
        b1 = -2.0 * (c2 - w2)
        b0 = c2 - 2.0 * damping * freq_rad * c + w2

        self._a2 = w2 / b2
        self._a1 = 2.0 * w2 / b2
        self._a0 = w2 / b2
        self._b1 = b1 / b2
        self._b0 = b0 / b2

    def filter(self, sig_in: NDArray[np.float64]) -> NDArray[np.float64]:
        sig_out = (
            self._a2 * sig_in
            + self._a1 * self._sig_in_1
            + self._a0 * self._sig_in_2
            - self._b1 * self._sig_out_1
            - self._b0 * self._sig_out_2
        )
        self._sig_in_2 = self._sig_in_1.copy()
        self._sig_in_1 = sig_in.copy()
        self._sig_out_2 = self._sig_out_1.copy()
        self._sig_out_1 = sig_out.copy()
        return sig_out


class IMUProcessor:
    """Process raw IMU data into RL policy observations."""

    def __init__(self, cutoff_hz: float = 30.0, damping: float = 0.707, dt: float = 0.02) -> None:
        self._omega_filter = LowPassFilter(cutoff_hz, damping, dt, n=3)

    @staticmethod
    def _build_r_xyz_omega(roll: float, pitch: float) -> NDArray[np.float64]:
        r_xyz_omega = np.eye(3, dtype=np.float64)
        r_xyz_omega[1, :] = rot_x(roll)[1, :]
        r_xyz_omega[2, :] = (rot_x(roll) @ rot_y(pitch))[2, :]
        return r_xyz_omega

    def process(
        self,
        yaw: float,
        pitch: float,
        roll: float,
        omega: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Process IMU data using the same math as the C++ SDK."""
        _ = yaw
        ypr = np.array([0.0, pitch, roll], dtype=np.float64)
        ned_r_ypr = euler_zyx_to_matrix(ypr[0], ypr[1], ypr[2])
        rpy = np.array(matrix_to_euler_xyz(ned_r_ypr), dtype=np.float64)

        r_xyz_omega = self._build_r_xyz_omega(rpy[0], rpy[1])
        q_dot = r_xyz_omega.T @ ned_r_ypr @ omega

        rb_w = euler_xyz_to_matrix(rpy[0], rpy[1], rpy[2])
        ang_vel = rb_w.T @ r_xyz_omega @ q_dot
        ang_vel_filtered = self._omega_filter.filter(ang_vel)

        gravity_dir = -rb_w.T[:, 2]
        return ang_vel_filtered, gravity_dir
