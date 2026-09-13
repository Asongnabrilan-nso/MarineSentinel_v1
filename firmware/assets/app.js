// SPDX-FileCopyrightText: Copyright (C) 2026 MarineSentinel Project
// SPDX-License-Identifier: MPL-2.0

const ui = new WebUI();

const el = (id) => document.getElementById(id);

const connStatus = el('conn-status');
ui.on_connect(() => {
  connStatus.textContent = 'Live';
  connStatus.className = 'conn-status online';
});
ui.on_disconnect(() => {
  connStatus.textContent = 'Disconnected';
  connStatus.className = 'conn-status offline';
});

// ── Small dependency-free SVG line-chart helper ──────────────────────────────
// `series` is an array of [timestamp, value] pairs (as sent by the Python
// SensorState history buffers). Renders into a <polyline> sized to its
// parent <svg>'s viewBox.
function renderLine(polylineEl, series) {
  const svg = polylineEl.ownerSVGElement;
  const viewBox = svg.viewBox.baseVal;
  const w = viewBox.width;
  const h = viewBox.height;
  const pad = h * 0.1;

  if (!series || series.length < 2) {
    polylineEl.setAttribute('points', '');
    return;
  }

  const xs = series.map((p) => p[0]);
  const ys = series.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;

  const points = series
    .map(([t, v]) => {
      const x = ((t - minX) / spanX) * w;
      const y = h - pad - ((v - minY) / spanY) * (h - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  polylineEl.setAttribute('points', points);
}

// ── Metrics row + turbidity/temperature history ──────────────────────────────
ui.on_message('metrics', (data) => {
  el('turbidity-value').textContent = `${data.turbidity_ntu.toFixed(1)} NTU`;
  el('turbidity-label').textContent = data.turbidity_label;
  el('turbidity-sim-badge').hidden = !data.turbidity_simulated;

  const tempOk = data.temperature_c > -100;
  el('temp-value').textContent = tempOk ? `${data.temperature_c.toFixed(1)} °C` : '-- °C';
  el('temp-label').textContent = data.temperature_label;

  renderAlerts(data.alerts);
  renderStatusCard(data.alerts);

  renderLine(el('turbidity-line'), data.turbidity_history);
  const validTemps = (data.temp_history || []).filter(([, v]) => v > -100);
  renderLine(el('temp-line'), validTemps);
  el('sensor-waiting').hidden = (data.turbidity_history || []).length > 0;
});

// ── Orientation panel ──────────────────────────────────────────────────────
ui.on_message('orientation', (data) => {
  el('roll-value').textContent = `${data.roll_deg.toFixed(1)}°`;
  el('pitch-value').textContent = `${data.pitch_deg.toFixed(1)}°`;
  el('yaw-value').textContent = `${data.yaw_deg.toFixed(1)}°`;
  el('orientation-caption').textContent = data.label;

  el('capsule-rig').style.transform =
    `rotateY(${data.yaw_deg}deg) rotateZ(${data.pitch_deg}deg) rotateX(${data.roll_deg}deg)`;

  renderLine(el('roll-line'), data.roll_history);
  renderLine(el('pitch-line'), data.pitch_history);

  renderAlerts(data.alerts);
  renderStatusCard(data.alerts);
});

// ── Debris log + active detections ──────────────────────────────────────────
ui.on_message('detections', (data) => {
  const detections = data.detections || {};
  const entries = Object.entries(detections).sort((a, b) => b[1] - a[1]);

  const top = entries[0];
  el('detection-value').textContent = top ? top[0] : 'None';
  el('detection-detail').textContent = top ? `${Math.round(top[1] * 100)}%` : 'No objects';

  const barsHost = el('active-detections');
  barsHost.innerHTML = '';
  if (entries.length === 0) {
    barsHost.innerHTML = '<p class="caption">Camera scanning…</p>';
  } else {
    for (const [label, conf] of entries) {
      const pct = Math.round(conf * 100);
      const bar = document.createElement('div');
      bar.className = 'detection-bar';
      bar.innerHTML = `
        <div class="detection-bar-label"><span>${label}</span><span>${pct}%</span></div>
        <div class="detection-bar-track"><div class="detection-bar-fill" style="width:${pct}%"></div></div>
      `;
      barsHost.appendChild(bar);
    }
  }

  const events = data.debris_events || [];
  const logHost = el('debris-log');
  logHost.innerHTML = '';
  if (events.length === 0) {
    logHost.innerHTML = '<li class="caption">No debris detected yet.</li>';
  } else {
    for (const evt of [...events].reverse()) {
      const li = document.createElement('li');
      li.textContent = evt;
      logHost.appendChild(li);
    }
  }
});

// ── Live camera feed ──────────────────────────────────────────────────────
ui.on_message('camera', (data) => {
  const img = el('camera-image');
  const placeholder = el('camera-placeholder');
  if (data.image) {
    img.src = data.image;
    img.hidden = false;
    placeholder.hidden = true;
  } else {
    img.hidden = true;
    placeholder.hidden = false;
  }
  el('camera-caption').textContent = data.caption || '';
});

// ── GPS panel ────────────────────────────────────────────────────────────
ui.on_message('gps', (data) => {
  el('gps-fix-value').textContent = data.fix ? 'Fix acquired' : 'No fix';
  el('gps-lat-value').textContent = data.fix ? data.lat.toFixed(6) : '--';
  el('gps-lon-value').textContent = data.fix ? data.lon.toFixed(6) : '--';
  el('gps-speed-value').textContent = data.fix ? `${data.speed_kmph.toFixed(1)} km/h` : '-- km/h';
  el('gps-course-value').textContent = data.fix ? `${data.course_deg.toFixed(0)}°` : '--°';
  el('gps-sat-value').textContent = data.satellites;

  el('gps-caption').textContent = data.fix
    ? `Last update ${data.age_sec.toFixed(1)}s ago`
    : `Searching for satellites… (${data.satellites} visible)`;
});

// ── Shared alert rendering (fed by both metrics and orientation messages) ──
function renderAlerts(alerts) {
  const host = el('alerts-list');
  host.innerHTML = '';
  if (!alerts || alerts.length === 0) {
    host.innerHTML = '<div class="alert-ok">No active water quality alerts.</div>';
    return;
  }
  for (const a of alerts) {
    const div = document.createElement('div');
    div.className = 'alert-item';
    div.textContent = a;
    host.appendChild(div);
  }
}

function renderStatusCard(alerts) {
  const active = alerts && alerts.length > 0;
  el('status-value').textContent = active ? 'ALERT' : 'OK';
  const detail = el('status-detail');
  detail.textContent = active ? alerts[0] : 'All clear';
  detail.classList.toggle('alert', active);
}
