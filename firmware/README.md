# 🌊 MarineSentinel

Marine water quality monitoring for the Arduino UNO Q, combining real-time
sensor fusion (turbidity + temperature + orientation) on the MCU with Edge AI
debris detection and a live web dashboard on the MPU.

- **MCU (sketch)** — samples a turbidity sensor and a DS18B20 temperature
  probe every 2 s, fuses accel+gyro from an MPU6050 (QWIIC/I2C) into
  roll/pitch/yaw at 10 Hz, streams all of it to the MPU over the Router
  Bridge, and drives an onboard RGB LED (green/red) as a local alert
  indicator.
- **MPU (Python)** — receives sensor + orientation readings, converts them to
  engineering units, evaluates alert thresholds (including a capsize/tilt
  check), stores history in InfluxDB, runs YOLO-X object detection on a USB
  camera feed to spot floating debris, and publishes everything — including
  a live 3D capsule orientation view — to a Streamlit dashboard on port
  `7000`.

---

## 1. Architecture

```
┌───────────────────────────┐  Router Bridge (2s / 100ms)  ┌──────────────────────────────┐
│  MCU (Zephyr sketch)      │  turbidityRaw, tempC         │  MPU (Python / Streamlit)     │
│  sketch/sketch.ino        │  roll, pitch, yaw            │  python/main.py                │
│                            │ ───────────────────────────▶│   ├─ sensors.py (state+rules) │
│  A0  ── turbidity sensor  │                              │   ├─ data_store.py (InfluxDB)  │
│  D2  ── DS18B20 (1-Wire)  │  ◀─────────────────────────  │   ├─ orientation_view.py       │
│  QWIIC ── MPU6050 (IMU)   │      set_alert(bool)         │   │    (CSS-3D capsule widget) │
│    (I2C4 = Wire1)         │                              │   └─ VideoObjectDetection      │
│  LED3 ── alert indicator  │                              │        (YOLO-X, USB camera)    │
└───────────────────────────┘                              └──────────────┬────────────────┘
                                                                            │ :7000
                                                                            ▼
                                                                Browser dashboard (LAN),
                                                                camera + orientation refresh
                                                                independently at 10 Hz via
                                                                an st.fragment
```

Bricks used (`app.yaml`):

| Brick | Purpose |
|---|---|
| `arduino:video_object_detection` | Runs the YOLO-X object-detection model against the USB camera stream |
| `arduino:streamlit_ui` | Hosts the web dashboard on port 7000 |
| `arduino:dbstorage_tsstore` | InfluxDB-backed time series storage for sensor history |

---

## 2. Challenges & solutions

Building the Python side surfaced a few non-obvious issues — recorded here
so they aren't rediscovered the hard way.

### 2.1 `Logger.info(...)` crashed the app on boot
`arduino.app_utils.Logger` is a `logging.Logger` subclass meant to be
**instantiated** (`logger = Logger("MyApp")`), not called as a static
method. The original code called `Logger.info("...")` directly on the
class, which Python interprets as `Logger.info(self="...")` — missing the
required `msg` argument, raising `TypeError` and crashing the whole
Streamlit script before anything rendered.

**Fix:** instantiate one module-level logger per file
(`logger = Logger("MarineSentinel")`) and call `logger.info(...)` on the
instance.

### 2.2 `App.run()` was placed after `st.rerun()` — bricks never started
The dashboard auto-refreshes every 3 s with `time.sleep(3); st.rerun()`.
`st.rerun()` aborts the running script immediately (it's a Streamlit
control-flow exception, not a normal return) — so any code placed after it
**never executes**. `App.run()` was the last line of the file, after the
`st.rerun()` call.

This matters because `AppController` (the object behind `App`) only starts
a brick's background threads — the video detector's WebSocket connection to
the model runner and its camera→runner TCP forwarding loop — inside
`App.run()`. With `App.run()` unreachable, the camera opened fine (it's
started explicitly via `detector.start()`), but no frames or detections
ever made it back to Python: the WebSocket never connected, and
`on_detect_all()` never fired.

**Fix:** call `App.run()` immediately after brick initialization, *before*
the dashboard layout and the auto-refresh `st.rerun()`. This is safe on
every re-run: in Streamlit's "framework-managed" mode `App.run()` is
idempotent and returns immediately instead of blocking — it only actually
starts brick threads on the first call.

### 2.3 Detection payload shape didn't match what the code assumed
`VideoObjectDetection.on_detect_all()`'s docstring says the callback
receives `{label: confidence}`, but the installed brick source
(`arduino/app_bricks/video_objectdetection/__init__.py`) actually builds
`{label: [{"confidence": ..., "bounding_box_xyxy": ...}, ...]}` — a list of
detections per label, since a frame can contain multiple instances of the
same class. Code written against the docstring's shape crashes or silently
misbehaves (e.g. `f"{confidence:.0%}"` on a list).

**Fix:** `sensors.summarize_detections()` reduces the raw
`{label: [box, ...]}` payload to `{label: best_confidence}` for display,
while debris logging still works off the normalized summary.

### 2.4 The live camera feed only updates when something is detected
By design, `on_detect_all()` (and the frame it passes) only fires when the
model finds an object above the confidence threshold — there's no public
"give me every frame" callback. That's fine for event logging, but a
"live camera" section that freezes on the last detected object isn't
actually live.

**Fix:** the detector keeps a continuously-updated raw preview frame
internally (`detector._last_camera_frame`, refreshed by the model runner on
every cycle). `main.py` reads that directly as a fallback so the feed stays
live between detections, and swaps in the bounding-box-annotated frame for
a few seconds right after a detection fires. This touches a private
attribute, not public API — if a future SDK version renames it, the code
fails closed (`try/except` → falls back to "Waiting for camera feed…"),
it doesn't crash the dashboard.

### 2.5 Orientation: feed the complementary filter fast, report it slow
The MPU6050 doesn't output an angle directly — `MPU6050_light`'s fused
roll/pitch come from a complementary filter that blends gyro integration
(`angle += gyroRate * dt`) with the accelerometer's tilt estimate on every
call to `update()`. The turbidity/temperature loop only samples every 2 s,
so calling `imu.update()` on that same coarse cadence would feed the filter
a 2-second `dt` — the single-step gyro integration term would dominate the
fused angle and only get pulled back toward the (correct) accelerometer
reading by a small filter coefficient each time, making roll/pitch sluggish
and inaccurate.

**Fix:** `sketch.ino`'s `loop()` calls `imu.update()` on *every* tick
(sub-millisecond `dt`, accurate fusion) but only sends the result over the
Bridge every `IMU_SEND_INTERVAL_MS` (10 Hz) via a separate `lastImuSendMs`
timer — decoupling the filter's internal update rate from how often Python
actually needs a fresh reading. Turbidity/temperature sampling keeps its own
independent 2 s timer, unchanged.

### 2.5b The QWIIC connector is a *different* I2C bus than plain `Wire`
The MPU6050 was correctly wired to the board's QWIIC connector, powered, and
still got a hard I2C failure — `Wire.begin(); imu.begin()` returned status 1
(NACK), and a full 1–127 address bus scan found **nothing at all**. The
board's official pinout PDF and the ArduinoCore-zephyr devicetree overlay
(`arduino_uno_q_stm32u585xx.overlay`) explain why:

```
zephyr,user { i2cs = <&i2c2>, <&i2c4>, <&i2c3>; ... };
```

`Wire.h` declares one `arduino::ZephyrI2C` object per entry in that list, in
order — so plain `Wire` is **I2C2** (the digital header's D20/D21 pins),
`Wire1` is **I2C4**, and `Wire2` is **I2C3** (the analog header's A4/A5
pins). The pinout diagram confirms the QWIIC connector's SDA/SCL pins
(`PD13`/`PD12`) are wired to I2C4 — i.e. **`Wire1`**, not the default `Wire`.
Two electrically separate I2C buses meant the scan on `Wire` legitimately
found nothing; the MPU6050 was never on that bus to begin with.

**Fix:** `MPU6050 imu(Wire1)` and `Wire1.begin()` instead of `Wire`. If you
move the MPU6050 to the analog header's I2C3 pins instead, it's `Wire2`; the
plain header-adjacent `Wire` is I2C2 (D20/D21), not exposed via any labeled
connector on this board's default configuration.

### 2.6 Yaw has no accelerometer-equivalent correction — it will drift
Roll and pitch are self-correcting: the accelerometer's gravity-vector tilt
estimate continuously pulls the gyro-integrated angle back toward truth, so
they stay accurate indefinitely. Yaw (heading) has no such reference on a
plain MPU6050 (no magnetometer) — `getAngleZ()` is pure gyro integration and
accumulates drift for as long as the capsule runs.

**Fix:** this is disclosed, not "fixed" — the dashboard labels the Yaw
metric "drifts w/o magnetometer" and `sensors.normalize_yaw()` just wraps
the value into `[-180, 180)` for readability. Treat yaw as relative heading
since boot, not an absolute compass bearing. Adding an AK8963/QMC5883L
magnetometer (or an MPU9250) and fusing it in would fix this properly.

### 2.7 A 3D dashboard widget still has to work with no internet
The orientation view needed *some* 3D rendering to show the capsule's
attitude, but the capsule is meant to be deployed far from shore with only a
LAN link to the board — a widget that pulls three.js or any other library
from a CDN would show a blank box the moment a viewer's browser has no
internet path to that CDN, which defeats the point of a status dashboard.

**Fix:** `orientation_view.py` renders the capsule as a plain CSS 3D
transform (`rotateX/Y/Z` on a `<div>` built from six `position:absolute`
faces) via `st.components.v1.html` — no `<script src>`, no fonts, no
network calls of any kind. It's a cruder cube-and-labels capsule rather than
a shaded 3D mesh, but it keeps rendering correctly for a browser that only
ever reaches the board itself.

### 2.8 A 3 s full-page rerun makes 10 Hz data feel frozen
Sending orientation at 10 Hz over the Bridge didn't make the dashboard feel
any faster — because the whole page only ever redrew on the shared
`time.sleep(3); st.rerun()` cycle at the bottom of the script. The camera
and orientation section could be showing a value up to 3 s old no matter how
fast the MCU or the video model produced fresh data; the bottleneck was
entirely in how often the *page* re-rendered, not how often new data
arrived.

**Fix:** wrapped the Live Camera + Orientation section in
`@st.fragment(run_every=0.1)`. A fragment auto-reruns *only itself* on its
own schedule, without re-running or re-fetching the rest of the page (top
metrics, sensor history charts, debris log) — so this section now redraws
independently at 10 Hz, matching the MCU's `IMU_SEND_INTERVAL_MS`. One
subtlety: a fragment's own reruns don't re-execute code *outside* it, so it
must take its own fresh `state.snapshot()` rather than reusing a `snap`
computed once at the top of the full script.

### 2.9 Streamlit's re-run model requires strict init/render separation
Streamlit re-executes the whole script top-to-bottom on every interaction
and on every auto-refresh. Anything that opens hardware (camera, Bridge
handlers, DB connections) must be wrapped in `@st.cache_resource` so it
runs exactly once per process — otherwise every 3-second refresh would try
to reopen the USB camera and re-register Bridge handlers. `_init_system()`
in `main.py` is the single place this happens; everything below it is
pure render code safe to re-run.

---

## 3. Setup

### 3.1 Hardware

| Sensor | Pin | Notes |
|---|---|---|
| Turbidity (e.g. SEN0189, analog) | `A0` | 3.3 V ref, 10-bit ADC, oversampled ×8 |
| DS18B20 temperature probe (1-Wire) | `D2` | needs a 4.7 kΩ pull-up between data and 3.3 V if not already on the module |
| MPU6050 IMU (accel + gyro) | **QWIIC connector** (`Wire1` = I2C4 — see §2.5b, *not* plain `Wire`) | default address `0x68` (`AD0` low); mount the breakout flat with its silkscreen **X-axis arrow pointing toward the bow** — the sketch reads `getAngleX()`/`getAngleY()`/`getAngleZ()` as roll/pitch/yaw assuming that mounting |
| USB camera | any USB-A port (use a USB-C hub if needed) | required for object detection |
| Alert LED | onboard `LED3_R` / `LED3_G` (RGB, MCU-controllable) | green = OK, red = ALERT |

### 3.2 First run

```bash
# From the board (SSH / App Lab terminal):
arduino-app-cli app start ~/ArduinoApps/marine-sentinel
```

This compiles and flashes `sketch/sketch.ino` to the MCU, then builds the
Python virtualenv and starts the Streamlit UI + video detection runner +
InfluxDB containers. First start takes a few minutes (Streamlit,
pandas, numpy, pyarrow etc. get downloaded into `.cache/.venv`).

Open the dashboard from any device on the same LAN:

```
http://<board-ip>:7000
```

### 3.3 Everyday commands

```bash
arduino-app-cli app restart ~/ArduinoApps/marine-sentinel      # apply code changes
arduino-app-cli app logs    ~/ArduinoApps/marine-sentinel --follow   # Python/Streamlit logs
arduino-app-cli monitor                                        # MCU Serial.print() output
arduino-app-cli app stop    ~/ArduinoApps/marine-sentinel
```

`app start`/`app restart` **stop whatever app is currently running** on the
board — only one app runs at a time.

### 3.4 Troubleshooting

- **"No available cameras found"** on restart — the previous process
  hadn't released `/dev/video0` yet (docker container teardown race).
  Wait a few seconds and restart again; check `fuser -v /dev/video0` to see
  who currently holds it.
- **Dashboard shows `-- °C` / "Sensor Error"** — DS18B20 returns `-127.00`
  when it can't be read (not wired, no pull-up, or wrong pin). `temp_label()`
  in `sensors.py` maps anything `< -100` to "Sensor Error".
- **"Waiting for camera feed…" forever** — check
  `arduino-app-cli app logs ... | grep VideoObjectDetection` for a line
  reading `WebSocket connection established`. If it's missing, `App.run()`
  likely isn't being reached (see §2.2) or the `ei-video-obj-detection-runner`
  container isn't healthy (`docker ps`).
- **Orientation stuck at 0.0° / 0.0° / 0.0°** — no serial monitor needed:
  `arduino-app-cli app logs` prints `MPU6050: init FAILED, status=N — ...`
  repeatedly (every `IMU_SEND_INTERVAL_MS`, currently 100 ms) while the IMU
  isn't initialized, including the result of an I2C bus scan. If the scan
  found **nothing** (`scan_addr=0`), double check
  power and the QWIIC cable seating first, then confirm the sketch is
  actually using **`Wire1`** (the QWIIC connector is I2C4, a different bus
  than plain `Wire`/I2C2 — see §2.5b) — this was the actual root cause the
  first time around. If the scan found a device at `0x69`, AD0 is tied HIGH;
  either tie it low or call `imu.setAddress(0x69)`. The sketch fails open:
  turbidity/temperature keep working normally either way, orientation just
  stays unreported (`imuReady` stays `false`, no `imu_data` is sent).
- **Camera/orientation feel laggy or stuck for a few seconds** — see §2.8.
  Confirm `_live_panel()` in `main.py` is still decorated with
  `@st.fragment(run_every=...)` — without it, this section falls back to the
  slower shared 3 s full-page refresh.
- **Roll/Pitch look plausible but Yaw drifts over minutes** — expected, see
  §2.6. The MPU6050 has no magnetometer, so heading is gyro-integration only.

---

## 4. Loading a different Edge AI model (Edge Impulse)

The object-detection brick supports both Arduino's built-in models and
custom models trained on [Edge Impulse](https://edgeimpulse.com).

1. **Train & export on Edge Impulse Studio.** Build an object detection
   project, then export/deploy it as a Linux **`.eim`** model targeting the
   board's platform (UNO Q / imola).
2. **Import the model onto the board.** Upload it through App Lab's model
   manager (or place the exported files under
   `/home/arduino/.arduino-bricks/ei-models`, the path the brick reads from
   — see `CUSTOM_MODEL_PATH` in the brick's `brick_config.yaml`).
3. **Confirm it's registered:**
   ```bash
   arduino-app-cli model list
   ```
   Custom Edge Impulse imports show up as `ei-model-<id>-<n>` alongside the
   built-ins (`yolox-object-detection`, `face-detection`, ...).
4. **Point `app.yaml` at it:**
   ```yaml
   bricks:
     - arduino:video_object_detection:
         model: ei-model-XXXXXX-N     # the ID from `model list`
   ```
5. **Update the debris/classification logic.** `sensors.DEBRIS_CLASSES` is
   hardcoded to the COCO labels the current YOLO-X model can output
   (`bottle`, `cup`, `bowl`, ...). A custom model will emit **its own**
   label set — update `DEBRIS_CLASSES` (or replace the whole `is_debris()`
   check) to match the new model's classes, otherwise nothing will ever log
   as debris even if detections are firing correctly.
6. **Restart:** `arduino-app-cli app restart ~/ArduinoApps/marine-sentinel`.

---

## 5. Adding more sensors

The turbidity + temperature pair follows a repeatable pattern; a new sensor
means touching four places. Worked example — adding a pH sensor on `A1`:

1. **`sketch/sketch.ino`** — read the new pin in `loop()` and add it to the
   existing `Bridge.notify()` call (or send a separate notify if it's on a
   different cadence):
   ```cpp
   #define PH_PIN A1
   ...
   int phRaw = analogRead(PH_PIN);
   Bridge.notify("sensor_data", turbidityRaw, tempC, phRaw);
   ```
   If the sensor needs a library (I²C, extra driver, ...), declare it under
   `sketch/sketch.yaml` → `libraries:` with a pinned version — there's no
   separate "install" step, the build profile is the source of truth.

2. **`python/main.py`** — extend `_on_sensor_data`'s signature to match the
   new `Bridge.notify()` arity (positional args must line up):
   ```python
   def _on_sensor_data(turbidity_raw: int, temp_c: float, ph_raw: int):
       ph = raw_to_ph(ph_raw)          # add the conversion in sensors.py
       state.update_sensors(ntu, temp_c, ph)
   ```

3. **`python/sensors.py`** — add the raw→engineering-units conversion
   (mirroring `raw_to_ntu()`), an alert threshold if relevant, and extend
   `SensorState`/`update_sensors()`/`snapshot()` to carry the new field and
   its history deque.

4. **`python/main.py` (dashboard section)** — add a `st.metric(...)` in the
   top row and a `st.line_chart(...)` in the Sensor History column, same
   shape as the existing turbidity/temperature ones. Optionally call
   `store.record(...)` with the new field name so it lands in InfluxDB too
   (`data_store.py` → add a `FIELD_PH = "ph"` constant and pass it through
   `record()`).

Then `arduino-app-cli app clean-cache user:marine-sentinel --force` if the
sketch build looks stale, and `arduino-app-cli app restart ...`.

---

## 6. Project layout

```
marine-sentinel/
├── app.yaml              # manifest + brick declarations
├── python/
│   ├── main.py            # Streamlit dashboard + Bridge/AI wiring (entry point)
│   ├── sensors.py          # unit conversion, alert rules, shared thread-safe state
│   ├── data_store.py       # InfluxDB (TimeSeriesStore) wrapper
│   └── orientation_view.py # CSS-3D capsule widget (no CDN/JS deps)
├── sketch/
│   ├── sketch.ino          # MCU: sensor + IMU sampling, LED alert, Bridge
│   └── sketch.yaml         # MCU build profile + library versions
└── README.md
```

---

## 7. Changelog

Keep this section updated with dated entries as the project evolves —
newest first.

### 2026-09-03 (2)
- Fixed the MPU6050 not being detected at all: the QWIIC connector on the
  UNO Q is wired to a separate I2C peripheral (**I2C4 = `Wire1`**, devicetree
  order `i2cs = <&i2c2>, <&i2c4>, <&i2c3>` → `Wire`=I2C2, `Wire1`=I2C4,
  `Wire2`=I2C3), not the plain default `Wire` (I2C2, digital pins D20/D21)
  the sketch originally opened. `sketch.ino` now uses `Wire1` throughout.
- Added an I2C bus scan (`scanI2CBus()`) that runs whenever `imu.begin()`
  fails, and a Bridge `imu_status` message (repeated on the same
  `IMU_SEND_INTERVAL_MS` timer as `imu_data` while failed, to survive the
  Python-side handler registering after MCU boot) so a wiring problem shows
  up in `app logs` without needing a working serial monitor.
- Fixed both the live camera feed and the orientation view feeling stuck:
  the whole dashboard previously only redrew on the shared
  `time.sleep(3); st.rerun()` cycle, so a value could be up to 3 s stale.
  Moved both into an `st.fragment(run_every=...)` block, which auto-reruns
  *only* that section on its own schedule without re-running the rest of
  the page.
- Tuned for responsiveness: MCU `IMU_SEND_INTERVAL_MS` 1000→100 (10 Hz) and
  the dashboard fragment's `run_every` 1→0.1 (10 Hz) to match — going faster
  on one side without the other just re-renders/re-sends the same value.
- Verified on-device: `app logs` shows `MPU6050: found and calibrated —
  orientation streaming` after the `Wire1` fix, and `IMU: roll=... pitch=...
  yaw=...` lines arriving roughly every 100 ms. Confirmed live in the
  browser by the user.

### 2026-09-03
- Added MPU6050 orientation sensing: `sketch.ino` now fuses accel+gyro via
  `MPU6050_light` into roll/pitch/yaw and streams it to Python once a second
  over a new `imu_data` Bridge message, decoupled from the existing
  turbidity/temperature 2 s loop (§2.5).
- Added a "🧭 Orientation" dashboard section: a dependency-free CSS-3D
  capsule model (`orientation_view.py`, `st.components.v1.html`, no CDN/JS
  libraries — §2.7) plus Roll/Pitch/Yaw metrics and a tilt-history chart.
- Added a capsize/listing alert (`sensors.TILT_WARN_DEG` /
  `TILT_CRITICAL_DEG`) that merges into the existing alert feed and LED
  indicator alongside the turbidity/temperature alerts.
- Orientation history is persisted to InfluxDB (`data_store.record_orientation`)
  the same way turbidity/temperature already are.
- Yaw is gyro-integration only (no magnetometer) and will drift over a long
  deployment — disclosed on the dashboard and in §2.6 rather than "fixed".
- Verified on-device: `arduino-app-cli app start` compiled and flashed the
  sketch cleanly with the new `MPU6050_light` dependency; the Python changes
  were syntax- and logic-checked inside the app's actual running container
  (`sensors.py`/`orientation_view.py` unit-exercised, `main.py` compiles
  clean, `st.components.v1.html` confirmed present in the installed
  Streamlit 1.63.0). The live dashboard render (3D capsule responding to a
  physical tilt) was **not** visually confirmed in a browser this session —
  no browser-automation tool was available. Please open
  `http://<board-ip>:7000`, tilt the capsule, and confirm the capsule model
  and Roll/Pitch/Yaw track it before relying on this in the field.

### 2026-09-02
- Fixed `Logger.info(...)` being called as a static method, which crashed
  the app on every boot (§2.1).
- Fixed `App.run()` being placed after the auto-refresh `st.rerun()`,
  which silently prevented the video detector's WebSocket and camera
  threads from ever starting (§2.2).
- Fixed detection payload parsing: `sensors.summarize_detections()` now
  correctly handles the brick's real `{label: [box, ...]}` shape instead
  of the docstring's simplified `{label: confidence}` (§2.3).
- Added the "📷 Live Camera — Edge AI Monitoring" dashboard section:
  annotated (bounding-box) frames on detection, falling back to a
  continuously-updated raw preview between detections (§2.4).
- Enabled `camera_preview=True` on `VideoObjectDetection` and draw
  bounding boxes via `arduino.app_utils.image.draw_bounding_boxes`.
- Replaced deprecated `use_container_width=True` with `width='stretch'`
  (Streamlit 1.63 removes it after 2025-12-31).
- Verified end-to-end on-device: Bridge sensor stream, InfluxDB writes,
  live camera feed, and object detection ("person", "laptop" recognized
  at >45% confidence) all confirmed working via the running dashboard.
