// Körperkarte 3D: Z-Anatomy (CC BY-SA 4.0, auf Basis von BodyParts3D © DBCLS) mit three.js (MIT)
// mount(el, {onPick(part, point, joint), markers}) → {parts, relations, view, focus, setSel, setLayer, setMuscleOpacity, setLabels, setMarkers, dispose}
import * as THREE from "../vendor/three/three.module.min.js";
import { GLTFLoader } from "../vendor/three/GLTFLoader.js";
import { OrbitControls } from "../vendor/three/OrbitControls.js";
import { MeshoptDecoder } from "../vendor/three/meshopt_decoder.module.js";

// Farben klar getrennt: Knochen elfenbein, Knorpel hellblau, Bänder grün, Sehnen silbern (glänzend); Auswahl orange, Zusammengehöriges violett
const COL = { skin: 0xe9c2a6, bone: 0xeee3cc, muscle: 0xb5483f, cartilage: 0x8fc3e3, ligament: 0x5fae94, tendon: 0xc9d6ea, insertion: 0xf0d27a, fascia: 0xdfe6ee };
const SEL = new THREE.Color(0xffb020), REL = new THREE.Color(0x7c5cff);
const tint = (c, p, out) => { const h = ((p * 2654435761) >>> 0) / 4294967296; return out.copy(c).multiplyScalar(0.86 + h * 0.26); };
// Ansichten für Schlüsselbeinhöhe 1,336 m angelegt; Höhen werden ans geladene Modell angepasst
const VIEWS = { ganz: [0, 0.85, 3.1, 0, 0.82, 0], vorn: [0, 0.85, 3.1, 0, 0.82, 0], hinten: [0, 0.85, -3.1, 0, 0.82, 0], links: [3.1, 0.85, 0, 0, 0.82, 0], rechts: [-3.1, 0.85, 0, 0, 0.82, 0], seite: [-3.1, 0.85, 0.15, 0, 0.82, 0],
  schulter: [-0.3, 1.42, 0.75, -0.06, 1.3, 0.05], brust: [0, 1.32, 0.8, 0, 1.25, 0.08], nacken: [0, 1.48, -0.75, 0, 1.4, 0], ruecken: [0, 1.15, -1.45, 0, 1.12, 0],
  becken: [0, 0.9, 1.3, 0, 0.85, 0], knie: [-0.2, 0.45, 0.95, 0, 0.38, 0.05] };

export async function mount(el, opt = {}) {
  const parts = await (await fetch(new URL("./parts.json", import.meta.url))).json();
  const W = () => el.clientWidth, H = () => el.clientHeight;
  let dirty = true; // neu zeichnen nötig
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio)); renderer.setSize(W(), H());
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(35, W() / H(), 0.02, 20);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6)); const dl = new THREE.DirectionalLight(0xffffff, 1.4); dl.position.set(1, 2, 2); cam.add(dl); scene.add(cam);
  // Steuerung: ruhiger Zoom zum Finger hin, Verschieben in Bildschirmebene
  const ctl = new OrbitControls(cam, renderer.domElement);
  ctl.addEventListener("change", () => { dirty = true; });
  renderer.domElement.addEventListener("webglcontextrestored", () => { dirty = true; });
  Object.assign(ctl, { enableDamping: true, dampingFactor: 0.15, rotateSpeed: 0.65, zoomSpeed: 0.55, panSpeed: 0.8, screenSpacePanning: true, zoomToCursor: true, minDistance: 0.12, maxDistance: 4.5 });
  const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(new URL("./body.glb", import.meta.url).href);
  const layers = {}, labelsEl = document.createElement("div"); labelsEl.className = "b3labels"; el.appendChild(labelsEl);
  gltf.scene.traverse(o => { if (!o.isMesh) return; const name = o.name || o.parent?.name, g = o.geometry; g.computeVertexNormals();
    const pa = g.getAttribute("_part"), n = g.getAttribute("position").count, col = new Float32Array(n * 3), c = new THREE.Color(COL[name] ?? 0xcccccc), t = new THREE.Color();
    // Muskeln: jedes Teil leicht anders getönt, damit die Grenzen zwischen Muskeln sichtbar sind
    for (let i = 0; i < n; i++) (name === "muscle" ? tint(c, Math.round(pa.getX(i)), t) : c).toArray(col, i * 3);
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    const see = name === "skin" || name === "fascia";
    // Haut/Faszien halbdurchsichtig, aber mit Tiefenpuffer: überlappende Regionen dunkeln sich nicht gegenseitig ab (vorher dunkle Flecken)
    o.material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: name === "tendon" ? .38 : name === "cartilage" ? .5 : .75, metalness: name === "tendon" ? .25 : 0, transparent: see, opacity: name === "skin" ? .22 : name === "fascia" ? .4 : 1, depthWrite: true, side: see ? THREE.FrontSide : THREE.DoubleSide });
    o.renderOrder = name === "skin" ? 3 : name === "fascia" ? 2 : 1; if (name === "fascia" || name === "insertion") o.visible = false;
    layers[name] = { mesh: o, pa, base: c };
  });
  scene.add(gltf.scene);
  // Ecken je Teil (die Kompression ordnet Ecken um)
  const range = {}; for (const [ln, L] of Object.entries(layers)) { const tmp = {}; for (let i = 0; i < L.pa.count; i++) { const p = Math.round(L.pa.getX(i)); (tmp[p] || (tmp[p] = [])).push(i); } for (const p in tmp) range[p] = { ln, v: Uint32Array.from(tmp[p]) }; }
  for (const p of parts) if (/epicranial aponeurosis/i.test(p.en) && range[p.i]) { const r = range[p.i], pos = layers[r.ln].mesh.geometry.getAttribute("position"), x = pos.getX(r.v[0]), y = pos.getY(r.v[0]), z = pos.getZ(r.v[0]); for (const i of r.v) pos.setXYZ(i, x, y, z); pos.needsUpdate = true; }
  const tmpC = new THREE.Color();
  function paint(p, color) { const r = range[p]; if (!r) return; const L = layers[r.ln], col = L.mesh.geometry.getAttribute("color"), c = color || (r.ln === "muscle" ? tint(L.base, +p, tmpC) : L.base); for (const i of r.v) c.toArray(col.array, i * 3); col.needsUpdate = true; }
  // Nähe im Modell (Weltkoordinaten in Metern): welche Teile berühren ein Teil? Für Sehnen/Bänder/Schleimbeutel, die Z-Anatomy nicht mit Muskeln verknüpft
  const lv = {};
  function layerVerts(ln){ if (lv[ln]) return lv[ln]; const L = layers[ln]; if (!L) return null; const m = L.mesh, pos = m.geometry.getAttribute("position"), n = pos.count, xyz = new Float32Array(n * 3), ids = new Int32Array(n), v = new THREE.Vector3(); m.updateMatrixWorld();
    for (let i = 0; i < n; i++) { v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld); xyz[i * 3] = v.x; xyz[i * 3 + 1] = v.y; xyz[i * 3 + 2] = v.z; ids[i] = Math.round(L.pa.getX(i)); } return lv[ln] = { xyz, ids }; }
  function partPts(i, max){ const r = range[i]; if (!r) return null; const { xyz } = layerVerts(r.ln), step = Math.max(1, Math.floor(r.v.length / max)), P = [], bb = [1e9, 1e9, 1e9, -1e9, -1e9, -1e9];
    for (let k = 0; k < r.v.length; k += step) { const j = r.v[k] * 3; for (let a = 0; a < 3; a++) { const x = xyz[j + a]; P.push(x); if (x < bb[a]) bb[a] = x; if (x > bb[a + 3]) bb[a + 3] = x; } } return { P, bb }; }
  function nearParts(i, lns, d, max = 250){ const S = partPts(i, max); if (!S) return []; const { P, bb } = S, d2 = d * d, best = new Map();
    for (const ln of lns) { const L = layerVerts(ln); if (!L) continue; const { xyz, ids } = L, n = ids.length;
      for (let q = 0; q < n; q++) { const x = xyz[q * 3], y = xyz[q * 3 + 1], z = xyz[q * 3 + 2], p = ids[q]; if (p === i || x < bb[0] - d || x > bb[3] + d || y < bb[1] - d || y > bb[4] + d || z < bb[2] - d || z > bb[5] + d) continue;
        for (let k = 0; k < P.length; k += 3) { const dx = x - P[k], dy = y - P[k + 1], dz = z - P[k + 2], s = dx * dx + dy * dy + dz * dz; if (s < d2) { const o = best.get(p); if (o === undefined || s < o) best.set(p, s); break; } } } }
    return [...best].sort((a, b) => a[1] - b[1]).map(x => x[0]); }
  let sel = [], rel = [];
  function setSel(s = [], r = []) { for (const p of [...sel, ...rel]) paint(p); sel = [...s]; rel = r.filter(p => !sel.includes(p)); for (const p of rel) paint(p, REL); for (const p of sel) paint(p, SEL); dirty = true; }
  // Gelenke ohne eigenes Teil am Schlüsselbein: SC (innen) und AC (außen)
  const joints = [];
  for (const [en, side] of [["Clavicle.r", "rechts"], ["Clavicle.l", "links"]]) { const p = parts.find(x => x.en === en), r = p && range[p.i]; if (!r) continue;
    const m = layers[r.ln].mesh, pos = m.geometry.getAttribute("position"), v = new THREE.Vector3(); m.updateMatrixWorld(); let lo = null, hi = null;
    for (const i of r.v) { v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld); const ax = Math.abs(v.x); if (!lo || ax < lo.ax) lo = { ax, p: v.toArray() }; if (!hi || ax > hi.ax) hi = { ax, p: v.toArray() }; }
    joints.push({ name: `SC-Gelenk ${side}`, pt: lo.p }, { name: `AC-Gelenk ${side}`, pt: hi.p }); }
  const jointAt = pt => { let best = null; for (const j of joints) { const d = Math.hypot(pt[0] - j.pt[0], pt[1] - j.pt[1], pt[2] - j.pt[2]); if (d < 0.035 && (!best || d < best.d)) best = { ...j, d }; } return best?.name || null; };
  // Zusammengehöriges: Gruppe, Teile desselben Muskels, Ursprung/Ansatz mit Knochen, Muskeln am Knochen
  const byGrp = {}, byBase = {}, byOn = {}, byEn = {}, key = (b, s) => b + "|" + (s || "");
  for (const p of parts) { byEn[p.en] = p; if (p.grp) (byGrp[p.grp] || (byGrp[p.grp] = [])).push(p); if (p.base) (byBase[key(p.base, p.side)] || (byBase[key(p.base, p.side)] = [])).push(p); if (p.on) (byOn[p.on] || (byOn[p.on] = [])).push(p); }
  const sameSide = (a, b) => !a.side || !b.side || a.side === b.side;
  const relCache = new Map(), SOFT = /bursa/i;
  function relations(i) { if (!relCache.has(i)) relCache.set(i, relations0(i)); return relCache.get(i); }
  function relations0(i) {
    const p = parts[i], out = [], add = (title, list) => { const ids = [...new Set(list.filter(x => x && x.i !== i).map(x => x.i))]; if (!ids.length) return; const o = out.find(g => g.title === title); if (o) o.ids = [...new Set([...o.ids, ...ids])]; else out.push({ title, ids }); };
    const near = (lns, d, max) => nearParts(i, lns, d, max).map(j => parts[j]);
    // Bänder, Sehnen, Knorpel, Schleimbeutel: woran sie liegen (Knochen, Muskeln) und was am selben Gelenk sitzt
    if (["tendon", "ligament", "cartilage"].includes(p.layer)) {
      if (p.grp) add(p.grpDe, (byGrp[p.grp] || []).filter(x => sameSide(x, p)));
      add(p.layer === "tendon" ? "Muskeln daran" : "Muskeln in der Nähe", near(["muscle"], 0.012).slice(0, 12));
      add(SOFT.test(p.en) ? "Liegt an Knochen" : "Verbindet Knochen", near(["bone"], 0.01).slice(0, 6));
      add("Bänder, Sehnen & Knorpel daneben", near(["ligament", "tendon", "cartilage"], 0.006).slice(0, 12));
      return out; }
    if (p.kind) { // Ursprung/Ansatz → Muskel und Knochen
      add("Muskel", (byBase[key(p.base, p.side)] || []).filter(x => !x.kind));
      add("Knochen", [byEn[p.on]]);
      add("Weitere Ansätze dieses Muskels", (byBase[key(p.base, p.side)] || []).filter(x => x.kind));
      return out; }
    if (p.layer === "bone") { const ins = byOn[p.en] || [];
      add("Muskeln an diesem Knochen", ins.flatMap(x => (byBase[key(x.base, x.side)] || []).filter(y => !y.kind)));
      add("Ansatzflächen am Knochen", ins);
      add("Bänder, Knorpel & Sehnen am Knochen", near(["ligament", "cartilage", "tendon"], 0.005, 700).slice(0, 24)); return out; }
    const g = byGrp[p.grp] || [], isMuscleGrp = /muscle$/i.test(p.grp || "");
    if (isMuscleGrp) add(`Teile: ${p.grpDe}`, g.filter(x => sameSide(x, p)));
    else if (p.grp) add(p.grpDe, g.filter(x => sameSide(x, p)));
    // übergeordnete Gruppe mit allen Untergruppen (z. B. Schultermuskeln = Deltamuskel + Rotatorenmanschette + großer Rundmuskel)
    if (p.grp2) add(p.grp2De, parts.filter(x => !x.kind && (x.grp === p.grp2 || x.grp2 === p.grp2) && x.grp !== p.grp && sameSide(x, p)));
    // Ursprung/Ansatz: zum Teil selbst, sonst zum ganzen Muskel (Köpfe teilen sich oft die Flächen)
    const keys = [p.base, isMuscleGrp ? p.grp : null].filter(Boolean), ins = keys.flatMap(k => (byBase[key(k, p.side)] || []).filter(x => x.kind));
    add("Ursprung & Ansatz", ins);
    add("Knochen, an denen er ansetzt", ins.map(x => byEn[x.on]));
    if (p.layer === "muscle") add("Sehnen, Bänder & Schleimbeutel daran", near(["tendon", "ligament"], 0.008).slice(0, 16));
    return out; }
  // Markierungen (Schmerzpunkte)
  const mk = new THREE.Group(); scene.add(mk);
  const mkGeo = new THREE.SphereGeometry(1, 16, 12), mkMat = new Map();
  const matFor = (n, old) => { const k = n + "|" + (old ? 1 : 0); if (!mkMat.has(k)) mkMat.set(k, new THREE.MeshBasicMaterial({ color: new THREE.Color().setHSL((1 - n / 10) * .33, .9, .5), transparent: true, opacity: old ? .35 : .95, depthTest: false })); return mkMat.get(k); };
  // Punkte aus älteren Modellständen auf die Oberfläche setzen: nächste Ecke des gespeicherten Körperteils, sonst des ganzen Modells (max. 15 cm)
  const snapMemo = new Map();
  function snap(pt, en){ const key = pt.join(",") + "|" + (en || ""); if (snapMemo.has(key)) return snapMemo.get(key);
    const p = en && byEn[en], r = p && range[p.i], cand = r ? [[r.ln, r.v]] : ["muscle", "bone", "cartilage", "skin"].filter(l => layers[l]).map(l => [l, null]);
    let best = null, bd = Infinity;
    for (const [ln, idx] of cand) { const L = layerVerts(ln); if (!L) continue; const xyz = L.xyz, n = idx ? idx.length : xyz.length / 3;
      for (let q = 0; q < n; q++) { const j = (idx ? idx[q] : q) * 3, dx = xyz[j] - pt[0], dy = xyz[j + 1] - pt[1], dz = xyz[j + 2] - pt[2], d = dx * dx + dy * dy + dz * dz; if (d < bd) { bd = d; best = [xyz[j], xyz[j + 1], xyz[j + 2]]; } } }
    const dist = Math.sqrt(bd), out = best && dist > 0.004 && dist < 0.15 ? best : pt; snapMemo.set(key, out); return out; }
  function setMarkers(list = []) { mk.clear(); for (const m of list) { if (!m.pt) continue; const n = Math.max(0, Math.min(10, m.n || 0)), s = new THREE.Mesh(mkGeo, matFor(n, m.old)), at = snap(m.pt, m.part);
    s.scale.setScalar(.01 + .0015 * n); s.position.fromArray(at); s.renderOrder = 5; s.userData = m; mk.add(s); } dirty = true; }
  setMarkers(opt.markers || []);
  // Beschriftung
  let labelMode = "auto", lastLbl = "";
  const big = parts.filter(p => p.layer !== "skin" && p.g).map(p => p.i);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function labels() { const out = [], placed = [], v = new THREE.Vector3();
    const scr = pos => { v.fromArray(pos).project(cam); return v.z > 1 || Math.abs(v.x) > 1.02 || Math.abs(v.y) > 1.02 ? null : [(v.x + 1) / 2 * W(), (1 - v.y) / 2 * H()]; };
    const push = (pos, txt, cls, force) => { const s = scr(pos); if (!s) return; if (!force && placed.some(([x, y]) => Math.abs(x - s[0]) < 80 && Math.abs(y - s[1]) < 17)) return; placed.push(s); out.push(`<span class="${cls}" style="left:${s[0]}px;top:${s[1]}px">${txt}</span>`); };
    const vis = ln => layers[ln]?.mesh.visible, mOpaque = vis("muscle") && layers.muscle.mesh.material.opacity >= 1;
    for (const s of mk.children) if (s.userData.label) push(s.position.toArray(), esc(s.userData.label), "lb pain", true);
    if (labelMode !== "off") { for (const p of sel) push(parts[p].c, esc(parts[p].de), "lb sel", true); for (const p of rel.slice(0, 12)) push(parts[p].c, esc(parts[p].de), "lb rel"); }
    if (labelMode === "all") { const camDir = new THREE.Vector3(); cam.getWorldDirection(camDir);
      const cand = big.filter(i => { const p = parts[i]; if (!vis(p.layer) || (mOpaque && (p.layer === "bone" || p.layer === "cartilage" || p.layer === "insertion")) || /disc/i.test(p.en)) return false; const d = new THREE.Vector3().fromArray(p.c).sub(cam.position);
          const side = new THREE.Vector3(p.c[0], 0, p.c[2] - 0.03).dot(new THREE.Vector3(camDir.x, 0, camDir.z).normalize()); return d.dot(camDir) > 0 && d.length() < 2.6 && side < -0.03; })
        .map(i => [i, scr(parts[i].c)]).filter(x => x[1]).sort((a, b) => Math.hypot(a[1][0] - W() / 2, a[1][1] - H() / 2) - Math.hypot(b[1][0] - W() / 2, b[1][1] - H() / 2));
      for (const [i] of cand) { if (out.length > 22) break; push(parts[i].c, esc(parts[i].de.split(" · ")[0]), "lb"); } }
    const html = out.join(""); if (html !== lastLbl) { lastLbl = html; labelsEl.innerHTML = html; } }
  // Kamera: Ansichten, sanftes Hinfahren zur angetippten Stelle (wird Drehmitte → Zoomen trifft das Ziel)
  const ky = (parts.find(p => p.en === "Clavicle.r")?.c[1] || 1.336) / 1.336;
  let anim = null;
  function fly(toPos, toTgt, ms = 350) { anim = { t0: performance.now(), ms, p0: cam.position.clone(), t0v: ctl.target.clone(), p1: new THREE.Vector3(...toPos), t1: new THREE.Vector3(...toTgt) }; }
  function view(name) { const v = VIEWS[name]; if (!v) return; fly([v[0], v[1] * ky, v[2]], [v[3], v[4] * ky, v[5]]); }
  function focus(pt, dist) { const t = new THREE.Vector3(...pt), off = cam.position.clone().sub(ctl.target); const d = dist ?? Math.min(off.length(), 0.9); off.setLength(Math.max(0.25, d)); fly(t.clone().add(off).toArray(), t.toArray(), 300); }
  { const v = VIEWS[opt.view || "vorn"]; cam.position.set(v[0], v[1] * ky, v[2]); ctl.target.set(v[3], v[4] * ky, v[5]); ctl.update(); }
  // Antippen: Teil bestimmen (Ziehen zum Drehen ist kein Antippen); durch Haut, Faszien und Halshautmuskel hindurch
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(); let down = null, ptrs = 0, multiT = false;
  renderer.domElement.addEventListener("pointerdown", e => { if (e.isPrimary) ptrs = 0; ptrs++; if (ptrs > 1) multiT = true; else { multiT = false; down = [e.clientX, e.clientY, Date.now()]; } anim = null; });
  renderer.domElement.addEventListener("pointercancel", () => { ptrs = Math.max(0, ptrs - 1); });
  renderer.domElement.addEventListener("pointerup", e => { ptrs = Math.max(0, ptrs - 1); if (multiT) { if (!ptrs) { multiT = false; down = null; } return; } if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 8 || Date.now() - down[2] > 600) return; const rc = renderer.domElement.getBoundingClientRect();
    ndc.set((e.clientX - rc.left) / rc.width * 2 - 1, -((e.clientY - rc.top) / rc.height) * 2 + 1); ray.setFromCamera(ndc, cam);
    const meshes = ["muscle", "tendon", "ligament", "insertion", "cartilage", "bone", "fascia", "skin"].map(l => layers[l]?.mesh).filter(m => m && m.visible);
    const hits = ray.intersectObjects(meshes, false), partOf = x => Object.values(layers).find(l => l.mesh === x.object).pa.getX(x.face.a);
    const thin = x => x.object === layers.skin?.mesh || x.object === layers.fascia?.mesh || /platysma/i.test(parts[Math.round(partOf(x))].en), h0 = hits[0];
    const hit = h0 && thin(h0) ? hits.find(x => !thin(x) && x.distance - h0.distance < 0.08) || h0 : h0;
    if (!hit) { opt.onPick?.(null); return; }
    const p = Math.round(partOf(hit)), pt = hit.point.toArray().map(x => +x.toFixed(4)); opt.onPick?.(parts[p], pt, jointAt(pt)); });
  let alive = true; const ro = new ResizeObserver(() => { if (!W() || !H()) return; renderer.setSize(W(), H()); cam.aspect = W() / H(); cam.updateProjectionMatrix(); dirty = true; }); ro.observe(el);
  // nur zeichnen, wenn sich Kamera oder Inhalt ändern (spart Akku); Beschriftung höchstens alle 120 ms
  let lt = 0, lblDue = true; (function loop(t) { if (!alive) return; requestAnimationFrame(loop);
    if (anim) { const k = Math.min(1, (t - anim.t0) / anim.ms), e = 1 - Math.pow(1 - k, 3); cam.position.lerpVectors(anim.p0, anim.p1, e); ctl.target.lerpVectors(anim.t0v, anim.t1, e); if (k >= 1) anim = null; dirty = true; }
    if (ctl.update()) dirty = true;
    if (dirty) { renderer.render(scene, cam); dirty = false; lblDue = true; }
    if (lblDue && t - lt > 120) { lt = t; lblDue = false; labels(); } })(0);
  return {
    parts, joints, relations, view, focus, setSel, setMarkers,
    setLayer(ln, on) { if (layers[ln]) layers[ln].mesh.visible = on; dirty = true; },
    setMuscleOpacity(o) { const m = layers.muscle?.mesh.material; if (m) { m.transparent = o < 1; m.opacity = o; m.depthWrite = o >= 1; m.needsUpdate = true; } dirty = true; },
    setLabels(mode) { labelMode = mode; dirty = true; },
    // WebGL-Speicher wirklich freigeben (sonst sammeln sich Kontexte beim mehrmaligen Öffnen)
    dispose() { alive = false; ro.disconnect(); ctl.dispose(); scene.traverse(o => { o.geometry?.dispose?.(); o.material?.dispose?.(); }); mkGeo.dispose(); for (const x of mkMat.values()) x.dispose(); renderer.dispose(); renderer.forceContextLoss(); el.innerHTML = ""; },
  };
}
