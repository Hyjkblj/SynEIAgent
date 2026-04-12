from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SafetyGuard:
    max_linear: float
    max_angular: float
    voice_max_duration_ms: int

    def clamp_axis(self, v: float) -> float:
        return max(-1.0, min(1.0, float(v)))

    def clamp_linear(self, linear: float) -> float:
        linear = float(linear)
        return max(-self.max_linear, min(self.max_linear, linear))

    def clamp_angular(self, angular: float) -> float:
        angular = float(angular)
        return max(-self.max_angular, min(self.max_angular, angular))

    def joystick_to_velocity(self, x: float, y: float) -> tuple[float, float]:
        # joystick: x for angular, y for linear
        nx = self.clamp_axis(x)
        ny = self.clamp_axis(y)
        linear = self.clamp_linear(ny * self.max_linear)
        angular = self.clamp_angular(nx * self.max_angular)
        return linear, angular

    def clamp_voice_duration(self, duration_ms: int | float | None) -> int:
        if duration_ms is None:
            return min(800, self.voice_max_duration_ms)
        d = int(duration_ms)
        d = max(100, d)
        return min(d, self.voice_max_duration_ms)
