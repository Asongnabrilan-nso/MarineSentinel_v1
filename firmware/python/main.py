# SPDX-FileCopyrightText: Copyright (C) 2026 MarineSentinel Project
# SPDX-License-Identifier: MPL-2.0

# MarineSentinel — live dashboard entry point.
# Streamlit re-runs this script on every user interaction.
# All bricks and shared state are cached with @st.cache_resource so they
# start exactly once and persist across re-runs.

import base64
import time

from arduino.app_utils import App, Bridge, Logger
from arduino.app_utils.image import draw_bounding_boxes, get_image_bytes
from arduino.app_bricks.streamlit_ui import st
from arduino.app_bricks.video_objectdetection import VideoObjectDetection

from sensors import SensorState, raw_to_ntu, turbidity_label, temp_label, orientation_label
from data_store import SensorStore
from orientation_view import capsule_html

logger = Logger("MarineSentinel")

# ── System init (runs once per process) ──────────────────────────────────────

@st.cache_resource
def _init_system():
    state = SensorState()
    store = SensorStore()
    store.start()

    # ── Bridge: receive sensor readings from MCU ──────────────────────────
    def _on_sensor_data(turbidity_raw: int, temp_c: float):
        ntu = raw_to_ntu(turbidity_raw)
        state.update_sensors(ntu, temp_c)
        store.record(ntu, temp_c)

        # Reflect alert state back to MCU LED
        alert_active = bool(state.alerts)
        Bridge.notify("set_alert", alert_active)

        logger.info(f"Sensor: turbidity={ntu:.1f} NTU  temp={temp_c:.2f} °C"
                    + ("  [ALERT]" if alert_active else ""))

    Bridge.provide("sensor_data", _on_sensor_data)

    # ── Bridge: receive fused orientation from the MPU6050 (MCU) ──────────
    def _on_imu_data(roll_deg: float, pitch_deg: float, yaw_deg: float):
        state.update_orientation(roll_deg, pitch_deg, yaw_deg)
        store.record_orientation(roll_deg, pitch_deg, yaw_deg)

        alert_active = bool(state.alerts)
        Bridge.notify("set_alert", alert_active)

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

    # ── Edge AI: debris detection via YOLO-X ─────────────────────────────
    detector = VideoObjectDetection(confidence=0.4, debounce_sec=3.0, camera_preview=True)

    def _on_all_detections(detections: dict, frame: bytes):
        state.update_detections(detections)
        if frame is not None:
            try:
                annotated = draw_bounding_boxes(frame, detections)
                state.update_frame(get_image_bytes(annotated))
            except Exception as e:
                logger.warning(f"Camera preview: failed to draw bounding boxes: {e}")

    detector.on_detect_all(_on_all_detections)
    detector.start()

    logger.info("MarineSentinel initialised — Bridge + AI detector running")
    return state, store, detector


state, store, detector = _init_system()

# App.run() starts each brick's background loops (Bridge dispatch, the video
# detector's WebSocket + camera-forwarding threads, ...). It must run before
# the auto-refresh st.rerun() below, since st.rerun() aborts the script
# immediately and never reaches code placed after it. Safe to call on every
# rerun: framework-managed App.run() is idempotent and returns immediately
# instead of blocking.
App.run()


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


# ── Dashboard layout ──────────────────────────────────────────────────────────

snap = state.snapshot()

st.set_page_config(
    page_title="MarineSentinel",
    page_icon="🌊",
    layout="wide",
)

st.title("🌊 MarineSentinel — Marine Water Quality Monitor")

# The camera feed and IMU orientation change far faster than the rest of the
# dashboard, but the whole script previously only redrew on the shared 3 s
# `time.sleep(3); st.rerun()` cycle at the bottom. A fragment auto-reruns
# *itself* on its own faster cadence without re-running (or re-fetching) the
# rest of the page. Matches the MCU's 10 Hz `imu_data` send rate (see
# IMU_SEND_INTERVAL_MS in sketch.ino) — going faster than the data source
# itself sends just re-renders the same values, so there's no point pushing
# this lower without also raising the MCU's send rate.
@st.fragment(run_every=0.1)
def _live_panel():
    live_snap = state.snapshot()

    st.subheader("📷 Live Camera — Edge AI Monitoring")

    annotated_frame = live_snap["camera_frame"]
    annotated_age = live_snap["camera_frame_age"]
    live_frame = _live_preview_frame()

    if annotated_frame is not None and annotated_age is not None and annotated_age < 5:
        st.image(annotated_frame, caption=f"⚠ Object detected {annotated_age:.1f}s ago", width='stretch')
    elif live_frame is not None:
        st.image(live_frame, caption="Live feed", width='stretch')
    elif annotated_frame is not None:
        st.image(annotated_frame, caption=f"Last detection {annotated_age:.1f}s ago", width='stretch')
    else:
        st.info("Waiting for camera feed…")

    st.divider()

    st.subheader("🧭 Orientation — MPU6050 IMU")

    orient_left, orient_right = st.columns([2, 1])

    with orient_left:
        st.components.v1.html(
            capsule_html(live_snap["roll_deg"], live_snap["pitch_deg"], live_snap["yaw_deg"]),
            height=300,
        )
        st.caption(orientation_label(live_snap["roll_deg"], live_snap["pitch_deg"]))

    with orient_right:
        st.metric("Roll", f"{live_snap['roll_deg']:.1f}°")
        st.metric("Pitch", f"{live_snap['pitch_deg']:.1f}°")
        st.metric("Yaw (heading)", f"{live_snap['yaw_deg']:.1f}°",
                   delta="drifts w/o magnetometer", delta_color="off")

        roll_hist = live_snap["roll_history"]
        pitch_hist = live_snap["pitch_history"]
        if roll_hist:
            import pandas as pd

            st.line_chart(
                pd.DataFrame({
                    "Roll (°)":  [v for _, v in roll_hist],
                    "Pitch (°)": [v for _, v in pitch_hist],
                }),
                height=160,
                width='stretch',
            )

# ── Top metrics row ───────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)

with col1:
    ntu = snap["turbidity_ntu"]
    st.metric(
        label="Turbidity",
        value=f"{ntu:.1f} NTU",
        delta=turbidity_label(ntu),
        delta_color="off",
    )

with col2:
    temp = snap["temperature_c"]
    st.metric(
        label="Water Temperature",
        value=f"{temp:.1f} °C" if temp > -100 else "-- °C",
        delta=temp_label(temp),
        delta_color="off",
    )

with col3:
    alerts = snap["alerts"]
    st.metric(
        label="System Status",
        value="ALERT" if alerts else "OK",
        delta=alerts[0] if alerts else "All clear",
        delta_color="inverse" if alerts else "off",
    )

with col4:
    detections = snap["detections"]
    top = max(detections, key=detections.get) if detections else "None"
    conf = f"{detections[top]:.0%}" if detections else ""
    st.metric(
        label="Last AI Detection",
        value=top,
        delta=conf if conf else "No objects",
        delta_color="off",
    )

st.divider()

_live_panel()

st.divider()

# ── Middle: sensor charts + debris event feed ─────────────────────────────────
left, right = st.columns([2, 1])

with left:
    st.subheader("Sensor History")

    t_hist = snap["turbidity_history"]
    temp_hist = snap["temp_history"]

    if t_hist:
        import pandas as pd

        ntu_values = [v for _, v in t_hist]
        st.line_chart(
            pd.DataFrame({"Turbidity (NTU)": ntu_values}),
            height=200,
            width='stretch',
        )

    if temp_hist:
        temp_values = [v for _, v in temp_hist if v > -100]
        if temp_values:
            st.line_chart(
                pd.DataFrame({"Temperature (°C)": temp_values}),
                height=200,
                width='stretch',
            )
    else:
        st.info("Waiting for sensor data from MCU…")

with right:
    st.subheader("Edge AI — Debris Log")

    events = snap["debris_events"]
    if events:
        for evt in reversed(events):
            st.text(evt)
    else:
        st.info("No debris detected yet.")

    st.subheader("Active Detections")
    if detections:
        for label, conf in sorted(detections.items(), key=lambda x: -x[1]):
            st.progress(conf, text=f"{label}: {conf:.0%}")
    else:
        st.caption("Camera scanning…")

st.divider()

# ── Alert feed ────────────────────────────────────────────────────────────────
st.subheader("Alerts")
if alerts:
    for a in alerts:
        st.error(a)
else:
    st.success("No active water quality alerts.")

# ── Auto-refresh every 3 seconds ─────────────────────────────────────────────
time.sleep(3)
st.rerun()
