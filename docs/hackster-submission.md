# MarineSentinel

**A $250 floating AI sentinel that watches a river or coastline for plastic pollution around the clock — spotting debris with an onboard camera, logging water quality, tilt and position, and serving its own live dashboard with no internet — doing much of what a $40,000 monitoring buoy does at a fraction of the landed cost.**

> **How to use this file:** each `##` heading below maps to a field in the Hackster
> project editor. Paste the **Story** block into the Story editor, fill **Things used
> in this project** from the component picker, and attach files under **Schematics**,
> **Code** and **CAD / custom enclosures**. Replace every `![...]()` placeholder with a
> real upload. Lines in _italics inside square brackets_ are notes to you — delete them.

---

## Story

### The problem: the water with the worst plastic has the least data about it

MarineSentinel started on a visit to **Limbe Down Beach**. Discarded plastic was being
dumped straight into the ocean, and more of it kept washing onto the sand, carried in by
the currents. It had come down through the drains and inlets that empty into the sea. The
people there fish that water and eat what they catch — and when the water turns bad, they
are the first to get sick.

Almost nobody measures any of this continuously. Plastic pollution and water quality get
recorded — when they get recorded at all — by a person travelling to a site to take one
photo or one sample. Between visits the water is unwatched, so a pollution event that
lasts a day looks exactly like one that lasts a month, and neither can be traced back to
a source.

The instruments that would fix this are priced out of reach. A commercial
multi-parameter water-quality sonde on a monitoring buoy runs roughly
**US$25,000–40,000 before freight**, and lands in Cameroon at close to twice that after
CEMAC duty, 19.25% VAT and clearing. No municipality here will instrument a river at
**24–42 million CFA francs per station** — so *"we have no numbers"* becomes the standing
reason cleanup and public-health funding proposals fail.

| | Commercial monitoring station | **MarineSentinel v0.1** |
|---|---|---|
| Landed cost | 24–42,000,000 XAF | **&lt; 150,000 XAF (≈ US$250)** |
| Where you buy it | Imported, months of lead time | Douala &amp; Yaoundé markets, 48 hours |
| Debris detection | None | Onboard camera + edge AI |
| Works offline | Needs a backend/subscription | Serves its own dashboard, no internet |

![Limbe Down Beach — plastic accumulating on the shoreline]()
_[Add a photo from the Limbe visit if you have one, or a representative shoreline-pollution photo you have rights to.]_

### The solution: a cheap instrument that stays on the water when nobody else can

MarineSentinel is a small sealed buoy that floats on the water and watches it for you,
day and night.

- A **camera and a small AI model on board** learn what floating plastic looks like and
  flag it when they see it.
- At the same time the buoy measures **how cloudy the water is** (turbidity) and **how
  warm it is**, and senses its **own tilt and motion** from the waves — an onboard
  laboratory that runs continuously.
- Everything shows up **live on a web page the buoy serves over its own Wi-Fi**. You open
  it on a phone at the water's edge, with no internet needed.

It does not scoop up trash. It is the **sensor layer for someone else's cleanup**: it
tells a crew *where* and *when* debris is flowing, and it warns the people who depend on
the water the moment a reading looks wrong. It also watches itself — tilt, and whether it
may have capsized — while it drifts on a retrieval line.

Every part is either already on the bench or buyable in a local market within 48 hours.
Nothing is imported. That constraint is the whole point: **a workshop in Bamenda or Lagos
can rebuild this from parts they can actually get.**

![MarineSentinel dashboard — live camera feed, detection, and the 3D capsule view]()
_[Screen recording / screenshot of the running Streamlit dashboard.]_

### How it works: one board, two brains, talking over a bridge

The **Arduino UNO Q** carries two processors on a single board. MarineSentinel gives each
one the job it is built for and lets them pass messages back and forth through Arduino
**App Lab's Router Bridge**.

**1. The real-time microcontroller reads the world.**
An Arduino sketch on the **STM32U585** samples the turbidity cell and a DS18B20
water-temperature probe every 2 seconds, and fuses the **MPU6050** accelerometer and
gyroscope into roll, pitch and yaw ten times a second with a complementary filter. It
drives an onboard RGB LED green or red as a local alarm.

**2. The Linux processor runs the AI and the dashboard.**
A Python app built inside App Lab runs an **object-detection model on the USB camera
feed**, converts the raw sensor values to engineering units, checks alert thresholds
(including a capsize / listing check), writes history to an **on-device InfluxDB**
time-series store, and serves the live web dashboard.

**3. The two halves stay in sync over the Bridge.**
The sketch fires `sensor_data` and `imu_data` messages up to Python; Python sends
`set_alert` back down to the LED. The dashboard's camera pane and 3D capsule view refresh
in their own 10 Hz loop, independent of the rest of the page.

```
┌───────────────────────────┐   Router Bridge    ┌──────────────────────────────┐
│  Real-time MCU (STM32U585) │                    │  Linux MPU (Qualcomm)        │
│  Arduino sketch            │  ── sensor_data ─▶ │  App Lab Python app          │
│                            │  ── imu_data ────▶ │   • video_object_detection   │
│  A0   turbidity cell       │  ── imu_status ──▶ │   • streamlit_ui (dashboard) │
│  D2   DS18B20 temp probe   │                    │   • dbstorage_tsstore (Influx)│
│  I2C4 MPU6050 IMU          │  ◀──── set_alert ──│   • alert rules + CSV log    │
│  LED3 alert indicator      │                    │  USB camera ─▶ on-device model│
└───────────────────────────┘                    └───────────────┬──────────────┘
                                                                 │  LAN / Wi-Fi
                                                                 ▼
                                                     Phone or laptop dashboard
```

The three App Lab **bricks** — `video_object_detection`, `streamlit_ui`,
`dbstorage_tsstore` — are declared in `app.yaml` and do the heavy lifting. The 3D capsule
view is drawn with **plain CSS 3D transforms — no three.js, no CDN** — so the dashboard
renders fully for a browser that can only reach the buoy itself.

![Architecture / wiring diagram]()
_[Attach the block diagram under Schematics and reference it here.]_

### What works today — and what comes next

MarineSentinel v0.1 is **bench-proven and honest about it.** The AI pipeline, the
dashboard and the motion sensing work end-to-end on the real hardware. The water-quality
sensors and the sealed capsule are built and waiting to be integrated, and the first
water trial is the next milestone.

**✅ Working now — proven on the UNO Q**

- Object-detection model deployed on the board, running on a live USB camera feed
- Live web dashboard served from the board — annotated camera feed and a detection log
- MPU6050 IMU read on the MCU; fused roll / pitch / yaw streamed to the dashboard at 10 Hz
- A 3D capsule model in the dashboard that tilts with the live IMU data
- Dashboard tiles and history charts for turbidity and temperature (UI ready)
- On-device InfluxDB logging of sensor and orientation history
- Capsize / listing alert derived from tilt, wired back to the onboard LED

_Verified on-device, 2026-09-03: dashboard live in a browser, the 3D capsule tracking a
physical tilt, detection firing on real objects above 45% confidence._

**→ Next — built, parts in hand, not yet integrated**

- Turbidity cell and DS18B20 probe — physical wiring, potting and a bench calibration
- Custom debris model on Edge Impulse — a local dataset (~1,300 labelled frames so far);
  the model running now is a general COCO detector using *bottle / cup / bowl* as debris
  proxies
- Sealed capsule — parametric Fusion 360 assembly done, five STL parts exported, hull and
  replaceable camera-window ring printed and dry-fitted
- GPS on the MCU's spare UART for a coordinate on every detection
- microSD CSV logging that runs whether or not a dashboard is connected
- Wi-Fi access-point mode and start-on-boot

**+ v1.0 — the road to a field deployment**

- First tethered water trials; a 30-minute float test with a tissue-paper ingress witness
- Debris model fine-tuned on Douala frames shot through the real window at three times of
  day, so sun glare is in the training set
- Turbidity calibrated against a reference standard
- Solar charging and power management for multi-day endurance
- LoRa or cellular store-and-forward so alerts reach authorised people off-site
- Anti-fouling wiper or a scheduled window swap
- Partner with an NGO, local council or fisheries body to deploy a small fleet and
  publish an openly licensed local dataset

### Why the Arduino UNO Q

The closest regional prior work — a camera-plus-sensor rig deployed in Lagos Lagoon and
published in *Cambridge Prisms: Water* (2025) — ran on a Raspberry Pi 3 and got about
**six hours of battery**, with Wi-Fi that failed once the antenna was 10 cm below the
surface. A single always-on Linux board is the wrong tool for a buoy.

- **Two processors, one board.** A low-power real-time MCU holds the sensors and the
  alarm; the Linux side only carries the vision model and the dashboard.
- **App Lab bricks instead of services.** The camera model runner, the dashboard, the
  time-series database and start-on-boot arrive as declared components in `app.yaml` —
  not four daemons to hand-build and supervise.
- **The repo mirrors the device.** The committed project layout is exactly the on-device
  layout — what you clone is what runs.
- **One cable flashes both halves.** A single `arduino-app-cli app start` compiles the
  sketch, flashes the MCU, builds the Python environment and brings the dashboard up.

### Build it yourself — under 150,000 CFA francs, nothing imported

The added bill of materials — everything except the UNO Q itself — lands at 150,000 XAF
with no headroom. Every line is stocked in Douala or Yaoundé. There is no shipment
anywhere on the critical path and no customs event that can end the build.

| Part | Role | XAF |
|---|---|--:|
| Arduino UNO Q | Dual-brain compute (owned) | 0 |
| USB UVC webcam, 1080p | Vision input | 15,000 |
| MPU6050 IMU × 2 | Roll / pitch / yaw, wave motion | 6,000 |
| DS18B20 waterproof probe × 2 | Water temperature | 9,000 |
| IR-LED + phototransistor cell | Turbidity, self-built from local parts | 4,000 |
| NEO-6M GPS + antenna × 2 | Position on every detection | 24,000 |
| PETG filament, 1 kg | Printed hull + camera window ring | 15,000 |
| 20,000 mAh USB-PD power bank | Field power | 22,000 |
| microSD 32 GB × 2 | Onboard CSV log | 12,000 |
| Seals, glands, foam, ballast, retrieval line, hub, wiring, desiccant | Flotation, sealing, recovery | 43,000 |
| **Added BOM total** | **≈ US$250** | **150,000** |

### Honest scope — what v0.1 does not do

- **No water deployment yet** — the prototype is bench-proven; the first tethered float
  test is the next milestone.
- **Turbidity is an index, not NTU** — the sensing cell is self-built and has no traceable
  calibration standard behind it yet.
- **No solar or long endurance** — a USB power bank bounds each session to a few hours.
- **No cellular, LoRa or cloud** — the dashboard is reachable only over the buoy's own
  Wi-Fi, within radio range.
- **Heading drifts** — the MPU6050 has no magnetometer, so yaw is relative to boot, not a
  compass bearing.
- **Tethered only** — a retrieval line is mandatory; there is no mooring and no unattended
  deployment.
- **No object counting** — the output is a detection event and a debris-density class, not
  a count of items.

### Track record

- **3rd place** — TechMaster Event, Arduino 2.0 contest.
- **278+ reactions, 11 comments, 10 reposts** on the concept announcement — the response
  is what turned MarineSentinel from an idea into a build.
- **Grounded in the regional literature** — every known failure mode from the Lagos Lagoon
  deployment and the floating-plastics vision studies was adopted as a design requirement.

### Open source &amp; licensing

The parametric CAD, the firmware and the documentation are all published, released as one
downloadable package so a stranger can replicate the build from what is published.

- Hardware: **CERN-OHL-S**
- Firmware &amp; software: **MPL-2.0**
- Documentation &amp; dataset: **CC BY-SA**

_[Confirm these three before publishing — the firmware headers currently say MPL-2.0; the
original plan mentioned MIT for software and CERN-OHL-S + CC BY-SA for the rest.]_

---

## Things used in this project

### Hardware components

| Component | Qty | Notes |
|---|--:|---|
| Arduino UNO Q | 1 | Dual-brain board — STM32U585 MCU + Qualcomm Linux MPU |
| USB UVC webcam (1080p, manual focus preferred) | 1 | Vision input for the object-detection brick |
| InvenSense MPU6050 (GY-521 breakout) | 2 | 6-axis IMU on the QWIIC connector (I2C4 / `Wire1`) |
| Maxim DS18B20 waterproof temperature probe | 2 | 1-Wire, needs a 4.7 kΩ pull-up |
| IR LED + phototransistor (discrete) | 1 pair | Self-built turbidity cell, potted per the OpenCTD method |
| u-blox NEO-6M GPS module + patch antenna | 2 | Per-detection position (integration pending) |
| USB power bank, 20,000 mAh, 5 V / 3 A USB-C PD | 1 | Field power |
| microSD card, 32 GB, class 10 | 2 | Onboard CSV logging |
| PETG filament, 1 kg (clear + natural) | 1 | Printed hull and replaceable camera window ring |
| Cable glands, O-ring cord, silicone marine sealant | — | Sealing |
| Closed-cell foam / EPS + ballast | — | Buoyancy and self-righting trim |
| Floating retrieval rope, 15 m + hi-vis float | 1 | Mandatory — capsule is never deployed untethered |

### Software apps and online services

- **Arduino App Lab** — application framework, bricks, Router Bridge
- **Arduino bricks:** `video_object_detection`, `streamlit_ui`, `dbstorage_tsstore`
- **Edge Impulse Studio** — custom object-detection model training (in progress)
- **Streamlit** — the on-device dashboard UI
- **InfluxDB** — on-device time-series storage (via the tsstore brick)
- **Autodesk Fusion 360** — parametric CAD of the capsule

### Hand tools and fabrication machines

- FDM 3D printer (PETG-capable)
- Soldering iron, multimeter, USB power meter
- Epoxy potting supplies for the sensor probes

---

## Schematics

_[Attach as image + PDF:]_

- **System block diagram** — the two-brain architecture and the Router Bridge messages
  (`sensor_data`, `imu_data`, `imu_status`, `set_alert`).
- **STM32U585 pin map** — `A0` turbidity, `D2` DS18B20 1-Wire, QWIIC / I2C4 (`Wire1`)
  MPU6050, `LED3_R` / `LED3_G` alert, spare UART for GPS.
- **Turbidity cell** — IR LED + phototransistor divider, output clamped below 3.3 V
  before the ADC pin.

---

## Code

**Repository:** _[add your public repo URL]_

The repository mirrors the on-device App Lab layout exactly — what you clone is what runs.

```
firmware/
├── app.yaml               # App Lab manifest + brick declarations
├── python/
│   ├── main.py             # Streamlit dashboard + Bridge/AI wiring (entry point)
│   ├── sensors.py          # unit conversion, alert rules, thread-safe shared state
│   ├── data_store.py       # InfluxDB (time-series store) wrapper
│   └── orientation_view.py # CSS-3D capsule widget (no CDN / JS deps)
└── sketch/
    ├── sketch.ino          # MCU: sensor + IMU sampling, LED alert, Router Bridge
    └── sketch.yaml         # MCU build profile + pinned library versions
```

Key implementation notes:

- **Two-rate IMU handling** — the complementary filter is stepped every loop tick
  (sub-millisecond `dt`, accurate fusion) but only transmitted over the Bridge at 10 Hz.
- **QWIIC is a separate I2C bus** — on the UNO Q the QWIIC connector is I2C4 (`Wire1`),
  not the default `Wire` (I2C2). The sketch scans the bus and reports the failure over the
  Bridge so a wiring fault shows up in `app logs` without a serial monitor.
- **Offline-first dashboard** — the 3D capsule is rendered with `st.components.v1.html`
  and CSS `rotateX/Y/Z`; there are no `<script src>` or font/CDN calls anywhere in the UI.
- **Fail-open sensors** — a missing IMU or a `-127 °C` DS18B20 reading degrades one
  dashboard value; it never crashes the app.

---

## CAD, custom parts and enclosures

_[Attach from `mechanical/stl/`:]_

- `MarineSentinel.step` — full assembly
- `bottom half.stl`, `Buoy Mid Section.stl`, `Buoy Top.stl`, `electronics Case.stl`,
  `Floating Base.stl`, `Camera ring tightener.stl` — printable parts
- Parametric Fusion 360 source with a driven-parameter waterline; the camera window ring
  is a separate, replaceable part at a 20° downward tilt.

---

## Credits

**Asongna Brilan (PlastiBytes)** — solo build: concept, mechanical, firmware, edge AI,
dashboard, documentation. Douala, Cameroon.

Built for **Hackster.io — Invent the Future with Arduino UNO Q and App Lab**.
Submission deadline: 14 September 2026.
