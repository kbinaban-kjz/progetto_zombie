/* =========================================================================
   PROTOCOLLO LAZZARO — globo interattivo
   Canvas 2D, nessuna dipendenza esterna.
   ========================================================================= */
(() => {
  'use strict';

  const TAU = Math.PI * 2;
  const DEG = Math.PI / 180;

  const DATA = window.MAP_DATA;
  const GRID = window.LAND_GRID;

  if (!DATA || !GRID) {
    console.error('Dati mappa mancanti.');
    return;
  }

  const TYPES = DATA.types;
  const NODES = DATA.nodes;
  const BY_ID = new Map(NODES.map((n) => [n.id, n]));
  const LINKS = DATA.links
    .map(([from, to]) => ({ from: BY_ID.get(from), to: BY_ID.get(to) }))
    .filter((l) => l.from && l.to);

  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------------------------------------------------------------- stato */

  const state = {
    yaw: -10 * DEG,
    pitch: 20 * DEG,
    zoom: 1,
    baseR: 300,
    spin: true,
    activeId: null,
    hoverId: null,
    hoverSource: null,
    pinnedId: null,
    pointerDown: false,
    dragging: false,
    moved: false,
    pointerId: null,
    startX: 0,
    startY: 0,
    lastX: 0,
    lastY: 0,
    lastInteraction: performance.now() - 5000,
    focusTarget: null,
    bootDone: false
  };

  const pointer = { x: 0, y: 0, inside: false };
  const activeTypes = new Set(Object.keys(TYPES));

  /* ------------------------------------------------------------ canvas */

  const canvas = document.getElementById('globe');
  const ctx = canvas.getContext('2d', { alpha: true });

  let W = 0;
  let H = 0;
  let DPR = 1;
  let CX = 0;
  let CY = 0;
  let R = 300;

  let sinY = 0;
  let cosY = 1;
  let sinP = 0;
  let cosP = 1;

  const P = { x: 0, y: 0, z: 0 };
  const hitNodes = [];

  /* ---------------------------------------------------------- geometria */

  const VECS = new Map();
  NODES.forEach((n) => {
    const la = n.lat * DEG;
    const lo = n.lon * DEG;
    const cl = Math.cos(la);
    VECS.set(n.id, [cl * Math.sin(lo), Math.sin(la), cl * Math.cos(lo)]);
  });

  const land = { x: [], y: [], z: [], count: 0 };
  const stars = [];
  const motes = [];

  const STAR_COUNT = 150;
  const MOTE_COUNT = 26;

  function seedAtmosphere() {
    for (let i = 0; i < STAR_COUNT; i++) {
      stars.push({
        x: Math.random(),
        y: Math.random(),
        s: 0.5 + Math.random() * 1.4,
        a: 0.12 + Math.random() * 0.5,
        p: Math.random() * TAU,
        red: Math.random() < 0.14
      });
    }
    for (let i = 0; i < MOTE_COUNT; i++) {
      motes.push({
        x: Math.random(),
        y: Math.random(),
        s: 0.4 + Math.random() * 1.1,
        v: 0.002 + Math.random() * 0.008,
        p: Math.random() * TAU
      });
    }
  }

  function decodeLand() {
    const raw = atob(GRID.data);
    const width = GRID.width;
    const height = GRID.height;
    const count = 46000;
    const golden = Math.PI * (3 - Math.sqrt(5));

    function isLand(latDeg, lonDeg) {
      const gx = Math.floor(((lonDeg + 180) / 360) * width);
      const gy = Math.floor(((90 - latDeg) / 180) * height);
      if (gx < 0 || gx >= width || gy < 0 || gy >= height) return false;
      const bit = gy * width + gx;
      const byte = raw.charCodeAt(bit >> 3);
      return ((byte >> (7 - (bit & 7))) & 1) === 1;
    }

    for (let i = 0; i < count; i++) {
      const y = 1 - ((i + 0.5) * 2) / count;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = i * golden;
      const x = Math.cos(th) * r;
      const z = Math.sin(th) * r;
      const lat = Math.asin(y) / DEG;
      const lon = Math.atan2(x, z) / DEG;
      if (!isLand(lat, lon)) continue;
      land.x.push(x);
      land.y.push(y);
      land.z.push(z);
    }
    land.count = land.x.length;
  }

  /* ------------------------------------------------------------ layout */

  function layout() {
    W = window.innerWidth;
    H = window.innerHeight;
    DPR = Math.min(2, window.devicePixelRatio || 1);

    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);

    if (W <= 820) {
      state.baseR = Math.min(W * 0.98, H * 0.58) * 0.5;
      CX = W * 0.5;
      CY = H * 0.44;
    } else if (W <= 1180) {
      state.baseR = Math.min(W * 0.62, H * 0.74) * 0.5;
      CX = W * 0.42;
      CY = H * 0.49;
    } else {
      state.baseR = Math.min(W * 0.79, H * 0.79) * 0.5;
      CX = W * 0.5;
      CY = H * 0.5 - 4;
    }
    R = state.baseR * state.zoom;
  }

  /* --------------------------------------------------------- proiezione */

  function projectVec(x0, y0, z0, alt = 1) {
    const x1 = x0 * cosY + z0 * sinY;
    const z1 = -x0 * sinY + z0 * cosY;
    const y2 = y0 * cosP - z1 * sinP;
    const z2 = y0 * sinP + z1 * cosP;

    P.x = CX + x1 * R * alt;
    P.y = CY - y2 * R * alt;
    P.z = z2;
    return P;
  }

  function projectLL(latDeg, lonDeg, alt = 1) {
    const la = latDeg * DEG;
    const lo = lonDeg * DEG;
    const cl = Math.cos(la);
    return projectVec(cl * Math.sin(lo), Math.sin(la), cl * Math.cos(lo), alt);
  }

  function inverseProject(sx, sy) {
    const x1 = (sx - CX) / R;
    const y2 = (CY - sy) / R;
    const d = x1 * x1 + y2 * y2;
    if (d > 1) return null;

    const z2 = Math.sqrt(1 - d);
    const y0 = y2 * cosP + z2 * sinP;
    const z1 = -y2 * sinP + z2 * cosP;
    const x0 = x1 * cosY - z1 * sinY;
    const z0 = x1 * sinY + z1 * cosY;

    return {
      lat: Math.asin(clamp(y0, -1, 1)) / DEG,
      lon: Math.atan2(x0, z0) / DEG
    };
  }

  function updateTrig() {
    sinY = Math.sin(state.yaw);
    cosY = Math.cos(state.yaw);
    sinP = Math.sin(state.pitch);
    cosP = Math.cos(state.pitch);
    R = state.baseR * state.zoom;
  }

  /* ------------------------------------------------------------ helpers */

  function clamp(v, min, max) {
    return v < min ? min : v > max ? max : v;
  }

  function rgba(hex, alpha) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }

  function esc(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtCoord(lat, lon) {
    const la = `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? 'N' : 'S'}`;
    const lo = `${Math.abs(lon).toFixed(2)}°${lon >= 0 ? 'E' : 'O'}`;
    return `${la} / ${lo}`;
  }

  function fmtSigned(value, digits) {
    return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(digits).padStart(digits + 4, '0')}`;
  }

  function waveBars() {
    let html = '';
    for (let i = 0; i < 14; i++) {
      html += `<i style="--h:${3 + ((i * 5) % 9)};--d:${i}"></i>`;
    }
    return `<span class="wave" aria-hidden="true">${html}</span>`;
  }

  function traceBars(node) {
    let html = '';
    for (let i = 0; i < 46; i++) {
      const base = Math.abs(Math.sin(i * 0.73 + node.lat * 0.2)) * 11;
      const spike = (i + Math.round(node.reliability)) % 11 === 0 ? 8 : 0;
      const height = Math.max(2, Math.round(base + spike));
      html += `<i style="--h:${height};--d:${i}"></i>`;
    }
    return html;
  }

  /* ------------------------------------------------------------ disegno */

  function drawSpace(now) {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#040706';
    ctx.fillRect(0, 0, W, H);

    for (let i = 0; i < stars.length; i++) {
      const s = stars[i];
      const twinkle = 0.55 + 0.45 * Math.sin(now * 0.0011 + s.p);
      const alpha = s.a * twinkle;
      ctx.fillStyle = s.red
        ? `rgba(210, 95, 115, ${alpha.toFixed(3)})`
        : `rgba(160, 205, 182, ${alpha.toFixed(3)})`;
      ctx.fillRect(s.x * W, s.y * H, s.s, s.s);
    }

    for (let i = 0; i < motes.length; i++) {
      const m = motes[i];
      const x = (m.x * W + Math.sin(now * 0.00016 + m.p) * 26 + now * m.v * 0.05) % W;
      const y = (m.y * H + now * m.v * 0.5) % H;
      ctx.fillStyle = `rgba(177, 200, 185, ${(0.1 + m.s * 0.1).toFixed(3)})`;
      ctx.fillRect(x, y, m.s, m.s);
    }
  }

  function drawAtmosphere() {
    const glow = ctx.createRadialGradient(CX, CY, R * 0.93, CX, CY, R * 1.27);
    glow.addColorStop(0, 'rgba(52, 211, 153, 0.14)');
    glow.addColorStop(0.32, 'rgba(52, 211, 153, 0.06)');
    glow.addColorStop(0.66, 'rgba(245, 182, 66, 0.026)');
    glow.addColorStop(0.88, 'rgba(190, 30, 58, 0.05)');
    glow.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = glow;
    ctx.fillRect(CX - R * 1.4, CY - R * 1.4, R * 2.8, R * 2.8);
  }

  function drawGlobeBase() {
    const ocean = ctx.createRadialGradient(CX - R * 0.38, CY - R * 0.42, R * 0.04, CX, CY, R * 1.02);
    ocean.addColorStop(0, '#16362c');
    ocean.addColorStop(0.45, '#0b2019');
    ocean.addColorStop(0.8, '#04110d');
    ocean.addColorStop(1, '#020806');
    ctx.beginPath();
    ctx.arc(CX, CY, R, 0, TAU);
    ctx.fillStyle = ocean;
    ctx.fill();

    ctx.save();
    ctx.beginPath();
    ctx.arc(CX, CY, R, 0, TAU);
    ctx.clip();

    const light = ctx.createRadialGradient(CX - R * 0.52, CY - R * 0.58, 0, CX - R * 0.1, CY - R * 0.12, R * 1.22);
    light.addColorStop(0, 'rgba(126, 240, 190, 0.11)');
    light.addColorStop(0.35, 'rgba(82, 180, 140, 0.045)');
    light.addColorStop(0.7, 'rgba(20, 60, 46, 0.01)');
    light.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = light;
    ctx.fillRect(CX - R, CY - R, R * 2, R * 2);

    const rimGlow = ctx.createRadialGradient(CX, CY, R * 0.82, CX, CY, R * 1.01);
    rimGlow.addColorStop(0, 'rgba(52, 211, 153, 0)');
    rimGlow.addColorStop(0.82, 'rgba(52, 211, 153, 0.03)');
    rimGlow.addColorStop(0.97, 'rgba(60, 220, 165, 0.13)');
    rimGlow.addColorStop(1, 'rgba(60, 220, 165, 0)');
    ctx.fillStyle = rimGlow;
    ctx.fillRect(CX - R, CY - R, R * 2, R * 2);
    ctx.restore();
  }

  function drawGraticule() {
    ctx.lineWidth = 0.6;
    ctx.strokeStyle = 'rgba(130, 180, 156, 0.10)';

    for (let lon = -180; lon < 180; lon += 30) {
      ctx.beginPath();
      let pen = false;
      for (let lat = -85; lat <= 85; lat += 5) {
        const p = projectLL(lat, lon);
        if (p.z > 0.012) {
          if (!pen) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
          pen = true;
        } else {
          pen = false;
        }
      }
      ctx.stroke();
    }

    for (let lat = -60; lat <= 60; lat += 30) {
      ctx.beginPath();
      ctx.strokeStyle = lat === 0 ? 'rgba(160, 205, 180, 0.16)' : 'rgba(130, 180, 156, 0.10)';
      let pen = false;
      for (let lon = -180; lon <= 180; lon += 4) {
        const p = projectLL(lat, lon);
        if (p.z > 0.012) {
          if (!pen) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
          pen = true;
        } else {
          pen = false;
        }
      }
      ctx.stroke();
    }
  }

  function drawLand() {
    const buckets = [[], [], [], [], [], [], [], []];
    const zoomScale = clamp(state.zoom, 0.75, 1.6);

    for (let i = 0; i < land.count; i++) {
      const x0 = land.x[i];
      const y0 = land.y[i];
      const z0 = land.z[i];

      const x1 = x0 * cosY + z0 * sinY;
      const z1 = -x0 * sinY + z0 * cosY;
      const y2 = y0 * cosP - z1 * sinP;
      const z2 = y0 * sinP + z1 * cosP;

      if (z2 <= 0.008) continue;
      const bucket = Math.min(7, (z2 * 8) | 0);
      buckets[bucket].push(CX + x1 * R, CY - y2 * R);
    }

    const baseSize = clamp(1.05 + state.zoom * 0.32, 1.1, 1.9);

    for (let b = 0; b < 8; b++) {
      const bucket = buckets[b];
      if (!bucket.length) continue;
      const alpha = 0.16 + (b / 7) * 0.7;
      const size = (1.03 + b * 0.12) * baseSize;
      ctx.fillStyle = `rgba(166, 208, 184, ${alpha.toFixed(3)})`;
      ctx.beginPath();
      for (let i = 0; i < bucket.length; i += 2) {
        ctx.rect(bucket[i], bucket[i + 1], size, size);
      }
      ctx.fill();
    }
  }

  function drawShading() {
    const shadow = ctx.createRadialGradient(CX - R * 0.26, CY - R * 0.3, R * 0.1, CX, CY, R * 1.04);
    shadow.addColorStop(0, 'rgba(0, 0, 0, 0)');
    shadow.addColorStop(0.58, 'rgba(0, 0, 0, 0.05)');
    shadow.addColorStop(1, 'rgba(0, 0, 0, 0.64)');
    ctx.fillStyle = shadow;
    ctx.fillRect(CX - R, CY - R, R * 2, R * 2);

    const warm = ctx.createLinearGradient(CX - R, CY + R, CX + R, CY - R);
    warm.addColorStop(0, 'rgba(120, 18, 38, 0.14)');
    warm.addColorStop(0.45, 'rgba(80, 12, 26, 0.03)');
    warm.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = warm;
    ctx.fillRect(CX - R, CY - R, R * 2, R * 2);
  }

  function drawArcs(now) {
    const time = now / 1000;

    for (let li = 0; li < LINKS.length; li++) {
      const link = LINKS[li];
      const a = VECS.get(link.from.id);
      const b = VECS.get(link.to.id);
      if (!a || !b) continue;

      const dot = clamp(a[0] * b[0] + a[1] * b[1] + a[2] * b[2], -1, 1);
      const omega = Math.acos(dot);
      const sinOmega = Math.sin(omega);
      const steps = 52;

      ctx.beginPath();
      let pen = false;
      for (let i = 0; i <= steps; i++) {
        const t = i / steps;
        let vx;
        let vy;
        let vz;
        if (sinOmega < 0.0001) {
          vx = a[0] * (1 - t) + b[0] * t;
          vy = a[1] * (1 - t) + b[1] * t;
          vz = a[2] * (1 - t) + b[2] * t;
        } else {
          const wa = Math.sin((1 - t) * omega) / sinOmega;
          const wb = Math.sin(t * omega) / sinOmega;
          vx = a[0] * wa + b[0] * wb;
          vy = a[1] * wa + b[1] * wb;
          vz = a[2] * wa + b[2] * wb;
        }
        const alt = 1 + Math.sin(Math.PI * t) * 0.055;
        const p = projectVec(vx, vy, vz, alt);
        if (p.z > 0.015) {
          if (!pen) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
          pen = true;
        } else {
          pen = false;
        }
      }
      ctx.setLineDash([2, 7]);
      ctx.lineDashOffset = -(time * 7 + li * 3);
      ctx.lineWidth = 0.7;
      ctx.strokeStyle = 'rgba(245, 182, 66, 0.17)';
      ctx.stroke();
      ctx.setLineDash([]);

      // pacchetto dati lungo l'arco
      const travel = (time * 0.055 + li * 0.137) % 1;
      let vx;
      let vy;
      let vz;
      if (sinOmega < 0.0001) {
        vx = a[0] * (1 - travel) + b[0] * travel;
        vy = a[1] * (1 - travel) + b[1] * travel;
        vz = a[2] * (1 - travel) + b[2] * travel;
      } else {
        const wa = Math.sin((1 - travel) * omega) / sinOmega;
        const wb = Math.sin(travel * omega) / sinOmega;
        vx = a[0] * wa + b[0] * wb;
        vy = a[1] * wa + b[1] * wb;
        vz = a[2] * wa + b[2] * wb;
      }
      const pp = projectVec(vx, vy, vz, 1 + Math.sin(Math.PI * travel) * 0.055);
      if (pp.z > 0.015) {
        ctx.beginPath();
        ctx.arc(pp.x, pp.y, 1.7, 0, TAU);
        ctx.fillStyle = 'rgba(245, 182, 66, 0.85)';
        ctx.shadowColor = 'rgba(245, 182, 66, 0.8)';
        ctx.shadowBlur = 7;
        ctx.fill();
        ctx.shadowBlur = 0;
      }
    }
  }

  function drawRim(now) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(CX, CY, R, 0, TAU);
    ctx.strokeStyle = 'rgba(120, 220, 180, 0.24)';
    ctx.lineWidth = 1;
    ctx.shadowColor = 'rgba(52, 211, 153, 0.55)';
    ctx.shadowBlur = 16;
    ctx.stroke();
    ctx.restore();

    // anello orbitale
    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(-now * 0.000035);
    ctx.beginPath();
    ctx.arc(0, 0, R * 1.105, 0, TAU);
    ctx.setLineDash([2, 24]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(135, 178, 156, 0.17)';
    ctx.stroke();
    ctx.setLineDash([]);

    const ang = now * 0.00019;
    const sx = Math.cos(ang) * R * 1.105;
    const sy = Math.sin(ang) * R * 1.105;
    ctx.fillStyle = 'rgba(245, 182, 66, 0.9)';
    ctx.shadowColor = 'rgba(245, 182, 66, 0.9)';
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.arc(sx, sy, 1.6, 0, TAU);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.restore();
  }

  function drawReticle(x, y, color, time) {
    ctx.save();
    ctx.translate(x, y);
    ctx.strokeStyle = rgba(color, 0.8);
    ctx.lineWidth = 1;

    ctx.save();
    ctx.rotate(time * 0.45);
    ctx.beginPath();
    ctx.arc(0, 0, 17, 0, TAU);
    ctx.setLineDash([3, 7]);
    ctx.stroke();
    ctx.restore();

    ctx.setLineDash([]);
    const d = 23;
    const len = 5;
    ctx.beginPath();
    ctx.moveTo(-d, -d + len);
    ctx.lineTo(-d, -d);
    ctx.lineTo(-d + len, -d);
    ctx.moveTo(d - len, -d);
    ctx.lineTo(d, -d);
    ctx.lineTo(d, -d + len);
    ctx.moveTo(d, d - len);
    ctx.lineTo(d, d);
    ctx.lineTo(d - len, d);
    ctx.moveTo(-d + len, d);
    ctx.lineTo(-d, d);
    ctx.lineTo(-d, d - len);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(-d - 4, 0);
    ctx.lineTo(-d + 1, 0);
    ctx.moveTo(d + 4, 0);
    ctx.lineTo(d - 1, 0);
    ctx.moveTo(0, -d - 4);
    ctx.lineTo(0, -d + 1);
    ctx.moveTo(0, d + 4);
    ctx.lineTo(0, d - 1);
    ctx.stroke();

    ctx.restore();
  }

  function drawMarkers(now) {
    const time = now / 1000;
    hitNodes.length = 0;

    const entries = [];

    for (let i = 0; i < NODES.length; i++) {
      const node = NODES[i];
      const vec = VECS.get(node.id);
      const p = projectVec(vec[0], vec[1], vec[2], 1.002);
      if (p.z <= 0.02) continue;
      if (!activeTypes.has(node.type)) continue;

      hitNodes.push({ id: node.id, x: p.x, y: p.y, type: node.type });
      entries.push({ node, x: p.x, y: p.y, index: i });
    }

    const active = state.activeId ? entries.find((entry) => entry.node.id === state.activeId) : null;

    // il nodo attivo viene disegnato per ultimo, sopra gli altri
    if (active) {
      const index = entries.indexOf(active);
      entries.splice(index, 1);
      entries.push(active);
    }

    for (let i = 0; i < entries.length; i++) {
      const entry = entries[i];
      const { node, x: sx, y: sy, index } = entry;
      const isActive = node.id === state.activeId;
      const nearActive = active && !isActive && Math.hypot(sx - active.x, sy - active.y) < 30;
      const color = TYPES[node.type].color;

      ctx.globalAlpha = nearActive ? 0.3 : 1;

      const haloR = isActive ? 40 : 25;
      const halo = ctx.createRadialGradient(sx, sy, 0, sx, sy, haloR);
      halo.addColorStop(0, rgba(color, isActive ? 0.24 : 0.11));
      halo.addColorStop(0.55, rgba(color, isActive ? 0.08 : 0.035));
      halo.addColorStop(1, rgba(color, 0));
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(sx, sy, haloR, 0, TAU);
      ctx.fill();

      const phase = (time * 0.42 + index * 0.131) % 1;
      ctx.beginPath();
      ctx.arc(sx, sy, 5 + phase * 19, 0, TAU);
      ctx.lineWidth = 0.8;
      ctx.strokeStyle = rgba(color, (1 - phase) * (isActive ? 0.5 : 0.32));
      ctx.stroke();

      if (isActive) {
        const phase2 = (time * 0.42 + index * 0.131 + 0.5) % 1;
        ctx.beginPath();
        ctx.arc(sx, sy, 5 + phase2 * 23, 0, TAU);
        ctx.strokeStyle = rgba(color, (1 - phase2) * 0.3);
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(sx, sy, isActive ? 4.4 : 2.7, 0, TAU);
      ctx.fillStyle = color;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(sx, sy, 1.05, 0, TAU);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.92)';
      ctx.fill();

      ctx.globalAlpha = 1;

      if (isActive) drawReticle(sx, sy, color, time);
    }

    if (active) drawNodeLabel(active.node, active.x, active.y);
  }

  function drawNodeLabel(node, px, py) {
    const color = TYPES[node.type].color;
    const flip = px > W - 260;
    const bx = px + (flip ? -30 : 30);
    const by = py - 26;

    ctx.save();
    ctx.textBaseline = 'middle';
    ctx.textAlign = flip ? 'right' : 'left';

    ctx.strokeStyle = rgba(color, 0.55);
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(px + (flip ? -10 : 10), py - 7);
    ctx.lineTo(bx, by);
    ctx.stroke();

    ctx.fillStyle = color;
    ctx.fillRect(px - 1.5, py - 1.5, 3, 3);

    const title = node.code;
    ctx.font = '10px "Share Tech Mono", monospace';
    const wTitle = ctx.measureText(title).width;
    ctx.font = '8px "Share Tech Mono", monospace';
    const wSub = ctx.measureText(node.name.toUpperCase()).width;
    const boxW = Math.max(wTitle, wSub) + 14;

    const boxX = flip ? bx - boxW + 7 : bx - 7;
    ctx.fillStyle = 'rgba(3, 8, 6, 0.82)';
    ctx.fillRect(boxX, by - 19, boxW, 37);
    ctx.strokeStyle = rgba(color, 0.34);
    ctx.strokeRect(boxX + 0.5, by - 18.5, boxW - 1, 36);

    ctx.fillStyle = color;
    ctx.font = '10px "Share Tech Mono", monospace';
    ctx.fillText(title, bx, by - 6);

    ctx.fillStyle = 'rgba(202, 218, 208, 0.8)';
    ctx.font = '8px "Share Tech Mono", monospace';
    ctx.fillText(node.name.toUpperCase(), bx, by + 8);

    ctx.restore();
  }

  function render(now) {
    updateTrig();
    drawSpace(now);
    drawAtmosphere();
    drawGlobeBase();

    ctx.save();
    ctx.beginPath();
    ctx.arc(CX, CY, R, 0, TAU);
    ctx.clip();
    drawGraticule();
    drawLand();
    drawShading();
    drawArcs(now);
    ctx.restore();

    drawRim(now);
    drawMarkers(now);
    syncHoverFromPointer();
  }

  function syncHoverFromPointer() {
    if (!pointer.inside || state.pointerDown || state.dragging) return;
    const hit = pick(pointer.x, pointer.y);
    if (hit !== state.hoverId) {
      setHover(hit, 'canvas');
      if (hit) {
        const node = BY_ID.get(hit);
        showTip(node, pointer.x, pointer.y);
      } else {
        hideTip();
      }
    } else if (hit && state.hoverSource === 'canvas') {
      positionTip(pointer.x, pointer.y);
    }
  }

  /* --------------------------------------------------------------- zoom */

  function setZoom(value) {
    state.zoom = clamp(value, 0.62, 2.6);
    const zoomEl = document.getElementById('zoomRead');
    if (zoomEl) zoomEl.textContent = `ZOOM  ${state.zoom.toFixed(2)}×`;
    state.lastInteraction = performance.now();
  }

  /* ----------------------------------------------------------- picking */

  function pick(x, y) {
    let best = null;
    let bestDist = Infinity;
    for (let i = 0; i < hitNodes.length; i++) {
      const h = hitNodes[i];
      const dx = h.x - x;
      const dy = h.y - y;
      const d = dx * dx + dy * dy;
      if (d < bestDist) {
        bestDist = d;
        best = h;
      }
    }
    const coarse = window.matchMedia('(pointer: coarse)').matches;
    const max = coarse ? 32 : 18;
    return best && bestDist <= max * max ? best.id : null;
  }

  /* ---------------------------------------------------------------- UI */

  const ui = {
    dossier: document.getElementById('dossier'),
    filters: document.getElementById('filters'),
    nodeList: document.getElementById('nodeList'),
    nodeCount: document.getElementById('nodeCount'),
    visibleCount: document.getElementById('visibleCount'),
    tip: document.getElementById('mapTip'),
    clock: document.getElementById('clock'),
    satStatus: document.getElementById('satStatus'),
    coordLat: document.getElementById('coordLat'),
    coordLon: document.getElementById('coordLon'),
    zoomRead: document.getElementById('zoomRead'),
    btnNodes: document.getElementById('btnNodes'),
    btnReset: document.getElementById('btnReset'),
    toggleSpin: document.getElementById('toggleSpin'),
    panelNodes: document.getElementById('panelNodes'),
    zoomIn: document.getElementById('zoomIn'),
    zoomOut: document.getElementById('zoomOut'),
    boot: document.getElementById('boot'),
    bootBar: document.getElementById('bootBar'),
    bootPct: document.getElementById('bootPct'),
    tickerTrack: document.getElementById('tickerTrack')
  };

  function countByType(type) {
    return NODES.filter((n) => n.type === type).length;
  }

  function renderFilters() {
    ui.filters.innerHTML = Object.keys(TYPES)
      .map((key) => {
        const type = TYPES[key];
        return `<button class="filter is-on" type="button" data-type="${key}" aria-pressed="true"
          style="--accent:${type.color};--soft:${type.soft}">
          <span class="fdot"></span>${type.label}<b>${countByType(key)}</b>
        </button>`;
      })
      .join('');
  }

  function renderNodeList() {
    ui.nodeList.innerHTML = NODES.map((node) => {
      const type = TYPES[node.type];
      return `<button class="node-row t-${node.type}" type="button" data-id="${node.id}"
        style="--accent:${type.color};--soft:${type.soft}">
        <span class="node-dot" aria-hidden="true"></span>
        <span class="node-txt">
          <span class="node-code">${node.code}</span>
          <span class="node-name">${esc(node.name)}</span>
        </span>
        <span class="node-state">${esc(node.status)}</span>
      </button>`;
    }).join('');
  }

  function renderDefaultDossier() {
    const legend = Object.keys(TYPES)
      .map((key) => {
        const type = TYPES[key];
        return `<div class="legend-row" style="--accent:${type.color};--soft:${type.soft}">
          <span class="legend-dot"></span>
          <span class="legend-txt"><b>${type.label}</b><span>${type.desc}</span></span>
          <em>${countByType(key)}</em>
        </div>`;
      })
      .join('');

    return `<div class="dossier-inner">
      <div class="dossier-accent" style="background:linear-gradient(90deg, var(--green), transparent 82%)"></div>
      <div class="dossier-top">
        <span class="type-tag">BRIEFING</span>
        <span class="dossier-code">PROT. LZ / 041</span>
      </div>
      <h2>Teatro Globale</h2>
      <p class="dossier-place">RETE LAZZARO <span>14 NODI ATTIVI</span></p>
      <p class="desc">Quarantena globale dal Giorno 12. La centrale coordina rifugi e squadre di recupero attraverso una rete di ripetitori. Passa sopra un segnale per aprire il dossier.</p>
      <div class="legend">${legend}</div>
      <div class="intel">
        <div class="intel-head"><span>INTEGRITÀ DELLA RETE</span><b>68%</b></div>
        <div class="intel-meter"><i style="width:68%"></i></div>
        <div class="intel-rows">
          <div><span>RIPETITORI ATTIVI</span><b>11 / 14</b></div>
          <div><span>MESSAGGI NON VERIFICATI</span><b>03</b></div>
          <div><span>PRIORITÀ</span><b>NORA FERRI</b></div>
        </div>
      </div>
      <p class="briefing-note"><b>NOTA OPERATIVA:</b> due trasmissioni della centrale condividono la stessa pausa di 3,0 secondi. La fonte resta non verificata.</p>
      <div class="dossier-foot">
        ${waveBars()}
        <span>◈ SELEZIONA UN NODO SULLA MAPPA</span>
      </div>
    </div>`;
  }

  function renderActiveDossier(node) {
    const type = TYPES[node.type];
    const index = NODES.indexOf(node) + 1;
    const pips = Array.from({ length: 5 }, (_, i) => `<i class="${i < node.threat ? 'on' : ''}"></i>`).join('');
    const tags = (node.tags || []).map((tag) => `<span class="tag">${esc(tag)}</span>`).join('');
    const directives = {
      bunker: 'Mantenere il perimetro. Nessun ingresso senza filtro sanitario e identificazione positiva.',
      outbreak: 'Interdire l\'area. Nessun recupero senza scorta armata e autorizzazione della centrale.',
      signal: 'Registrare la trasmissione. Non rispondere sulla frequenza. Triangolare la sorgente.',
      anomaly: 'Isolare il campione. Segnalare qualsiasi variazione morfologica. Non aprire i sigilli.'
    };

    return `<div class="dossier-inner" style="--accent:${type.color};--soft:${type.soft}">
      <div class="dossier-accent" style="background:linear-gradient(90deg, ${type.color}, transparent 82%)"></div>
      <div class="dossier-top">
        <span class="type-tag">${type.label}</span>
        <div class="dossier-top-right">
          <span class="dossier-code">${node.code} · NODO ${String(index).padStart(2, '0')}</span>
          <button class="dossier-close" type="button" aria-label="Chiudi dossier">×</button>
        </div>
      </div>
      <h2>${esc(node.name)}</h2>
      <p class="dossier-place">${esc(node.place.toUpperCase())} <span>${esc(node.region)}</span></p>
      <div class="coords">${fmtCoord(node.lat, node.lon)}<span>${fmtSigned(node.lat, 2)} / ${fmtSigned(node.lon, 2)}</span></div>
      <div class="signal-state"><i></i>${esc(node.status)}</div>
      <div class="threat">
        <span>MINACCIA</span>
        <span class="pips">${pips}</span>
        <b>${node.threat}/5</b>
      </div>
      <p class="desc">${esc(node.desc)}</p>
      <div class="dossier-grid">
        <div><span>SUPERSTITI</span><b>${esc(node.survivors)}</b></div>
        <div><span>ULTIMO CONTATTO</span><b>${esc(node.contact)}</b></div>
        <div><span>FONTE</span><b>[${esc(node.source)}]</b></div>
        <div><span>AFFIDABILITÀ</span><b>${node.reliability}%</b></div>
      </div>
      <div class="tags">${tags}</div>
      <div class="dossier-directive">
        <span>DIRETTIVA OPERATIVA</span>
        <p>${directives[node.type]}</p>
      </div>
      <div class="dossier-trace">
        <div class="trace-head"><span>TRACCIA SEGNALE</span><b>${node.reliability}%</b></div>
        <div class="trace-bars" aria-hidden="true">${traceBars(node)}</div>
        <div class="trace-foot"><span>FREQ ${(80 + (index * 3.7)).toFixed(1)}</span><span>CH-${String(index).padStart(2, '0')}</span><span>NOISE ${100 - node.reliability}%</span></div>
      </div>
      <div class="dossier-foot">
        ${waveBars()}
        <span>NODO ${String(index).padStart(2, '0')}/${NODES.length} · <b>${type.label}</b></span>
      </div>
    </div>`;
  }

  function refreshActive(force = false) {
    const active = state.hoverId || state.pinnedId || null;
    const changed = active !== state.activeId;
    state.activeId = active;

    if (changed || force) {
      if (active) {
        ui.dossier.innerHTML = renderActiveDossier(BY_ID.get(active));
      } else {
        ui.dossier.innerHTML = renderDefaultDossier();
      }
      updateRowStates(active);
    }

    ui.dossier.classList.toggle('has-active', Boolean(active));
    document.body.classList.toggle('is-hovering-node', Boolean(state.hoverId && state.hoverSource === 'canvas'));
    document.body.classList.toggle('has-selection', Boolean(active));
  }

  function updateRowStates(id) {
    const rows = ui.nodeList.querySelectorAll('.node-row');
    rows.forEach((row) => {
      row.classList.toggle('is-active', row.dataset.id === id);
    });
  }

  function setHover(id, source = 'canvas') {
    if (state.hoverId === id && state.hoverSource === source) return;
    state.hoverId = id;
    state.hoverSource = id ? source : null;
    refreshActive();
    if (id && source === 'canvas') {
      const node = BY_ID.get(id);
      if (node) showTip(node, pointer.x, pointer.y);
    } else if (!id) {
      hideTip();
    }
  }

  function showTip(node, x, y) {
    const type = TYPES[node.type];
    ui.tip.style.setProperty('--accent', type.color);
    ui.tip.style.setProperty('--soft', type.soft);
    ui.tip.innerHTML = `
      <div class="tip-type">${type.label} · ${node.code}</div>
      <div class="tip-name">${esc(node.name)}</div>
      <div class="tip-meta">${esc(node.place)} · <b>${esc(node.status)}</b><br>${fmtCoord(node.lat, node.lon)}</div>`;
    ui.tip.classList.add('is-on');
    ui.tip.setAttribute('aria-hidden', 'false');
    positionTip(x, y);
  }

  function positionTip(x, y) {
    const tw = ui.tip.offsetWidth || 210;
    const th = ui.tip.offsetHeight || 74;
    let left = x + 18;
    let top = y + 16;
    if (left + tw > W - 12) left = x - tw - 18;
    if (top + th > H - 58) top = y - th - 16;
    ui.tip.style.transform = `translate3d(${Math.max(8, left)}px, ${Math.max(8, top)}px, 0)`;
  }

  function hideTip() {
    ui.tip.classList.remove('is-on');
    ui.tip.setAttribute('aria-hidden', 'true');
  }

  function pinNode(id, shouldFocus) {
    state.pinnedId = id;
    refreshActive();
    hideTip();
    if (shouldFocus) focusNode(id);
  }

  function clearPinned() {
    state.pinnedId = null;
    state.hoverId = null;
    state.hoverSource = null;
    refreshActive();
    hideTip();
  }

  function focusNode(id) {
    const node = BY_ID.get(id);
    if (!node) return;
    state.focusTarget = {
      yaw: -node.lon * DEG,
      pitch: clamp(node.lat * DEG, -1.32, 1.32)
    };
    state.lastInteraction = performance.now();
    hideTip();
  }

  function toggleNodesPanel(force) {
    const open = typeof force === 'boolean' ? force : !ui.panelNodes.classList.contains('is-open');
    ui.panelNodes.classList.toggle('is-open', open);
    ui.btnNodes.setAttribute('aria-expanded', String(open));
  }

  function applyFilters() {
    const rows = ui.nodeList.querySelectorAll('.node-row');
    let visible = 0;
    rows.forEach((row) => {
      const node = BY_ID.get(row.dataset.id);
      const show = node && activeTypes.has(node.type);
      row.hidden = !show;
      if (show) visible++;
    });

    ui.visibleCount.textContent = `${visible} / ${NODES.length}`;

    const active = state.activeId ? BY_ID.get(state.activeId) : null;
    const hover = state.hoverId ? BY_ID.get(state.hoverId) : null;
    if (active && !activeTypes.has(active.type)) state.pinnedId = null;
    if (hover && !activeTypes.has(hover.type)) state.hoverId = null;
    refreshActive();
    if (!state.hoverId) hideTip();
  }

  function updateSpinButton() {
    ui.toggleSpin.setAttribute('aria-pressed', String(!state.spin));
    ui.toggleSpin.setAttribute('aria-label', state.spin ? 'Pausa rotazione' : 'Riprendi rotazione');
    ui.toggleSpin.setAttribute('title', state.spin ? 'Pausa rotazione' : 'Riprendi rotazione');
  }

  function resetView() {
    state.yaw = -10 * DEG;
    state.pitch = 20 * DEG;
    state.zoom = 1;
    state.focusTarget = null;
    state.spin = true;
    state.pinnedId = null;
    state.hoverId = null;
    state.hoverSource = null;
    state.lastInteraction = performance.now();
    refreshActive();
    hideTip();
    setZoom(1);
    updateSpinButton();
    toggleNodesPanel(false);
  }

  /* ----------------------------------------------------------- eventi */

  function bindUi() {
    renderFilters();
    renderNodeList();
    ui.dossier.innerHTML = renderDefaultDossier();
    ui.nodeCount.textContent = NODES.length;
    ui.visibleCount.textContent = `${NODES.length} / ${NODES.length}`;
    document.getElementById('statNodes').textContent = NODES.length;
    document.getElementById('statOutbreak').textContent = countByType('outbreak');

    const setMobileCount = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = String(value).padStart(2, '0');
    };
    setMobileCount('mbNodes', NODES.length);
    setMobileCount('mbOutbreak', countByType('outbreak'));
    setMobileCount('mbSignal', countByType('signal'));
    setMobileCount('mbAnomaly', countByType('anomaly'));

    ui.filters.addEventListener('click', (event) => {
      const btn = event.target.closest('.filter');
      if (!btn) return;
      const type = btn.dataset.type;
      if (activeTypes.has(type)) {
        if (activeTypes.size === 1) return;
        activeTypes.delete(type);
      } else {
        activeTypes.add(type);
      }
      const on = activeTypes.has(type);
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', String(on));
      applyFilters();
    });

    ui.nodeList.addEventListener('pointerover', (event) => {
      const row = event.target.closest('.node-row');
      if (!row) return;
      if (event.relatedTarget && row.contains(event.relatedTarget)) return;
      setHover(row.dataset.id, 'list');
      hideTip();
    });

    ui.nodeList.addEventListener('pointerout', (event) => {
      const row = event.target.closest('.node-row');
      if (!row) return;
      if (event.relatedTarget && row.contains(event.relatedTarget)) return;
      if (state.hoverId === row.dataset.id && state.hoverSource === 'list') {
        setHover(null, 'list');
      }
    });

    ui.nodeList.addEventListener('focusin', (event) => {
      const row = event.target.closest('.node-row');
      if (row) {
        setHover(row.dataset.id, 'list');
        hideTip();
      }
    });

    ui.nodeList.addEventListener('focusout', (event) => {
      const row = event.target.closest('.node-row');
      if (row && state.hoverSource === 'list') setHover(null, 'list');
    });

    ui.nodeList.addEventListener('click', (event) => {
      const row = event.target.closest('.node-row');
      if (!row) return;
      pinNode(row.dataset.id, true);
      toggleNodesPanel(false);
    });

    ui.dossier.addEventListener('click', (event) => {
      if (event.target.closest('.dossier-close')) clearPinned();
    });

    ui.btnNodes.addEventListener('click', () => toggleNodesPanel());
    ui.btnReset.addEventListener('click', resetView);

    ui.toggleSpin.addEventListener('click', () => {
      state.spin = !state.spin;
      state.lastInteraction = performance.now();
      updateSpinButton();
    });

    ui.zoomIn.addEventListener('click', () => setZoom(state.zoom * 1.14));
    ui.zoomOut.addEventListener('click', () => setZoom(state.zoom / 1.14));

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        clearPinned();
        toggleNodesPanel(false);
      }
    });
  }

  function bindCanvas() {
    canvas.addEventListener('pointerdown', (event) => {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      pointer.inside = true;
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      state.pointerDown = true;
      state.pointerId = event.pointerId;
      state.moved = false;
      state.dragging = false;
      state.startX = state.lastX = event.clientX;
      state.startY = state.lastY = event.clientY;
      state.focusTarget = null;
      hideTip();

      if (canvas.setPointerCapture) {
        try {
          canvas.setPointerCapture(event.pointerId);
        } catch (_) {}
      }
    });

    canvas.addEventListener('pointermove', (event) => {
      pointer.inside = true;
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      updateReadout(event.clientX, event.clientY);

      if (state.pointerDown && event.pointerId === state.pointerId) {
        const dx = event.clientX - state.lastX;
        const dy = event.clientY - state.lastY;

        if (!state.moved && Math.hypot(event.clientX - state.startX, event.clientY - state.startY) > 4) {
          state.moved = true;
          state.dragging = true;
          document.body.classList.add('is-dragging');
          hideTip();
        }

        if (state.dragging) {
          state.yaw += dx * 0.0044;
          state.pitch = clamp(state.pitch + dy * 0.0044, -1.35, 1.35);
          state.lastInteraction = performance.now();
          state.lastX = event.clientX;
          state.lastY = event.clientY;
        }
        return;
      }

      state.lastInteraction = performance.now();
      const hit = pick(event.clientX, event.clientY);
      if (hit !== state.hoverId || state.hoverSource !== 'canvas') {
        setHover(hit, 'canvas');
        if (hit) {
          const node = BY_ID.get(hit);
          showTip(node, event.clientX, event.clientY);
        } else {
          hideTip();
        }
      } else if (hit) {
        positionTip(event.clientX, event.clientY);
      }
    });

    canvas.addEventListener('pointerup', (event) => {
      if (event.pointerId !== state.pointerId) return;
      if (!state.moved) {
        const hit = pick(event.clientX, event.clientY);
        if (hit) {
          pinNode(hit, event.pointerType !== 'mouse');
        } else {
          clearPinned();
          toggleNodesPanel(false);
        }
      }
      state.pointerDown = false;
      state.dragging = false;
      state.moved = false;
      state.pointerId = null;
      document.body.classList.remove('is-dragging');
      if (canvas.releasePointerCapture) {
        try {
          canvas.releasePointerCapture(event.pointerId);
        } catch (_) {}
      }
    });

    canvas.addEventListener('pointercancel', () => {
      state.pointerDown = false;
      state.dragging = false;
      state.moved = false;
      state.pointerId = null;
      document.body.classList.remove('is-dragging');
    });

    canvas.addEventListener('pointerleave', () => {
      pointer.inside = false;
      if (state.hoverSource === 'canvas') {
        setHover(null, 'canvas');
        hideTip();
      }
      updateReadout(null, null);
    });

    canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0012);
      setZoom(state.zoom * factor);
      state.lastInteraction = performance.now();
    }, { passive: false });
  }

  function updateReadout(x, y) {
    if (x === null || y === null) {
      ui.coordLat.textContent = 'LAT  --';
      ui.coordLon.textContent = 'LON  --';
      return;
    }
    const geo = inverseProject(x, y);
    if (!geo) {
      ui.coordLat.textContent = 'LAT  --';
      ui.coordLon.textContent = 'LON  --';
    } else {
      ui.coordLat.textContent = `LAT  ${fmtSigned(geo.lat, 2)}`;
      ui.coordLon.textContent = `LON  ${fmtSigned(geo.lon, 2)}`;
    }
  }

  /* ------------------------------------------------------- ticker / ora */

  function buildTicker() {
    const half = `<div class="ticker-half">${DATA.ticker
      .map((line) => `<span class="ticker-item">${esc(line)}</span>`)
      .join('')}</div>`;
    ui.tickerTrack.innerHTML = half + half;
  }

  function startClock() {
    const tick = () => {
      const now = new Date();
      ui.clock.textContent = now.toISOString().slice(11, 19);
      ui.clock.title = now.toUTCString();
    };
    tick();
    window.setInterval(tick, 1000);

    const states = ['STABILE', 'STABILE', 'SYNC', 'STABILE', 'RICALIBRA'];
    let i = 0;
    window.setInterval(() => {
      i = (i + 1) % states.length;
      ui.satStatus.textContent = states[i];
      ui.satStatus.style.color = states[i] === 'STABILE' ? '' : 'var(--amber)';
      if (states[i] !== 'STABILE') {
        window.setTimeout(() => {
          ui.satStatus.textContent = 'STABILE';
          ui.satStatus.style.color = '';
        }, 1600);
      }
    }, 9000);
  }

  /* ------------------------------------------------------------- ciclo */

  let lastFrame = performance.now();

  function updateView(now) {
    if (state.focusTarget) {
      const target = state.focusTarget;
      const dt = Math.min(50, now - lastFrame);
      const ease = clamp(dt * 0.0075, 0.04, 0.22);

      let diff = ((target.yaw - state.yaw + Math.PI) % TAU + TAU) % TAU - Math.PI;
      state.yaw += diff * ease;
      state.pitch += (target.pitch - state.pitch) * ease;

      if (Math.abs(diff) < 0.0025 && Math.abs(target.pitch - state.pitch) < 0.0025) {
        state.yaw = target.yaw;
        state.pitch = target.pitch;
        state.focusTarget = null;
      }
      return;
    }

    if (
      state.spin &&
      !state.activeId &&
      !state.dragging &&
      !state.pointerDown &&
      now - state.lastInteraction > 2400 &&
      !prefersReduced
    ) {
      const dt = Math.min(50, now - lastFrame);
      state.yaw += dt * 0.000026;
    }
  }

  function frame(now) {
    updateView(now);
    updateTrig();
    render(now);
    lastFrame = now;
    window.requestAnimationFrame(frame);
  }

  /* --------------------------------------------------------------- boot */

  function bootSequence() {
    let pct = 0;
    let finished = false;

    const finish = () => {
      if (finished) return;
      finished = true;
      state.bootDone = true;
      ui.boot.classList.add('is-done');
      document.body.classList.add('is-ready');
      window.setTimeout(() => {
        if (ui.boot && ui.boot.parentNode) ui.boot.parentNode.removeChild(ui.boot);
      }, 900);
    };

    const timer = window.setInterval(() => {
      pct = Math.min(100, pct + 4 + Math.random() * 7);
      ui.bootBar.style.width = pct.toFixed(0) + '%';
      ui.bootPct.textContent = String(Math.round(pct)).padStart(3, '0') + '%';
      if (pct >= 100) {
        window.clearInterval(timer);
        window.setTimeout(finish, 380);
      }
    }, 65);

    window.setTimeout(finish, 3200);
    ui.boot.addEventListener('click', finish);
    window.addEventListener('keydown', finish, { once: true });
  }

  /* --------------------------------------------------------------- init */

  function init() {
    seedAtmosphere();
    decodeLand();
    layout();
    bindUi();
    bindCanvas();
    buildTicker();
    startClock();
    updateSpinButton();
    window.addEventListener('resize', layout);
    window.addEventListener('orientationchange', layout);
    window.requestAnimationFrame((now) => {
      lastFrame = now;
      frame(now);
    });
    bootSequence();
  }

  init();
})();
