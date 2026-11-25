// Körperkarte 3D: Z-Anatomy (CC BY-SA 4.0, auf Basis von BodyParts3D © DBCLS) mit three.js (MIT)
// mount(el, {onPick(part, point), markers}) → {setLayer, setLabels, setMarkers, view, highlight, dispose}
import * as THREE from "../vendor/three/three.module.min.js";
import { GLTFLoader } from "../vendor/three/GLTFLoader.js";
import { OrbitControls } from "../vendor/three/OrbitControls.js";
import { MeshoptDecoder } from "../vendor/three/meshopt_decoder.module.js";

const COL = { skin: 0xe9c2a6, bone: 0xeee3cc, muscle: 0xb5483f, cartilage: 0x9cc7e0, ligament: 0xd8d0b8, tendon: 0xf5ecc8, fascia: 0xdfe6ee };
// Modell: Füße y≈0, Scheitel y≈1,68 m, vorn = +z. Schlüsselbein y≈1,34, Becken y≈0,85, Kniescheibe y≈0,38
const VIEWS = { vorn: [0, 0.85, 3.1, 0, 0.82, 0], hinten: [0, 0.85, -3.1, 0, 0.82, 0], links: [3.1, 0.85, 0, 0, 0.82, 0], rechts: [-3.1, 0.85, 0, 0, 0.82, 0],
  schulter: [-0.3, 1.42, 0.75, -0.06, 1.3, 0.05], brust: [0, 1.32, 0.8, 0, 1.25, 0.08], nacken: [0, 1.48, -0.75, 0, 1.4, 0], ruecken: [0, 1.15, -1.45, 0, 1.12, 0],
  becken: [0, 0.9, 1.3, 0, 0.85, 0], knie: [-0.2, 0.45, 0.95, 0, 0.38, 0.05] };

export async function mount(el, opt = {}) {
  const parts = await (await fetch(new URL("./parts.json", import.meta.url))).json();
  const W = () => el.clientWidth, H = () => el.clientHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio)); renderer.setSize(W(), H());
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(35, W() / H(), 0.05, 20);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6)); const dl = new THREE.DirectionalLight(0xffffff, 1.4); dl.position.set(1, 2, 2); cam.add(dl); scene.add(cam);
  const ctl = new OrbitControls(cam, renderer.domElement); ctl.enableDamping = true; ctl.minDistance = 0.3; ctl.maxDistance = 5;
  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder), gltf = await loader.loadAsync(new URL("./body.glb", import.meta.url).href);
  const layers = {}, labelsEl = document.createElement("div"); labelsEl.className = "b3labels"; el.appendChild(labelsEl);
  gltf.scene.traverse(o => { if (!o.isMesh) return; const name = o.name || o.parent?.name, g = o.geometry; g.computeVertexNormals();
    const pa = g.getAttribute("_part"), n = g.getAttribute("position").count, col = new Float32Array(n * 3), c = new THREE.Color(COL[name] ?? 0xcccccc);
    for (let i = 0; i < n; i++) c.toArray(col, i * 3);
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    o.material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .75, metalness: 0, transparent: name === "skin" || name === "fascia", opacity: name === "skin" ? .28 : name === "fascia" ? .4 : 1, depthWrite: name !== "skin" && name !== "fascia", side: name === "skin" || name === "fascia" ? THREE.FrontSide : THREE.DoubleSide });
    o.renderOrder = name === "skin" ? 3 : name === "fascia" ? 2 : 1; if (name === "fascia") o.visible = false; layers[name] = { mesh: o, pa, base: c };
  });
  scene.add(gltf.scene);
  // Teil-Bereiche je Ebene (Ecken liegen je Teil zusammenhängend)
  // Ecken je Teil sammeln (die Kompression ordnet Ecken um – sie liegen nicht zusammenhängend)
  const range = {}; for (const [ln, L] of Object.entries(layers)) { const tmp = {}; for (let i = 0; i < L.pa.count; i++) { const p = Math.round(L.pa.getX(i)); (tmp[p] || (tmp[p] = [])).push(i); } for (const p in tmp) range[p] = { ln, v: Uint32Array.from(tmp[p]) }; }
  // Gelenke, die im Modell kein eigenes Teil sind: SC (Schlüsselbein–Brustbein) und AC (Schlüsselbein–Schulterhöhe) an den Schlüsselbein-Enden
  const joints = [];
  for (const [en, side] of [["Clavicle.r", "rechts"], ["Clavicle.l", "links"]]) { const p = parts.find(x => x.en === en), r = p && range[p.i]; if (!r) continue;
    const m = layers[r.ln].mesh, pos = m.geometry.getAttribute("position"), v = new THREE.Vector3(); m.updateMatrixWorld(); let lo = null, hi2 = null;
    for (const i of r.v) { v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld); const ax = Math.abs(v.x); if (!lo || ax < lo.ax) lo = {ax, p: v.toArray()}; if (!hi2 || ax > hi2.ax) hi2 = {ax, p: v.toArray()}; }
    joints.push({name: `SC-Gelenk ${side}`, pt: lo.p}, {name: `AC-Gelenk ${side}`, pt: hi2.p}); }
  const jointAt = pt => { let best = null; for (const j of joints) { const d = Math.hypot(pt[0] - j.pt[0], pt[1] - j.pt[1], pt[2] - j.pt[2]); if (d < 0.035 && (!best || d < best.d)) best = {...j, d}; } return best?.name || null; };
  let hi = null; const HI = new THREE.Color(0xffc23d);
  function paint(p, color) { const r = range[p]; if (!r) return; const L = layers[r.ln], col = L.mesh.geometry.getAttribute("color"); for (const i of r.v) color.toArray(col.array, i * 3); col.needsUpdate = true; }
  function highlight(p) { if (hi != null) paint(hi, layers[range[hi].ln].base); hi = p ?? null; if (hi != null) paint(hi, HI); }
  // Markierungen (Schmerzpunkte)
  const mk = new THREE.Group(); scene.add(mk);
  function setMarkers(list = []) { mk.clear(); for (const m of list) { const s = new THREE.Mesh(new THREE.SphereGeometry(.012 + .002 * (m.n || 0), 16, 12), new THREE.MeshBasicMaterial({ color: new THREE.Color().setHSL((1 - Math.min(10, m.n || 0) / 10) * .33, .9, .5), transparent: true, opacity: m.old ? .35 : .95, depthTest: false }));
    s.position.fromArray(m.pt); s.renderOrder = 5; s.userData = m; mk.add(s); } }
  setMarkers(opt.markers || []);
  // Beschriftung: gewähltes Teil, Markierungen, auf Wunsch die größten sichtbaren Muskeln
  let labelMode = "auto";
  // beschriftbar: übersetzte Muskeln und Knochen, dazu alle Sehnen, Bänder und Knorpel (auch mit Fachnamen)
  // beschriftbar: Teile mit Körperregion (übersetzte Muskeln, Knochen, Knorpel) und alle Sehnen/Bänder
  const big = parts.filter(p => p.layer !== "skin" && p.g).map(p => p.i);
  function labels() { const out = [], placed = [], v = new THREE.Vector3();
    const scr = pos => { v.fromArray(pos).project(cam); return v.z > 1 || Math.abs(v.x) > 1.02 || Math.abs(v.y) > 1.02 ? null : [(v.x + 1) / 2 * W(), (1 - v.y) / 2 * H()]; };
    const push = (pos, txt, cls, force) => { const s = scr(pos); if (!s) return; if (!force && placed.some(([x, y]) => Math.abs(x - s[0]) < 80 && Math.abs(y - s[1]) < 17)) return; placed.push(s); out.push(`<span class="${cls}" style="left:${s[0]}px;top:${s[1]}px">${txt}</span>`); };
    const vis = ln => layers[ln]?.mesh.visible, mOpaque = vis("muscle") && layers.muscle.mesh.material.opacity >= 1;
    for (const s of mk.children) if (s.userData.label) push(s.userData.pt, esc(s.userData.label), "lb pain", true);
    if (hi != null && labelMode !== "off") push(parts[hi].c, esc(parts[hi].de), "lb sel", true);
    if (labelMode === "all") { const camDir = new THREE.Vector3(); cam.getWorldDirection(camDir);
      // Knochen und Knorpel nur beschriften, wenn keine deckenden Muskeln davor sind; nah an der Bildmitte zuerst
      // nur Teile auf der Kameraseite: mindestens 3 cm vor der Körperachse (sonst schimmern Rückenmuskeln und Wirbel durch)
      const cand = big.filter(i => { const p = parts[i]; if (!vis(p.layer) || (mOpaque && (p.layer === "bone" || p.layer === "cartilage" || (p.layer === "tendon" && /^(Ursprung|Ansatz)/.test(p.de)))) || /disk/.test(p.en)) return false; const d = new THREE.Vector3().fromArray(p.c).sub(cam.position);
          const side = new THREE.Vector3(p.c[0], 0, p.c[2] - 0.03).dot(new THREE.Vector3(camDir.x, 0, camDir.z).normalize()); return d.dot(camDir) > 0 && d.length() < 2.6 && side < -0.03; })
        .map(i => [i, scr(parts[i].c)]).filter(x => x[1]).sort((a, b) => Math.hypot(a[1][0] - W() / 2, a[1][1] - H() / 2) - Math.hypot(b[1][0] - W() / 2, b[1][1] - H() / 2));
      for (const [i] of cand) { if (out.length > 22) break; push(parts[i].c, esc(parts[i].de.split(" · ")[0]), "lb"); } }
    labelsEl.innerHTML = out.join(""); }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // Antippen: Teil bestimmen (Ziehen zum Drehen ist kein Antippen)
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(); let down = null;
  renderer.domElement.addEventListener("pointerdown", e => down = [e.clientX, e.clientY, Date.now()]);
  renderer.domElement.addEventListener("pointerup", e => { if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 8 || Date.now() - down[2] > 600) return; const rc = renderer.domElement.getBoundingClientRect();
    ndc.set((e.clientX - rc.left) / rc.width * 2 - 1, -((e.clientY - rc.top) / rc.height) * 2 + 1); ray.setFromCamera(ndc, cam);
    const order = ["muscle", "tendon", "ligament", "cartilage", "bone", "fascia", "skin"], meshes = order.map(l => layers[l]?.mesh).filter(m => m && m.visible);
    // durch die halbdurchsichtige Haut hindurch: die erste Struktur darunter (bis 8 cm tief), sonst die Haut
    // ebenso durch den hauchdünnen Halshautmuskel (liegt über Schlüsselbein und SC-Gelenk)
    const hits = ray.intersectObjects(meshes, false), partOf = x => Object.values(layers).find(l => l.mesh === x.object).pa.getX(x.face.a);
    const thin = x => x.object === layers.skin?.mesh || x.object === layers.fascia?.mesh || /platysma/i.test(parts[partOf(x)].en), h0 = hits[0];
    const hit = h0 && thin(h0) ? hits.find(x => !thin(x) && x.distance - h0.distance < 0.08) || h0 : h0;
    if (!hit) { highlight(null); opt.onPick?.(null); return; }
    const p = partOf(hit), pt = hit.point.toArray().map(x => +x.toFixed(4)); highlight(p); opt.onPick?.(parts[p], pt, jointAt(pt)); });
  // Ansichten sind für Schlüsselbeinhöhe 1,336 m angelegt: Höhen an das geladene Modell anpassen
  const ky = (parts.find(p => /^(Clavicle\.r|right clavicle)$/.test(p.en))?.c[1] || 1.336) / 1.336;
  function view(name) { const v = VIEWS[name]; if (!v) return; cam.position.set(v[0], v[1] * ky, v[2]); ctl.target.set(v[3], v[4] * ky, v[5]); ctl.update(); }
  view(opt.view || "vorn");
  let alive = true; const ro = new ResizeObserver(() => { renderer.setSize(W(), H()); cam.aspect = W() / H(); cam.updateProjectionMatrix(); }); ro.observe(el);
  let lt = 0; (function loop(t) { if (!alive) return; requestAnimationFrame(loop); ctl.update(); renderer.render(scene, cam); if (t - lt > 120) { lt = t; labels(); } })(0);
  return {
    parts, joints, view, highlight, setMarkers,
    setLayer(ln, on) { if (layers[ln]) layers[ln].mesh.visible = on; },
    setMuscleOpacity(o) { const m = layers.muscle?.mesh.material; if (m) { m.transparent = o < 1; m.opacity = o; m.depthWrite = o >= 1; m.needsUpdate = true; } },
    setLabels(mode) { labelMode = mode; },
    dispose() { alive = false; ro.disconnect(); ctl.dispose(); renderer.dispose(); el.innerHTML = ""; },
  };
}
