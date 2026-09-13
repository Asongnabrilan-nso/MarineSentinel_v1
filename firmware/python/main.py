# SPDX-FileCopyrightText: Copyright (C) 2026 MarineSentinel Project
# SPDX-License-Identifier: MPL-2.0

# MarineSentinel — always-on backend + WebSocket dashboard.
#
# Runs on arduino:web_ui, a plain always-on Python process, instead of
# arduino:streamlit_ui. Streamlit only executes app code the first time a
# browser opens the dashboard, which meant the Bridge providers, camera/AI
# detector, and InfluxDB storage below never started on an unattended boat
# deployment where nobody opens the dashboard. web_ui has no such gating:
# everything below starts the instant the app boots, dashboard or not. The
# dashboard itself (assets/) is a static HTML/JS page that receives live
# updates over Socket.IO.

import base64
import os
import random
import threading
import time

from arduino.app_utils import App, Bridge, Logger
from arduino.app_utils.image import draw_bounding_boxes, get_image_bytes
from arduino.app_bricks.web_ui import WebUI
from arduino.app_bricks.video_objectdetection import VideoObjectDetection

from sensors import SensorState, raw_to_ntu, turbidity_label, temp_label, orientation_label
from data_store import SensorStore

logger = Logger("MarineSentinel")

ui = WebUI()
state = SensorState()
store = SensorStore()
store.start()

# ── Bench-test override: fake a clean-water turbidity reading ───────────────
# For testing the dashboard/pipeline without a calibrated SEN0189 on hand.
# OFF by default. Never enable this on a real deployment — the whole point of
# MarineSentinel is to detect *real* turbidity, and this substitutes a fake
# "clean water" value instead of the sensor's actual reading. When on, every
# affected reading is logged and flagged to the dashboard as simulated (see
# _on_sensor_data / _metrics_payload) so it's never mistaken for a real one,
# and simulated values are excluded from InfluxDB history (see data_store.py).
SIMULATE_TURBIDITY = os.environ.get("MARINESENTINEL_SIMULATE_TURBIDITY", "false").lower() == "true"
if SIMULATE_TURBIDITY:
    logger.warning("MARINESENTINEL_SIMULATE_TURBIDITY is ON — turbidity readings are FAKE "
                    "bench-test data, not the real sensor. Do not use this in a real deployment.")

# ── Edge AI: debris detection via YOLO-X ─────────────────────────────────────
detector = VideoObjectDetection(confidence=0.4, debounce_sec=3.0, camera_preview=True)


def _metrics_payload() -> dict:
    snap = state.snapshot()
    return {
        "turbidity_ntu": snap["turbidity_ntu"],
        "turbidity_label": turbidity_label(snap["turbidity_ntu"]),
        "temperature_c": snap["temperature_c"],
        "temperature_label": temp_label(snap["temperature_c"]),
        "turbidity_simulated": snap["turbidity_simulated"],
        "alerts": snap["alerts"],
        "turbidity_history": snap["turbidity_history"],
        "temp_history": snap["temp_history"],
    }


def _orientation_payload() -> dict:
    snap = state.snapshot()
    return {
        "roll_deg": snap["roll_deg"],
        "pitch_deg": snap["pitch_deg"],
        "yaw_deg": snap["yaw_deg"],
        "alerts": snap["alerts"],
        "label": orientation_label(snap["roll_deg"], snap["pitch_deg"]),
        "roll_history": snap["roll_history"],
        "pitch_history": snap["pitch_history"],
    }


def _detections_payload() -> dict:
    snap = state.snapshot()
    return {
        "detections": snap["detections"],
        "debris_events": snap["debris_events"],
    }


# ── Bridge: receive sensor readings from MCU ─────────────────────────────────
def _on_sensor_data(turbidity_raw: int, temp_c: float):
    if SIMULATE_TURBIDITY:
        ntu = round(random.uniform(10.0, 40.0), 1)   # bench-test stand-in: always "Clear"
        logger.warning(f"[SIMULATED] turbidity={ntu:.1f} NTU — real raw ADC={turbidity_raw} ignored")
    else:
        ntu = raw_to_ntu(turbidity_raw)

    state.update_sensors(ntu, temp_c, turbidity_simulated=SIMULATE_TURBIDITY)
    store.record(ntu, temp_c, store_turbidity=not SIMULATE_TURBIDITY)

    alert_active = bool(state.snapshot()["alerts"])
    Bridge.notify("set_alert", alert_active)
    ui.send_message("metrics", _metrics_payload())

    logger.info(f"Sensor: turbidity={ntu:.1f} NTU" + (" [SIMULATED]" if SIMULATE_TURBIDITY else "")
                + f"  temp={temp_c:.2f} °C"
                + ("  [ALERT]" if alert_active else ""))


Bridge.provide("sensor_data", _on_sensor_data)


# ── Bridge: receive fused orientation from the MPU6050 (MCU) ────────────────
def _on_imu_data(roll_deg: float, pitch_deg: float, yaw_deg: float):
    state.update_orientation(roll_deg, pitch_deg, yaw_deg)
    store.record_orientation(roll_deg, pitch_deg, yaw_deg)

    alert_active = bool(state.snapshot()["alerts"])
    Bridge.notify("set_alert", alert_active)
    ui.send_message("orientation", _orientation_payload())

    logger.info(f"IMU: roll={roll_deg:.1f}  pitch={pitch_deg:.1f}  yaw={yaw_deg:.1f}"
                + ("  [ALERT]" if alert_active else ""))


Bridge.provide("imu_data", _on_imu_data)


# ── Bridge: MPU6050 init status reported by the MCU (repeats while failed) ──
def _on_imu_status(status: int, scan_addr: int):
    if status == 0:
        logger.info("MPU6050: found and calibrated — orientation streaming")
        return

    if scan_addr == 0:
        hint = ("no I2C device responded on the bus at all — check power "
                 "(3.3V/GND) and the SDA/SCL connection (Qwiic connector "
                 "recommended)")
    elif scan_addr == 0x69:
        hint = ("found a device at 0x69 instead of the expected 0x68 — "
                 "this is the MPU6050 with its AD0 pin tied HIGH; call "
                 "imu.setAddress(0x69) before imu.begin() in the sketch, "
                 "or tie AD0 low")
    else:
        hint = (f"found a different I2C device at 0x{scan_addr:02X} — "
                 "check for an address conflict on the bus")

    logger.warning(f"MPU6050: init FAILED, status={status} — {hint}. "
                    "Orientation stays at 0.0/0.0/0.0 until this is fixed "
                    "and the app is restarted.")


Bridge.provide("imu_status", _on_imu_status)


# ── Bridge: receive GPS fix data from the MCU ────────────────────────────────
def _gps_payload() -> dict:
    snap = state.snapshot()
    return {
        "fix": snap["gps_fix"],
        "lat": snap["gps_lat"],
        "lon": snap["gps_lon"],
        "speed_kmph": snap["gps_speed_kmph"],
        "course_deg": snap["gps_course_deg"],
        "satellites": snap["gps_satellites"],
        "age_sec": snap["gps_age_sec"],
    }


def _on_gps_data(fix: bool, lat: float, lon: float, speed_kmph: float, course_deg: float, satellites: int):
    state.update_gps(fix, lat, lon, speed_kmph, course_deg, satellites)
    ui.send_message("gps", _gps_payload())


Bridge.provide("gps_data", _on_gps_data)


def _on_all_detections(detections: dict, frame: bytes):
    state.update_detections(detections)
    if frame is not None:
        try:
            annotated = draw_bounding_boxes(frame, detections)
            state.update_frame(get_image_bytes(annotated))
        except Exception as e:
            logger.warning(f"Camera preview: failed to draw bounding boxes: {e}")

    ui.send_message("detections", _detections_payload())


detector.on_detect_all(_on_all_detections)


def _start_detector_with_retry():
    """Start the camera/AI detector without blocking the rest of the app.

    detector.start() raises CameraOpenError when the USB camera isn't ready
    (unplugged, still enumerating, busy). Letting that exception escape at
    module level used to kill the whole Python process before App.run() —
    taking WebUI, the Bridge providers, and InfluxDB storage down with it, so
    the dashboard never came up at all. Retrying in the background instead
    keeps everything else running and picks the camera up whenever it
    becomes available.
    """
    while True:
        try:
            detector.start()
            logger.info("Camera + Edge AI detector started")
            return
        except Exception as e:
            logger.warning(f"Camera/detector failed to start ({e}); retrying in 10s — "
                            "dashboard, sensors, and storage continue without it.")
            time.sleep(10)


threading.Thread(target=_start_detector_with_retry, daemon=True).start()


def _live_preview_frame() -> bytes | None:
    """Read the detector's continuously-updated raw preview frame.

    on_detect_all() only fires when the model finds an object above the
    confidence threshold, but the model runner streams a preview frame on
    every cycle regardless. Reading it directly keeps the camera section
    live between detection events instead of freezing on the last hit.
    """
    try:
        with detector._camera_preview_lock:
            b64 = detector._last_camera_frame
        if not b64:
            return None
        _, _, data = b64.partition(",")
        return base64.b64decode(data) if data else None
    except Exception:
        return None


def _camera_tick():
    """Push the current camera frame + caption, matching the priority order:
    a fresh detection overlay, then the live raw feed, then a stale overlay,
    then a waiting placeholder.
    """
    snap = state.snapshot()
    annotated_frame = snap["camera_frame"]
    annotated_age = snap["camera_frame_age"]
    live_frame = _live_preview_frame()

    if annotated_frame is not None and annotated_age is not None and annotated_age < 5:
        image, caption = annotated_frame, f"⚠ Object detected {annotated_age:.1f}s ago"
    elif live_frame is not None:
        image, caption = live_frame, "Live feed"
    elif annotated_frame is not None:
        image, caption = annotated_frame, f"Last detection {annotated_age:.1f}s ago"
    else:
        image, caption = None, "Waiting for camera feed…"

    ui.send_message("camera", {
        "image": f"data:image/jpeg;base64,{base64.b64encode(image).decode()}" if image else None,
        "caption": caption,
    })


def _on_client_connect(sid: str):
    # Send a full snapshot right away so a newly-opened dashboard isn't blank
    # until the next sensor event / camera tick.
    ui.send_message("metrics", _metrics_payload(), room=sid)
    ui.send_message("orientation", _orientation_payload(), room=sid)
    ui.send_message("detections", _detections_payload(), room=sid)
    ui.send_message("gps", _gps_payload(), room=sid)
    _camera_tick()


ui.on_connect(_on_client_connect)

logger.info("MarineSentinel initialised — Bridge + AI detector + dashboard running")


def _loop():
    # Matches the MCU's 10 Hz imu_data send rate (see IMU_SEND_INTERVAL_MS in
    # sketch.ino) — going faster than the data source itself sends just
    # re-renders the same values, so there's no point pushing this lower
    # without also raising the MCU's send rate.
    _camera_tick()
    time.sleep(0.1)


App.run(user_loop=_loop)
