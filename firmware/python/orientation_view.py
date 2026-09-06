# SPDX-FileCopyrightText: Copyright (C) 2026 MarineSentinel Project
# SPDX-License-Identifier: MPL-2.0

"""Self-contained CSS-3D capsule widget for the orientation dashboard section.

Rendered via st.components.v1.html as plain HTML/CSS — no external assets,
JS libraries, or CDN calls. The capsule is expected to be deployed far from
shore with only a LAN link to the board, so the dashboard must keep working
for a browser with no internet access.
"""

_TEMPLATE = """
<div class="scene">
  <div class="rig" style="transform: rotateY({yaw}deg) rotateZ({pitch}deg) rotateX({roll}deg);">
    <div class="face top">▲ UP</div>
    <div class="face bottom">▼ BILGE</div>
    <div class="face hull-a">MARINESENTINEL</div>
    <div class="face hull-b">MARINESENTINEL</div>
    <div class="face bow">BOW ▶</div>
    <div class="face stern">STERN</div>
  </div>
</div>
<style>
  html, body {{ margin: 0; background: transparent; }}
  .scene {{
    width: 100%; height: 300px; perspective: 900px;
    display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .rig {{
    width: 220px; height: 70px; position: relative;
    transform-style: preserve-3d;
    transition: transform .4s ease;
  }}
  .face {{
    position: absolute; display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 600; letter-spacing: .05em; color: #08202e;
    border: 1px solid rgba(0, 0, 0, .15);
  }}
  .top    {{ width: 220px; height: 70px; background: #cfe8ff; transform: rotateX(90deg) translateZ(35px); }}
  .bottom {{ width: 220px; height: 70px; background: #0b2f45; color: #cfe8ff; transform: rotateX(-90deg) translateZ(35px); }}
  .hull-a {{ width: 220px; height: 70px; background: #1b6ca8; color: #eaf6ff; transform: translateZ(35px); }}
  .hull-b {{ width: 220px; height: 70px; background: #1b6ca8; color: #eaf6ff; transform: rotateY(180deg) translateZ(35px); }}
  .bow    {{ width: 70px; height: 70px; background: #e8622c; color: #fff; transform: rotateY(90deg) translateZ(110px); }}
  .stern  {{ width: 70px; height: 70px; background: #5b6b73; color: #fff; transform: rotateY(-90deg) translateZ(110px); }}
</style>
"""


def capsule_html(roll_deg: float, pitch_deg: float, yaw_deg: float) -> str:
    """Render the capsule model at the given fused orientation (degrees).

    Axis convention (mount the MPU6050 flat with its silkscreen X-axis arrow
    pointing toward the capsule's bow):
      roll  — rotation about the bow/stern axis   (sketch: imu.getAngleX())
      pitch — nose up/down                         (sketch: imu.getAngleY())
      yaw   — heading, gyro-integrated only — drifts over time with no
              magnetometer to correct it            (sketch: imu.getAngleZ())
    """
    return _TEMPLATE.format(roll=roll_deg, pitch=pitch_deg, yaw=yaw_deg)
