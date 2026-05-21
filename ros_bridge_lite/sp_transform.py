"""Serial-parallel mechanism transform for ankle joints.

In simulation mode (Isaac Sim), serial and parallel representations are
identical, so all methods are pass-through.

On the real robot, funcSPTrans (aarch64 C++ library) converts between
parallel motor angles and serial joint angles for the ankle mechanism.
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod

import numpy as np
from numpy.typing import NDArray


class SPTransformBase(ABC):
    """Abstract base for serial-parallel ankle joint conversion."""

    @abstractmethod
    def forward(self,
                q_p: NDArray[np.float64],
                qdot_p: NDArray[np.float64],
                tor_p: NDArray[np.float64],
                ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        """Parallel → Serial (feedback path). Returns (q_s, qdot_s, tor_s)."""
        ...

    @abstractmethod
    def inverse(self,
                q_s: NDArray[np.float64],
                qdot_s: NDArray[np.float64],
                tor_s: NDArray[np.float64],
                ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        """Serial → Parallel (command path). Returns (q_p, qdot_p, tor_p)."""
        ...


class SimulationSPTransform(SPTransformBase):
    """Identity pass-through for simulation (Isaac Sim / Windows)."""

    def forward(self,
                q_p: NDArray[np.float64],
                qdot_p: NDArray[np.float64],
                tor_p: NDArray[np.float64],
                ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        return q_p.copy(), qdot_p.copy(), tor_p.copy()

    def inverse(self,
                q_s: NDArray[np.float64],
                qdot_s: NDArray[np.float64],
                tor_s: NDArray[np.float64],
                ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        return q_s.copy(), qdot_s.copy(), tor_s.copy()


class CTypesSPTransform(SPTransformBase):
    """ctypes wrapper around libfuncSPTrans.so (aarch64 Linux only).

    Wraps the C++ funcSPTrans class for ankle joint serial-parallel conversion.
    """

    def __init__(self, lib_path: str) -> None:
        import ctypes

        self._lib = ctypes.cdll.LoadLibrary(lib_path)

        # Constructor / destructor
        self._lib.funcSPTrans_new.restype = ctypes.c_void_p
        self._lib.funcSPTrans_new.argtypes = []
        self._lib.funcSPTrans_delete.argtypes = [ctypes.c_void_p]

        # Forward kinematics (parallel → serial)
        self._lib.setPEst.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_double),  # qPEst (4 elements)
            ctypes.POINTER(ctypes.c_double),  # qDotPEst (4 elements)
            ctypes.POINTER(ctypes.c_double),  # qTorPEst (4 elements)
        ]
        self._lib.setPEst.restype = ctypes.c_bool

        self._lib.calcFK.argtypes = [ctypes.c_void_p]
        self._lib.calcFK.restype = ctypes.c_bool

        self._lib.getSState.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_double),  # qSEst out
            ctypes.POINTER(ctypes.c_double),  # qDotSEst out
            ctypes.POINTER(ctypes.c_double),  # torSEst out
        ]
        self._lib.getSState.restype = ctypes.c_bool

        # Inverse kinematics (serial → parallel)
        self._lib.setSDes.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_double),  # qSRef (4 elements)
            ctypes.POINTER(ctypes.c_double),  # qDotSRef (4 elements)
            ctypes.POINTER(ctypes.c_double),  # torSDes (4 elements)
        ]
        self._lib.setSDes.restype = ctypes.c_bool

        self._lib.calcJointPosRef.argtypes = [ctypes.c_void_p]
        self._lib.calcJointPosRef.restype = ctypes.c_bool

        self._lib.calcJointTorDes.argtypes = [ctypes.c_void_p]
        self._lib.calcJointTorDes.restype = ctypes.c_bool

        self._lib.getPDes.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_double),  # qPDes out
            ctypes.POINTER(ctypes.c_double),  # qDotPDes out
            ctypes.POINTER(ctypes.c_double),  # torPDes out
        ]
        self._lib.getPDes.restype = ctypes.c_bool

        # Create instance
        self._obj = self._lib.funcSPTrans_new()


def _can_load_ctypes_sp_transform(lib_path: str) -> tuple[bool, str]:
    import ctypes

    try:
        lib = ctypes.cdll.LoadLibrary(lib_path)
    except Exception as exc:
        return False, f"load_failed:{exc}"

    required_symbols = (
        "funcSPTrans_new",
        "funcSPTrans_delete",
        "setPEst",
        "calcFK",
        "getSState",
        "setSDes",
        "calcJointPosRef",
        "calcJointTorDes",
        "getPDes",
    )
    for symbol in required_symbols:
        try:
            getattr(lib, symbol)
        except Exception as exc:
            return False, f"missing_symbol:{symbol}:{exc}"
    return True, ""

    def _to_ptr(self, arr: NDArray[np.float64]):
        import ctypes
        return (ctypes.c_double * len(arr))(*arr.tolist())

    def _from_ptr(self, n: int = 4):
        import ctypes
        return (ctypes.c_double * n)()

    def forward(self,
                q_p: NDArray[np.float64],
                qdot_p: NDArray[np.float64],
                tor_p: NDArray[np.float64],
                ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        import ctypes

        p_q = self._to_ptr(q_p)
        p_qd = self._to_ptr(qdot_p)
        p_tor = self._to_ptr(tor_p)

        self._lib.setPEst(self._obj, p_q, p_qd, p_tor)
        self._lib.calcFK(self._obj)

        out_q = self._from_ptr()
        out_qd = self._from_ptr()
        out_tor = self._from_ptr()
        self._lib.getSState(self._obj, out_q, out_qd, out_tor)

        return (
            np.array(out_q, dtype=np.float64),
            np.array(out_qd, dtype=np.float64),
            np.array(out_tor, dtype=np.float64),
        )

    def inverse(self,
                q_s: NDArray[np.float64],
                qdot_s: NDArray[np.float64],
                tor_s: NDArray[np.float64],
                ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        import ctypes

        p_q = self._to_ptr(q_s)
        p_qd = self._to_ptr(qdot_s)
        p_tor = self._to_ptr(tor_s)

        self._lib.setSDes(self._obj, p_q, p_qd, p_tor)
        self._lib.calcJointPosRef(self._obj)
        self._lib.calcJointTorDes(self._obj)

        out_q = self._from_ptr()
        out_qd = self._from_ptr()
        out_tor = self._from_ptr()
        self._lib.getPDes(self._obj, out_q, out_qd, out_tor)

        return (
            np.array(out_q, dtype=np.float64),
            np.array(out_qd, dtype=np.float64),
            np.array(out_tor, dtype=np.float64),
        )


def create_sp_transform(
    simulation: bool,
    lib_path: str = "",
    *,
    allow_simulation_transform: bool = False,
) -> SPTransformBase:
    """Factory: return simulation stub or ctypes wrapper based on platform.

    When ``allow_simulation_transform`` is enabled we try to reuse the official
    serial/parallel ankle library even in simulation, as long as the current
    host can actually load the shared object.
    """
    if not simulation:
        if not lib_path:
            raise ValueError("lib_path required for CTypesSPTransform when simulation=False")
        return CTypesSPTransform(lib_path)

    if allow_simulation_transform:
        if not lib_path:
            raise ValueError("lib_path required when enable_sim_sp_transform=True")
        ok, reason = _can_load_ctypes_sp_transform(lib_path)
        if ok:
            return CTypesSPTransform(lib_path)
        print(
            "[SPTransform] Falling back to SimulationSPTransform in simulation mode "
            f"because official SP library is incompatible: {reason}"
        )

    return SimulationSPTransform()
