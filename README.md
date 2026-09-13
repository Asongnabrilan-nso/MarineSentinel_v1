# 🌊 MarineSentinel

**A ~$300 floating AI sentinel that watches a river or coastline for plastic
pollution around the clock, and logs water quality — built on a single
Arduino UNO Q.**

📖 Full project write-up (story, build photos, step-by-step assembly):
[hackster.io/abrilannso/marinesentinel-60f927](https://www.hackster.io/abrilannso/marinesentinel-60f927)
· 🔧 Technical deep-dive: [`firmware/README.md`](firmware/README.md)

<img src="media/1780496834661.jpg" alt="MarineSentinel buoy — Fusion 360 cutaway render showing the sealed electronics stack inside the capsule" width="640">

---

## The problem

MarineSentinel started on a visit to Limbe Down Beach (Cameroon), watching
plastic wash in through the drains and inlets that feed the ocean — water
that local fishing communities depend on. Almost nobody measures any of this
continuously: pollution is recorded, if at all, by someone travelling to a
site to take one photo or one sample. Between visits the water is unwatched,
so a spill that lasts a day looks identical to one that lasts a month, and
neither can be traced back to a source.

The instruments that could fix this are priced out of reach — a commercial
multi-parameter water-quality sonde on a monitoring buoy runs roughly
US$25,000–40,000 before freight, and lands close to double that after
regional duty, VAT, and clearing. No local municipality instruments a river
at that price, so "we have no numbers" becomes the reason cleanup and public
health funding proposals fail.

## The solution

MarineSentinel is a small sealed buoy that floats on the water and watches
it for you, day and night:

- A **camera + on-device AI model** learns what floating plastic and debris
  look like and flags it when it sees it.
- Onboard sensors continuously measure **turbidity**, **water temperature**,
  and the buoy's own **tilt/motion** (orientation) from the waves — an
  always-on lab that never needs a boat trip to take a reading.
- A **GPS fix** locates every reading and every alert.
- Everything is served live from a **web dashboard the buoy hosts itself**
  over WiFi — open it on a phone at the water's edge, no internet required.

It doesn't scoop up trash — it's the sensor layer for someone else's
cleanup, telling a crew *where* and *when* debris is flowing and warning
people who depend on the water the moment a reading looks wrong. Every part
is either already on the bench or buyable locally within 48 hours, so a
local workshop can rebuild or repair it without waiting on an import.

## How it works — one board, two brains, over a bridge

The Arduino UNO Q carries two processors on one board, and MarineSentinel
gives each the job it's built for, passing messages between them over
[Arduino App Lab](https://docs.arduino.cc/software/app-lab/)'s **Router
Bridge**:

```
┌────────────────────────────────┐   Bridge (notify)   ┌──────────────────────────────────┐
│  MCU — Zephyr sketch (STM32)    │  sensor_data (2s)    │  MPU — Python (arduino:web_ui)    │
│  firmware/sketch/sketch.ino     │  imu_data (10 Hz)     │  firmware/python/main.py           │
│                                  │  gps_data (1 Hz)       │───────────────────────────────────│
│  A0    ── turbidity sensor      │ ─────────────────────▶│   sensors.py   — units, alerts,    │
│  D4    ── DS18B20 temp (1-Wire) │                        │                  thread-safe state │
│  QWIIC ── MPU6050 IMU (Wire1)   │                        │   data_store.py — InfluxDB history │
│  D20/21─ GPS (Serial3, TinyGPS) │  ◀──────────────────── │   VideoObjectDetection — YOLO-X /  │
│  LED3  ── green/red alert LED   │      set_alert(bool)   │      custom Edge Impulse model     │
└────────────────────────────────┘                        └──────────────────┬────────────────┘
                                                                                │ :7000 (Socket.IO)
                                                                                ▼
                                                                   assets/ static dashboard — LAN,
                                                                   no CDN, capsule tilt view + live
                                                                   camera + water-quality tiles
```

1. **The real-time microcontroller reads the world.** The sketch samples
   turbidity and a DS18B20 water-temperature probe every 2 s, fuses the
   MPU6050 accelerometer + gyroscope into roll/pitch/yaw at 10 Hz with a
   complementary filter, parses GPS NMEA sentences continuously and reports
   a fix once a second, and drives the onboard RGB LED green/red as a local
   alarm — all independent of whether Python is even listening.
2. **The Linux processor runs the AI and the dashboard.** A Python app,
   built as an always-on `arduino:web_ui` process (not Streamlit — see
   [`firmware/README.md`](firmware/README.md) for why that migration
   mattered), runs object detection on the USB camera feed, converts raw
   sensor values to engineering units, evaluates alert thresholds (including
   a capsize/listing check on tilt), writes history to an on-device
   InfluxDB, and serves a static HTML/JS dashboard over Socket.IO.
3. **The two halves stay in sync over the bridge.** The sketch fires
   `sensor_data`, `imu_data`, and `gps_data` messages up to Python; Python
   sends `set_alert` back down to drive the LED. The dashboard's camera pane
   and 3D capsule tilt view refresh in their own 10 Hz loop, independent of
   the rest of the page.

Three App Lab bricks do the heavy lifting (declared in
[`firmware/app.yaml`](firmware/app.yaml)):

| Brick | Purpose |
|---|---|
| `arduino:video_object_detection` | Runs the object-detection model (built-in YOLO-X, or a custom Edge Impulse export) against the USB camera stream |
| `arduino:web_ui` | Hosts the always-on Python process + the Socket.IO dashboard on port `7000` |
| `arduino:dbstorage_tsstore` | InfluxDB-backed time-series storage for sensor/orientation history |

The 3D capsule tilt indicator on the dashboard is drawn with plain CSS 3D
transforms — no Three.js, no CDN — so it still renders for a browser that
can only reach the buoy itself, out on the water with no internet path to
anywhere else.

## What works today

MarineSentinel is bench-proven and water-tested; the AI pipeline, dashboard,
and motion sensing run end to end on the real hardware:

- ✅ Object-detection model deployed on the board, running on a live USB
  camera feed, with annotated bounding-box frames on detection.
- ✅ Live web dashboard served from the board (`arduino:web_ui`, Socket.IO)
  — camera feed, detection log, and metrics all update without a full-page
  reload.
- ✅ MPU6050 IMU fused on the MCU; roll/pitch/yaw streamed to the dashboard
  at 10 Hz and driving a live CSS-3D capsule model.
- ✅ Turbidity + DS18B20 temperature sampled every 2 s, with alert
  thresholds and history tiles.
- ✅ GPS fix (lat/lon/speed/course/satellites) parsed on the MCU and pushed
  to the dashboard once a second.
- ✅ On-device InfluxDB logging of sensor, orientation, and detection
  history.
- ✅ Capsize/listing alert derived from tilt, wired back to the onboard LED.
- ✅ Camera and Bridge startup are retry-safe — a missing/busy USB camera or
  a failed IMU no longer takes the whole app down; each fails open and keeps
  reporting the rest of the system.

See [`firmware/README.md`](firmware/README.md) for the full changelog,
wiring notes, and the non-obvious bugs this surfaced along the way (I²C bus
selection on the QWIIC connector, Bridge/App.run() ordering, etc.).

## Why the Arduino UNO Q

- **Two processors, one board.** The real-time MCU owns the sensors and
  electronics; the Linux side only carries the vision model and dashboard —
  no separate SBC + microcontroller pair to wire together.
- **App Lab bricks instead of hand-rolled services.** The camera model
  runner, the dashboard, the time-series database, and start-on-boot all
  arrive as declared components in `app.yaml`.
- **The repo mirrors the device.** The committed project layout under
  [`firmware/`](firmware) is exactly the on-device app layout — what you
  clone is what runs.
- **One cable flashes both halves.** `arduino-app-cli app start` compiles
  and flashes the sketch, builds the Python environment, and brings the
  dashboard up in one command.

## Bill of materials — under $300, nothing imported

| Component | Notes |
|---|---|
| Arduino UNO Q | the board — MPU + MCU |
| USB webcam (e.g. Logitech HD Pro) | debris detection camera |
| MPU6050 6-DOF IMU (e.g. DFRobot breakout) | mounted on the QWIIC connector |
| DS18B20 waterproof temperature probe | 1-Wire, e.g. DFRobot Gravity |
| GPS receiver (e.g. Adafruit Ultimate GPS Breakout) | NMEA over Serial3 |
| Turbidity sensor, phototransistor output | e.g. SEN0189-class module |
| 2.5 W solar panel + buck converter | trickle-charges the buoy in the field |
| Li-Ion battery, 1000 mAh | onboard power |
| PETG filament | for the 3D-printed enclosure |

The added bill of materials — everything beyond the UNO Q itself — came to
roughly 157,506 XAF (~US$260) sourced entirely locally, keeping the whole
build under $300 with no import/customs step on the critical path.

## The enclosure

Custom-designed in Fusion 360 and 3D-printed in PETG. Five parts that snap
together with just two M3 screws:

- **Buoy Cover** — solar panel, GPS antenna, charging/power electronics.
- **Buoy Mid Body** — holds the camera for live footage.
- **Buoy Bottom** — IMU and other water-facing sensors.
- **Buoy Floating Base** — flotation (now polythene foam).
- **Electronics Enclosure** — the UNO Q, battery, and wiring.

STEP/STL files are in [`mechanical/stl/`](mechanical/stl); design source in
`mechanical/stl/MarineSentinel.step`.

<table>
<tr>
<td><img src="media/1780496826680.jpg" alt="Dimensioned CAD drawing of the buoy body" width="320"></td>
<td><img src="media/pics/IMG_20260904_074645.jpg" alt="Arduino UNO Q board" width="320"></td>
</tr>
<tr>
<td align="center"><sub>Buoy body — dimensioned Fusion 360 drawing</sub></td>
<td align="center"><sub>Arduino UNO Q — the two-processor board at the core of the build</sub></td>
</tr>
<tr>
<td><img src="media/photo_2026-09-11_09-25-02.jpg" alt="Sensor module mounted in the buoy bottom" width="320"></td>
<td><img src="media/photo_2026-09-11_09-39-22.jpg" alt="Power and GPS electronics mounted in the buoy cover" width="320"></td>
</tr>
<tr>
<td align="center"><sub>Sensor module mounted in the buoy bottom</sub></td>
<td align="center"><sub>Power + GPS electronics mounted in the buoy cover</sub></td>
</tr>
</table>

## Edge AI debris detection

The built-in `arduino:video_object_detection` brick runs a YOLO-X model out
of the box. For debris-specific detection, a custom model can be trained on
[Edge Impulse Studio](https://www.edgeimpulse.com/) — label photos of
plastic bags, bottles, and open ocean water, train, and export/deploy
straight to App Lab; no manual model files or SDK calls to manage.

<table>
<tr>
<td><img src="media/1780496837123.jpg" alt="Edge Impulse Studio dataset — labeled ocean water samples" width="320"></td>
<td><img src="media/ai-model-69ef2289b5d9c873409962.jpg" alt="Custom model training pipeline: labeled photos through Edge Impulse Studio to a MobileNetV2 model deployed as an App Lab brick" width="320"></td>
</tr>
<tr>
<td align="center"><sub>Labeling a training dataset in Edge Impulse Studio</sub></td>
<td align="center"><sub>Custom-model pipeline: photos → Edge Impulse → App Lab brick</sub></td>
</tr>
</table>

See [`firmware/README.md` §4](firmware/README.md#4-loading-a-different-edge-ai-model-edge-impulse)
for the exact steps to point `app.yaml` at a custom Edge Impulse export.

## Repository layout

```
MarineSentinel_v1/
├── firmware/               # the Arduino App — clone this onto the board
│   ├── app.yaml             # manifest + brick declarations
│   ├── python/               # main.py, sensors.py, data_store.py
│   ├── sketch/                # sketch.ino, sketch.yaml
│   ├── assets/                 # static dashboard (HTML/JS/CSS, Socket.IO)
│   └── README.md                # full technical write-up, wiring, troubleshooting
├── mechanical/              # Fusion 360 STEP + STL files for the enclosure
├── media/                   # build/CAD/dashboard photos used in this README
└── marinesentinel_spec.json # project spec (requirements, BOM, timeline)
```

## Quickstart

```bash
# On the board (SSH / App Lab terminal):
git clone https://github.com/Asongnabrilan-nso/MarineSentinel_v1.git ~/ArduinoApps/MarineSentinel_v1
arduino-app-cli app start ~/ArduinoApps/MarineSentinel_v1/firmware
```

This compiles and flashes `sketch/sketch.ino` to the MCU, builds the Python
environment, and starts the dashboard + video-detection runner + InfluxDB.
Open it from any device on the same LAN at `http://<board-ip>:7000`.

`app start` **stops whatever app is currently running** on the board — only
one App runs at a time. Full hardware wiring, everyday commands, and
troubleshooting live in [`firmware/README.md`](firmware/README.md).

## Credits

Built by [Asongna Brilan Nso Nkengafac](https://www.hackster.io/abrilannso).
Full project story, build log, and step-by-step assembly photos:
[hackster.io/abrilannso/marinesentinel-60f927](https://www.hackster.io/abrilannso/marinesentinel-60f927).

Source is licensed Mozilla Public License 2.0 (see SPDX headers in
`firmware/python/` and `firmware/sketch/`).
