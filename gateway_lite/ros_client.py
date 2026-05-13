from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


class RosBridgeClient(Protocol):
    async def move(self, linear: float, angular: float) -> tuple[bool, str]: ...

    async def stop(self) -> tuple[bool, str]: ...

    async def motion(self, motion_number: int, active: bool = True) -> tuple[bool, str]: ...

    async def fsm_cmd(self, cmd: str) -> tuple[bool, str]: ...


@dataclass(slots=True)
class HttpRosBridgeClient:
    base_url: str
    timeout_s: float = 0.8

    async def move(self, linear: float, angular: float) -> tuple[bool, str]:
        v_linear = float(linear)
        v_angular = float(angular)
        # Keep both key styles for compatibility with old/new ros_bridge_lite.
        payload = {
            "linear": v_linear,
            "angular": v_angular,
            "linear_x": v_linear,
            "angular_z": v_angular,
        }
        return await self._post("/move", payload)

    async def stop(self) -> tuple[bool, str]:
        payload = {"linear": 0.0, "angular": 0.0, "linear_x": 0.0, "angular_z": 0.0}
        return await self._post("/move", payload)

    async def motion(self, motion_number: int, active: bool = True) -> tuple[bool, str]:
        payload = {"number": int(motion_number), "active": bool(active)}
        return await self._post("/motion", payload)

    async def fsm_cmd(self, cmd: str) -> tuple[bool, str]:
        payload = {"cmd": str(cmd).strip()}
        return await self._post("/fsm_cmd", payload)

    async def _post(self, path: str, body: dict) -> tuple[bool, str]:
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            # Keep loopback bridge calls off any ambient proxy or env-based routing.
            async with httpx.AsyncClient(timeout=self.timeout_s, trust_env=False) as client:
                resp = await client.post(url, json=body)
            if resp.status_code >= 400:
                return False, f"http_{resp.status_code}"
            try:
                payload = resp.json()
            except Exception:
                payload = None
            if isinstance(payload, dict) and payload.get("success") is False:
                detail = payload.get("detail")
                if isinstance(detail, str) and detail.strip():
                    return False, detail.strip()
                return False, "bridge_rejected"
            return True, "ok"
        except httpx.TimeoutException:
            return False, "timeout"
        except Exception as e:
            return False, str(e)


class MockRosBridgeClient:
    """Local mock for fast bring-up without ROS."""

    async def move(self, linear: float, angular: float) -> tuple[bool, str]:
        print(f"[MOCK] move linear={linear:.3f} angular={angular:.3f}")
        return True, "ok"

    async def stop(self) -> tuple[bool, str]:
        print("[MOCK] stop")
        return True, "ok"

    async def motion(self, motion_number: int, active: bool = True) -> tuple[bool, str]:
        print(f"[MOCK] motion number={motion_number} active={active}")
        return True, "ok"

    async def fsm_cmd(self, cmd: str) -> tuple[bool, str]:
        print(f"[MOCK] fsm_cmd cmd={cmd}")
        return True, "ok"
