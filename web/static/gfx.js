// Shared helpers for the optional 3D layer. Nothing here imports three.js up front:
// pages call loadThree() only after canUse3D() says yes, and keep their flat view if anything fails.
export const COLORS = {
  navy: 0x0a1424, plate: 0x13253f, edge: 0x2c4a72, grid: 0x1b3152,
  amber: 0xc98500, amberGlow: 0xffb23f,   // electricity / legacy path (validated mark + its glow)
  aqua: 0x159f9f, aquaGlow: 0x5fe6dc,     // water / OneCase
  breach: 0xff5b4f, ink: 0xeef3f8,
};

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// ?flat=1 forces the fallback (for testing); phones and narrow screens get the flat view.
export function canUse3D() {
  if (new URLSearchParams(location.search).has("flat")) return false;
  if (matchMedia("(max-width: 900px)").matches || matchMedia("(pointer: coarse)").matches) return false;
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch { return false; }
}

let threeP;
export const loadThree = () => (threeP ??= import("./vendor/three.module.js"));

// Soft round glow for sprites and trail points (drawn once, no image file).
export function glowTexture(THREE) {
  const s = 128, c = document.createElement("canvas");
  c.width = c.height = s;
  const g = c.getContext("2d"), grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grd.addColorStop(0, "rgba(255,255,255,1)");
  grd.addColorStop(0.25, "rgba(255,255,255,.55)");
  grd.addColorStop(0.6, "rgba(255,255,255,.12)");
  grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd; g.fillRect(0, 0, s, s);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function makeRenderer(THREE, canvasHost) {
  const r = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  r.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  r.outputColorSpace = THREE.SRGBColorSpace;
  canvasHost.appendChild(r.domElement);
  return r;
}

// project a world position to CSS pixels inside the canvas
export function toScreen(v, camera, w, h) {
  const p = v.clone().project(camera);
  return { x: (p.x + 1) / 2 * w, y: (1 - p.y) / 2 * h, visible: p.z < 1 };
}

export const ease = {
  outCubic: t => 1 - (1 - t) ** 3,
  inOutCubic: t => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2),
  inOutSine: t => -(Math.cos(Math.PI * t) - 1) / 2,
};
export const clamp01 = t => Math.max(0, Math.min(1, t));
