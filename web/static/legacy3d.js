// Legacy-vs-OneCase stage for the before/after toggle. Driven by GET /legacy-path/{id}:
// the systems, their order, how each handover loses history, the odds and the days all come from that response.
//   Today lane:   a complaint particle hops system to system; its trail is wiped at every hop that loses history
//                 (re-keyed into CaseTrack, or a nightly batch). A counter climbs to the historical days-to-close for a
//                 transferred case, and the breach flag lights when it passes this case's SLA.
//   OneCase lane: one straight beam from intake to resolution carrying the one case ID.
import { COLORS, loadThree, glowTexture, makeRenderer, toScreen, ease, clamp01, reducedMotion } from "./gfx.js";

let THREE, renderer, glowTex;   // one renderer for the page, reused across mounts (no WebGL context pile-up)

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LANE_TODAY = -1.0, LANE_ONE = 1.45, X0 = -4.1, X1 = 4.1;
const HOP_TIME = 1.0, DWELL = { rekey: 0.45, batch: 0.8, live: 0.3 }, BEAM_TIME = 0.9;

// Fetch and parse three.js ahead of time so the toggle has nothing to load.
export async function warmUp() { THREE ??= await loadThree(); }

export async function mountLegacyStage(host, L, kase, { onFail } = {}) {
  THREE ??= await loadThree();
  const stats = L.stats, days = stats.transferred_days, sla = kase.sla_days;
  const resolved = L.onecase.status === "Resolved";
  const ocText = resolved
    ? `${L.onecase.minutes_to_resolve < 1 ? "&lt; 1 min" : L.onecase.minutes_to_resolve.toFixed(1) + " min"} <span>resolved at first contact</span>`
    : `routed once <span>to ${esc(kase.owning_team)}, no transfer</span>`;
  const lost = L.hops.find(h => h.handoff === "rekey");

  host.innerHTML = `
    <div class="stage-head">
      <div class="lane-key today"><i></i><em>Today</em><b class="st-days">0.0</b><span>days if transferred ·
        ${Math.round(stats.transfer_probability * 100)}% chance from ${esc(L.intake_system)}</span></div>
      <div class="lane-key onecase"><i></i><em>OneCase</em><b class="st-oc">${ocText}</b></div>
      <button type="button" class="st-replay" aria-label="Replay the animation">↻ Replay</button>
    </div>
    <div class="stage-canvas"><div class="stage-labels" aria-hidden="true"></div>
      <strong class="st-breach" role="status">SLA ${sla} days missed · ${Math.round(stats.if_transferred.breach * 100)}% of transferred</strong></div>
    ${lost ? `<p class="stage-cap">“${esc(lost.system_note)}” <span>${esc(lost.system_name)} system note · simulated path, real odds</span></p>` : ""}`;
  const box = host.querySelector(".stage-canvas"), labelsEl = host.querySelector(".stage-labels");
  const daysEl = host.querySelector(".st-days"), breachEl = host.querySelector(".st-breach"), ocEl = host.querySelector(".st-oc");

  // ---- renderer (shared) + scene
  if (!renderer) {
    renderer = makeRenderer(THREE, box);
    glowTex = glowTexture(THREE);
  } else box.prepend(renderer.domElement);
  renderer.setClearColor(COLORS.navy, 1);
  const lostCtx = () => onFail?.("WebGL context lost");
  renderer.domElement.addEventListener("webglcontextlost", lostCtx);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  scene.add(new THREE.HemisphereLight(0xa9c4ff, 0x0a1424, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(3, 7, 5); scene.add(sun);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 30), new THREE.MeshStandardMaterial({ color: 0x0f1d33, roughness: 1 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.1; scene.add(floor);
  const grid = new THREE.GridHelper(60, 120, COLORS.grid, 0x12213a);
  grid.material.transparent = true; grid.material.opacity = 0.55; grid.position.y = -0.09; scene.add(grid);

  const puckGeo = new THREE.CylinderGeometry(0.42, 0.46, 0.3, 48);
  const rimGeo = new THREE.TorusGeometry(0.43, 0.04, 10, 64);
  const bodyMat = new THREE.MeshStandardMaterial({ color: 0x2b4a78, roughness: 0.45, metalness: 0.2, emissive: 0x0d1c33 });
  function puck(x, z, rimColor) {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(puckGeo, bodyMat));
    const rim = new THREE.Mesh(rimGeo, new THREE.MeshBasicMaterial({ color: rimColor }));
    rim.rotation.x = Math.PI / 2; rim.position.y = 0.15; g.add(rim);
    g.position.set(x, 0.05, z); scene.add(g);
    return { g, rim };
  }
  function glow(color, scale, opacity = 1) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, blending: THREE.AdditiveBlending,
      transparent: true, depthWrite: false, opacity }));
    s.scale.setScalar(scale); scene.add(s);
    return s;
  }
  function bar(x0, x1, z, color, h = 0.02, d = 0.07) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(Math.max(0.01, x1 - x0), h, d), new THREE.MeshBasicMaterial({ color }));
    m.position.set((x0 + x1) / 2, -0.05, z); scene.add(m);
    return m;
  }

  // ---- Today lane: one puck per system in the response
  const n = L.hops.length, xs = L.hops.map((_, i) => X0 + (X1 - X0) * (n === 1 ? 0.5 : i / (n - 1)));
  const nodes = xs.map(x => puck(x, LANE_TODAY, 0x3a5a85));
  for (let i = 1; i < n; i++) {
    const a = xs[i - 1] + 0.5, b = xs[i] - 0.5, h = L.hops[i].handoff;
    if (h === "rekey") { const m = (a + b) / 2; bar(a, m - 0.18, LANE_TODAY, 0x8a2f2b); bar(m + 0.18, b, LANE_TODAY, 0x8a2f2b); }
    else if (h === "batch") { for (let x = a; x < b - 0.05; x += 0.28) bar(x, Math.min(x + 0.14, b), LANE_TODAY, 0x35557f); }
    else bar(a, b, LANE_TODAY, 0x2f6f9a);
  }
  const particle = glow(COLORS.amberGlow, 0.95);
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.1, 20, 12), new THREE.MeshBasicMaterial({ color: 0xffe2b0 }));
  scene.add(core);

  // trail: glowing points; a hop that loses history wipes everything behind it
  const MAX = 900, tPos = new Float32Array(MAX * 3), tCol = new Float32Array(MAX * 3), tSeg = new Int16Array(MAX);
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute("position", new THREE.BufferAttribute(tPos, 3));
  trailGeo.setAttribute("color", new THREE.BufferAttribute(tCol, 3));
  const trail = new THREE.Points(trailGeo, new THREE.PointsMaterial({ size: 0.34, map: glowTex, vertexColors: true,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  trail.frustumCulled = false; scene.add(trail);

  // ---- OneCase lane
  const intake = puck(X0, LANE_ONE, COLORS.aqua), done = puck(X1, LANE_ONE, 0x3a5a85);
  bar(X0 + 0.5, X1 - 0.5, LANE_ONE, 0x163a4a, 0.012, 0.05);
  const beam = new THREE.Mesh(new THREE.BoxGeometry(1, 0.05, 0.09), new THREE.MeshBasicMaterial({ color: COLORS.aquaGlow }));
  beam.geometry.translate(0.5, 0, 0); beam.position.set(X0 + 0.45, 0.02, LANE_ONE); beam.scale.x = 0.0001; scene.add(beam);
  const beamGlow = glow(COLORS.aqua, 1, 0.9);
  const comet = glow(COLORS.aquaGlow, 0.9);

  // ---- DOM labels anchored to world points
  const labels = [];
  const label = (html, x, y, z, cls = "") => {
    const el = document.createElement("div");
    el.className = "l3d " + cls; el.innerHTML = html; labelsEl.appendChild(el);
    labels.push({ el, v: new THREE.Vector3(x, y, z) });
    return el;
  };
  L.hops.forEach((h, i) => label(`<span>${esc(h.system_id)}</span>${esc(h.system_name)}`, xs[i], 0, LANE_TODAY + 0.62, "node"));
  for (let i = 1; i < n; i++) {
    const h = L.hops[i].handoff, mx = (xs[i - 1] + xs[i]) / 2;
    if (h === "rekey") label("✂ history lost", mx, 1.3, LANE_TODAY, "cut");
    if (h === "batch") label("next-day batch", mx, 1.3, LANE_TODAY, "batch");
  }
  label(`<span>${esc(kase.channel)}</span>Intake`, X0, 0, LANE_ONE + 0.62, "node");
  const doneLabel = label(`<span>${esc(kase.owning_team)}</span>${resolved ? "Resolved" : "Owning team"}`, X1, 0, LANE_ONE + 0.62, "node");
  const idLabel = label(`${esc(L.case_id)} · one case, no transfer`, 0, 0, LANE_ONE - 0.62, "caseid");

  // ---- timeline (built from the hops)
  const plan = [];
  let t = 0.35;
  for (let i = 1; i < n; i++) {
    plan.push({ from: i - 1, to: i, start: t, land: t + HOP_TIME, handoff: L.hops[i].handoff });
    t += HOP_TIME + DWELL[L.hops[i].handoff];
  }
  const legacyEnd = t, beamStart = legacyEnd + 0.2, beamEnd = beamStart + BEAM_TIME, total = beamEnd + 0.6;
  let count = 0, breached = false;
  const segLost = new Float32Array(Math.max(1, n)).fill(Infinity);   // when each hop's trail was wiped
  const amber = new THREE.Color(COLORS.amberGlow), cpos = new THREE.Vector3();

  function update(time) {
    // particle position
    let seg = -1, landedAt = 0;
    cpos.set(xs[0], 0.22, LANE_TODAY);
    for (const [k, p] of plan.entries()) {
      if (time < p.start) break;
      seg = k;
      if (time < p.land) {
        const u = ease.inOutSine((time - p.start) / HOP_TIME);
        cpos.set(xs[p.from] + (xs[p.to] - xs[p.from]) * u, 0.26 + 0.85 * 4 * u * (1 - u), LANE_TODAY);
        landedAt = -1;
      } else {
        const since = time - p.land;          // small decaying bounce on landing
        cpos.set(xs[p.to], 0.22 + 0.22 * Math.abs(Math.sin(since * 9)) * Math.exp(-since * 5), LANE_TODAY);
        landedAt = p.land;
        if (p.handoff !== "live") for (let j = 0; j <= k; j++) segLost[j] = Math.min(segLost[j], p.land);
        nodes[p.to].rim.material.color.setHex(time - p.land < 0.35 ? COLORS.amberGlow : COLORS.amber);
      }
    }
    if (time > 0.05) nodes[0].rim.material.color.setHex(COLORS.amber);
    particle.position.copy(cpos); core.position.copy(cpos);
    particle.scale.setScalar(0.9 + 0.08 * Math.sin(time * 7));

    // trail: record while moving
    if (landedAt === -1) {
      const px = count ? tPos[(count - 1) * 3] : cpos.x, py = count ? tPos[(count - 1) * 3 + 1] : cpos.y;
      const steps = Math.min(12, Math.max(1, Math.ceil(Math.hypot(cpos.x - px, cpos.y - py) / 0.04)));
      for (let k = 1; k <= steps && count < MAX; k++, count++) {   // fill gaps so a slow frame never leaves dots
        const u = count ? k / steps : 1;
        tPos.set([px + (cpos.x - px) * u, py + (cpos.y - py) * u, cpos.z], count * 3); tSeg[count] = seg;
      }
      trailGeo.setDrawRange(0, count);
    }
    for (let i = 0; i < count; i++) {
      const f = 1 - clamp01((time - segLost[Math.max(0, tSeg[i])]) / 0.45);
      tCol[i * 3] = amber.r * f * 0.9; tCol[i * 3 + 1] = amber.g * f * 0.9; tCol[i * 3 + 2] = amber.b * f * 0.9;
    }
    trailGeo.attributes.position.needsUpdate = true; trailGeo.attributes.color.needsUpdate = true;

    // counter + breach
    const d = days * clamp01((time - 0.2) / (legacyEnd - 0.2));
    daysEl.textContent = d.toFixed(1);
    if (!breached && d >= sla) { breached = true; breachEl.classList.add("on"); }

    // OneCase beam
    const b = ease.outCubic(clamp01((time - beamStart) / BEAM_TIME)), len = (X1 - X0 - 0.9) * b;
    beam.scale.x = Math.max(0.0001, len);
    beamGlow.position.set(X0 + 0.45 + len / 2, 0.05, LANE_ONE); beamGlow.scale.set(Math.max(0.01, len * 1.08), 0.55, 1);
    beamGlow.material.opacity = b > 0 ? 0.75 : 0;
    comet.position.set(X0 + 0.45 + len, 0.08, LANE_ONE); comet.material.opacity = b > 0 && b < 1 ? 1 : 0;
    const arrived = time >= beamEnd;
    done.rim.material.color.setHex(arrived ? COLORS.aquaGlow : 0x3a5a85);
    doneLabel.classList.toggle("on", arrived); idLabel.classList.toggle("on", b > 0.4); ocEl.classList.toggle("on", arrived);
  }

  // ---- layout: fit the camera so every lane and label is on screen at any width
  let W = 1, H = 1;
  function layout() {
    W = box.clientWidth; H = box.clientHeight;
    if (!W || !H) return;
    renderer.setSize(W, H);
    camera.aspect = W / H;
    const tan = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const dist = Math.max(5.4 / (tan * camera.aspect), 2.5 / tan);
    const elev = THREE.MathUtils.degToRad(40), target = new THREE.Vector3(0, 0.5, 0.3);   // leaves a band at the top for the breach flag
    camera.position.set(0, target.y + dist * Math.sin(elev), target.z + dist * Math.cos(elev));
    camera.lookAt(target); camera.updateProjectionMatrix();
    placeLabels();
  }
  function placeLabels() {
    for (const { el, v } of labels) {
      const p = toScreen(v, camera, W, H);
      el.style.transform = `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px) translate(-50%, 0)`;
    }
  }

  // ---- loop: runs only while animating, stops itself, restarts on replay
  let raf = 0, t0 = 0, alive = true;
  const frame = now => {
    if (!alive) return;
    const time = Math.max(0, (now - t0) / 1000);
    update(Math.min(time, total));
    renderer.render(scene, camera);
    raf = time < total ? requestAnimationFrame(frame) : 0;
  };
  function reset() {
    count = 0; breached = false; breachEl.classList.remove("on"); ocEl.classList.remove("on"); segLost.fill(Infinity);
    trailGeo.setDrawRange(0, 0);
    nodes.forEach(nd => nd.rim.material.color.setHex(0x3a5a85));
  }
  function play() {
    cancelAnimationFrame(raf); reset();
    update(0); renderer.compile(scene, camera); renderer.render(scene, camera);   // compile shaders before the clock starts
    if (reducedMotion()) {           // no motion: build the end state and draw it once
      for (let s = 0; s <= total; s += 1 / 30) update(s);
      update(total); renderer.render(scene, camera); return;
    }
    t0 = performance.now(); raf = requestAnimationFrame(frame);
  }
  const ro = new ResizeObserver(() => { layout(); if (!raf) renderer.render(scene, camera); });
  ro.observe(box);
  host.querySelector(".st-replay").addEventListener("click", play);
  layout(); play();

  return {
    replay: play,
    dispose() {
      alive = false; cancelAnimationFrame(raf); ro.disconnect();
      renderer.domElement.removeEventListener("webglcontextlost", lostCtx);
      scene.traverse(o => {
        o.geometry?.dispose();
        if (o.material) [].concat(o.material).forEach(m => m.dispose());
      });
      renderer.domElement.remove();
    },
  };
}
