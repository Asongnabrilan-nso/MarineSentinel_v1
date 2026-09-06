# SPDX-FileCopyrightText: Copyright (C) 2026 MarineSentinel Project
# SPDX-License-Identifier: MPL-2.0

from collections import deque
import threading
import time

# ── Conversion constants ──────────────────────────────────────────────────────
_ADC_REF_V   = 3.3    # UNO Q MCU ADC reference voltage
_ADC_MAX     = 1023   # 10-bit ADC

# ── Alert thresholds ──────────────────────────────────────────────────────────
TURBIDITY_WARN_NTU  = 100.0   # Moderate — caution
TURBIDITY_ALERT_NTU = 500.0   # High — quality concern
TEMP_HIGH_ALERT_C   = 35.0    # Thermal stress threshold
TEMP_LOW_ALERT_C    = 4.0     # Cold alert (DS18B20 returns -127 on error)
TILT_WARN_DEG       = 45.0    # Listing — caution
TILT_CRITICAL_DEG   = 120.0   # Likely capsized / inverted

# ── Marine debris classes that YOLO-X COCO can detect ────────────────────────
DEBRIS_CLASSES = {
    "bottle", "cup", "bowl", "backpack", "handbag",
    "suitcase", "umbrella", "sports ball", "frisbee",
    "book", "vase", "cell phone",
}


def raw_to_ntu(raw: int) -> float:
    """Convert 10-bit ADC reading to NTU using SEN0189 sensor curve (3.3 V ref).

    SEN0189 at 3.3 V: clean water ≈ 3.0 V → 0 NTU, murky ≈ 0 V → 3000 NTU.
    Quadratic fit from manufacturer datasheet (4.5 V coefficients scaled to 3.3 V).
    """
    voltage = raw * (_ADC_REF_V / _ADC_MAX)
    ntu = max(0.0, -1120.4 * voltage**2 + 5742.3 * voltage - 4352.9)
    return round(ntu, 1)


def turbidity_label(ntu: float) -> str:
    if ntu < TURBIDITY_WARN_NTU:   return "Clear"
    if ntu < TURBIDITY_ALERT_NTU:  return "Moderate"
    return "Turbid"


def temp_label(temp_c: float) -> str:
    if temp_c < -100:              return "Sensor Error"
    if temp_c < TEMP_LOW_ALERT_C:  return "Cold"
    if temp_c > TEMP_HIGH_ALERT_C: return "Hot"
    return "Normal"


def normalize_yaw(yaw_deg: float) -> float:
    """Wrap a gyro-integrated yaw reading into [-180, 180).

    Yaw has no accelerometer-equivalent correction (no magnetometer on the
    MPU6050), so it accumulates indefinitely over a long deployment — this
    just keeps the displayed heading readable, it doesn't fix the drift.
    """
    return ((yaw_deg + 180.0) % 360.0) - 180.0


def orientation_label(roll_deg: float, pitch_deg: float) -> str:
    tilt = max(abs(roll_deg), abs(pitch_deg))
    if tilt >= TILT_CRITICAL_DEG: return "Capsized?"
    if tilt >= TILT_WARN_DEG:     return "Listing"
    return "Upright"


def evaluate_orientation_alerts(roll_deg: float, pitch_deg: float) -> list[str]:
    tilt = max(abs(roll_deg), abs(pitch_deg))
    if tilt >= TILT_CRITICAL_DEG:
        return [f"⚠ Capsule may be capsized: tilt {tilt:.0f}°"]
    if tilt >= TILT_WARN_DEG:
        return [f"⚠ Capsule listing: tilt {tilt:.0f}°"]
    return []


def is_debris(label: str) -> bool:
    return label.lower() in DEBRIS_CLASSES


def summarize_detections(raw: dict) -> dict[str, float]:
    """Reduce the brick's raw {label: [box, ...]} output to {label: best confidence}.

    Each box is a dict with a "confidence" key; a label with an empty box list
    (no instance found this frame) is dropped from the summary.
    """
    summary = {}
    for label, boxes in raw.items():
        if isinstance(boxes, list):
            confs = [b.get("confidence", 0.0) for b in boxes if isinstance(b, dict)]
            if confs:
                summary[label] = max(confs)
        elif isinstance(boxes, (int, float)):
            summary[label] = float(boxes)
    return summary


class SensorState:
    """Thread-safe shared state updated by Bridge callbacks and AI callbacks."""

    _HISTORY = 120  # keep last 120 readings (~4 min at 2 s cadence)

    def __init__(self):
        self._lock = threading.Lock()
        self.turbidity_ntu: float = 0.0
        self.temperature_c: float = 0.0
        self.roll_deg: float = 0.0
        self.pitch_deg: float = 0.0
        self.yaw_deg: float = 0.0
        self.alerts: list[str] = []
        self._env_alerts: list[str] = []
        self._orientation_alerts: list[str] = []
        self.detections: dict[str, float] = {}   # label → best confidence this frame
        self.debris_events: list[str] = []        # timestamped log
        self.camera_frame: bytes | None = None     # latest annotated JPEG frame
        self.camera_frame_ts: float = 0.0

        self._turbidity_history: deque = deque(maxlen=self._HISTORY)
        self._temp_history:      deque = deque(maxlen=self._HISTORY)
        self._roll_history:      deque = deque(maxlen=self._HISTORY)
        self._pitch_history:     deque = deque(maxlen=self._HISTORY)

    def update_sensors(self, turbidity_ntu: float, temperature_c: float):
        with self._lock:
            self.turbidity_ntu = turbidity_ntu
            self.temperature_c = temperature_c
            ts = time.time()
            self._turbidity_history.append((ts, turbidity_ntu))
            self._temp_history.append((ts, temperature_c))

            alerts = []
            if turbidity_ntu > TURBIDITY_ALERT_NTU:
                alerts.append(f"⚠ High turbidity: {turbidity_ntu:.0f} NTU")
            if temperature_c > TEMP_HIGH_ALERT_C:
                alerts.append(f"⚠ High temp: {temperature_c:.1f} °C")
            if 0 < temperature_c < TEMP_LOW_ALERT_C:
                alerts.append(f"⚠ Low temp: {temperature_c:.1f} °C")
            self._env_alerts = alerts
            self.alerts = self._env_alerts + self._orientation_alerts

    def update_orientation(self, roll_deg: float, pitch_deg: float, yaw_deg: float):
        with self._lock:
            self.roll_deg = roll_deg
            self.pitch_deg = pitch_deg
            self.yaw_deg = normalize_yaw(yaw_deg)
            ts = time.time()
            self._roll_history.append((ts, roll_deg))
            self._pitch_history.append((ts, pitch_deg))

            self._orientation_alerts = evaluate_orientation_alerts(roll_deg, pitch_deg)
            self.alerts = self._env_alerts + self._orientation_alerts

    def update_detections(self, raw_detections: dict):
        detections = summarize_detections(raw_detections)
        debris = {k: v for k, v in detections.items() if is_debris(k)}
        with self._lock:
            self.detections = detections
            if debris:
                ts = time.strftime("%H:%M:%S")
                labels = ", ".join(f"{k} ({v:.0%})" for k, v in debris.items())
                entry = f"[{ts}] Debris — {labels}"
                self.debris_events.append(entry)
                if len(self.debris_events) > 100:
                    self.debris_events = self.debris_events[-100:]

    def update_frame(self, jpeg_bytes: bytes):
        with self._lock:
            self.camera_frame = jpeg_bytes
            self.camera_frame_ts = time.time()

    def snapshot(self):
        with self._lock:
            return dict(
                turbidity_ntu = self.turbidity_ntu,
                temperature_c = self.temperature_c,
                roll_deg      = self.roll_deg,
                pitch_deg     = self.pitch_deg,
                yaw_deg       = self.yaw_deg,
                alerts        = list(self.alerts),
                detections    = dict(self.detections),
                debris_events = list(self.debris_events[-20:]),
                turbidity_history = list(self._turbidity_history),
                temp_history      = list(self._temp_history),
                roll_history      = list(self._roll_history),
                pitch_history     = list(self._pitch_history),
                camera_frame      = self.camera_frame,
                camera_frame_age  = (time.time() - self.camera_frame_ts) if self.camera_frame else None,
            )
