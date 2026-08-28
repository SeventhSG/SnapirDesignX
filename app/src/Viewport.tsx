/**
 * The 3D viewport. Two jobs, one scene.
 *
 * Solid mode shows the built body. Every triangle carries the id of the B-rep
 * face it came from, so clicking picks a real face in the solid rather than a
 * patch of triangles.
 *
 * Sketch mode shows the survey itself: every measured point, coloured by what
 * it is, the outline drawn through the floor corners, and a vertical link from
 * each corner up to the ceiling. The solid is hidden here on purpose. Leaving
 * the last build on screen while the outline is being redrawn makes a stale
 * body look like a broken one.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import type { Mesh as MeshData, Point } from "./api";

const GOLD = new THREE.Color("#A87A26");
const HOVER = new THREE.Color("#C99B3F");
const MASS_LIGHT = new THREE.Color("#8E8D85");
const MASS_DARK = new THREE.Color("#6A6A72");

/** Point colours by role. The same vocabulary as the plan view. */
export const ROLE_COLOR: Record<string, string> = {
  floor: "#26262A",
  ceiling: "#9E9D95",
  opening: "#A87A26",
  socket: "#3B7455",
  plumbing: "#3D7A96",
  control: "#7C7B82",
  station: "#7C7B82",
  unknown: "#A34A28",
};

export interface SketchProps {
  points: Point[];
  /** Every line the survey drew, plus anything the operator added. */
  segments: [string, string][];
  ring: string[];
  selectedPoint: string | null;
  pending: string | null;
  selectedLine: [string, string] | null;
  onPickPoint: (name: string) => void;
  onPickLine: (seg: [string, string] | null) => void;
}

/** What a line is, judged only by what it joins. */
function segmentKind(a: Point, b: Point): string {
  const r = new Set([a.role, b.role]);
  if (r.size === 1 && r.has("floor")) return "floor";
  if (r.size === 1 && r.has("ceiling")) return "ceiling";
  if (r.has("floor") && r.has("ceiling")) return "link";
  if (r.has("opening")) return "opening";
  return "other";
}

const LINE_3D: Record<string, { color: number; w: number; dash: boolean }> = {
  floor: { color: 0xa87a26, w: 3.4, dash: false },
  ceiling: { color: 0x9e9d95, w: 1.9, dash: false },
  link: { color: 0x9e9d95, w: 1.7, dash: true },
  opening: { color: 0x7a5716, w: 2.2, dash: false },
  other: { color: 0xb0afa8, w: 1.4, dash: false },
};

interface Props {
  mesh: MeshData | null;
  selected: number | null;
  onSelect: (faceId: number | null) => void;
  sketch?: SketchProps | null;
  /** "orbit" walks around the body, "inside" stands in the room and looks. */
  look?: "orbit" | "inside";
  /** See through the walls without cutting the body. */
  ghost?: boolean;
  dark?: boolean;
}

interface Scene {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  solid: THREE.Group;
  sketch: THREE.Group;
  lineMats: LineMaterial[];
  geom?: THREE.BufferGeometry;
  body?: THREE.Mesh;
  faceIds: number[];
  dots: THREE.Mesh[];
  lines: THREE.Object3D[];
  hovered: number | null;
  selected: number | null;
  sketching: boolean;
  inside: boolean;
  eye: THREE.Vector3;      // where the inside camera stands
  yaw: number;
  pitch: number;
  dark: boolean;
  edges?: THREE.LineSegments;
  shadow?: THREE.Mesh;
}

const CM = 0.01;                       // survey centimetres to scene metres

export default function Viewport({
  mesh, selected, onSelect, sketch, look = "orbit", ghost = false, dark = false,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const S = useRef<Scene>();
  const cb = useRef({ onSelect, sketch, dark });
  cb.current = { onSelect, sketch, dark };
  // Camera framing is a deliberate act, not a side effect of re-rendering.
  const viewRef = useRef<string>("");

  /* ---------------- scene, once ---------------- */
  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    // Filmic tone mapping keeps the highlights on a white body from blowing
    // out, which is most of what makes a CAD render look cheap.
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.02, 500);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;
    controls.rotateSpeed = 0.85;

    scene.add(new THREE.HemisphereLight(0xffffff, 0x9a9a92, 2.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(5, 9, 6);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5);
    fill.position.set(-6, 3, -4);
    scene.add(fill);

    // Survey coordinates are Z-up; three.js is Y-up.
    const pivot = new THREE.Group();
    pivot.rotation.x = -Math.PI / 2;
    scene.add(pivot);
    const solid = new THREE.Group();
    const sk = new THREE.Group();
    pivot.add(solid, sk);

    const state: Scene = {
      renderer, scene, camera, controls, solid, sketch: sk, lineMats: [],
      faceIds: [], dots: [], lines: [], hovered: null, selected: null,
      sketching: false,
      inside: false, eye: new THREE.Vector3(), yaw: 0, pitch: 0, dark,
    };

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      // Fat lines need the pixel size of the canvas to stay a constant width.
      for (const m of state.lineMats) m.resolution.set(w, h);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    let alive = true;
    const tick = () => {
      if (!alive) return;
      // OrbitControls rewrites the camera from its own spherical state on
      // every update, even when disabled. Standing inside the room means
      // driving the camera directly, so it must not run at all.
      if (!state.inside) controls.update();
      renderer.render(scene, camera);
      requestAnimationFrame(tick);
    };
    tick();

    S.current = state;
    return () => {
      alive = false;
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
      S.current = undefined;
    };
  }, []);

  /* ---------------- the solid ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s) return;
    clear(s.solid, s);
    s.body = undefined;
    s.geom = undefined;
    if (!mesh) return;

    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
    geom.setAttribute("normal", new THREE.Float32BufferAttribute(mesh.normals, 3));
    geom.setAttribute("color",
      new THREE.BufferAttribute(new Float32Array(mesh.positions.length), 3));
    geom.computeBoundingBox();

    const body = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: 0.58, metalness: 0.04,
      flatShading: true, side: THREE.DoubleSide,
    }));
    const bb = geom.boundingBox!;
    const c = bb.getCenter(new THREE.Vector3());
    body.position.set(-c.x, -c.y, -c.z);

    // Eye height inside the room: 1.6 m above the floor, on the room's axis.
    // Survey Z becomes world Y once the pivot has rotated the group.
    const halfH = (bb.max.z - bb.min.z) / 2;
    s.eye.set(0, -halfH + 1.6, 0);
    s.solid.add(body);
    s.body = body;
    s.geom = geom;
    s.faceIds = mesh.faceIds;

    // Crisp edges are what separate a CAD body from a grey blob. 24 degrees
    // keeps real corners and ignores tessellation seams.
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geom, 24),
      new THREE.LineBasicMaterial({
        color: s.dark ? 0x8d8c94 : 0x4a4a50, transparent: true, opacity: 0.55,
      })
    );
    edges.position.copy(body.position);
    edges.renderOrder = 1;
    s.solid.add(edges);
    s.edges = edges;

    // A soft contact shadow anchors the body instead of leaving it floating.
    const shadow = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.MeshBasicMaterial({
        map: contactShadow(), transparent: true, opacity: s.dark ? 0.5 : 0.34,
        depthWrite: false,
      })
    );
    const size = bb.getSize(new THREE.Vector3());
    shadow.scale.set(Math.max(size.x, 0.5) * 2.1, Math.max(size.y, 0.5) * 2.1, 1);
    shadow.position.set(0, 0, -halfH - 0.004);
    shadow.renderOrder = 0;
    s.solid.add(shadow);
    s.shadow = shadow;

    if (!s.sketching) frame(s, geom.boundingBox!.getSize(new THREE.Vector3()).length());
    paint(s, null, null);
  }, [mesh]);

  /* ---------------- the sketch ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s) return;
    clear(s.sketch, s);
    s.dots = [];
    s.lines = [];
    const wasSketching = s.sketching;
    s.sketching = !!sketch;

    // The solid is never shown while the outline is being edited.
    s.solid.visible = !sketch;
    s.sketch.visible = !!sketch;
    if (!sketch) {
      if (wasSketching && s.geom?.boundingBox) {
        frame(s, s.geom.boundingBox.getSize(new THREE.Vector3()).length());
      }
      return;
    }

    const { points, ring, selectedPoint, pending } = sketch;
    const box = new THREE.Box3();
    points.forEach((p) =>
      box.expandByPoint(new THREE.Vector3(p.x * CM, p.y * CM, p.z * CM)));
    const mid = box.getCenter(new THREE.Vector3());
    const at = (x: number, y: number, z: number) =>
      new THREE.Vector3(x * CM - mid.x, y * CM - mid.y, z * CM - mid.z);

    const { clientWidth: w, clientHeight: h } = host.current!;
    const fatLine = (pts: THREE.Vector3[], color: number,
                     width: number, dashed = false, seg?: [string, string]) => {
      const g = new LineGeometry();
      g.setPositions(pts.flatMap((v) => [v.x, v.y, v.z]));
      const m = new LineMaterial({
        color, linewidth: width, dashed,
        dashSize: 0.09, gapSize: 0.06, transparent: true, opacity: dashed ? 0.7 : 1,
      });
      m.resolution.set(w || 1, h || 1);
      s.lineMats.push(m);
      const line = new Line2(g, m);
      if (dashed) line.computeLineDistances();
      if (seg) {
        line.userData.seg = seg;
        line.computeLineDistances();
        s.lines.push(line);
      }
      s.sketch.add(line);
      return line;
    };

    const byName = new Map(points.map((p) => [p.name, p]));

    /* Every connection the room actually claims. Nothing is inferred here:
       a line appears because the survey drew it or the operator added it. */
    const chosen = sketch.selectedLine
      ? [sketch.selectedLine[0], sketch.selectedLine[1]].sort().join("|") : null;
    for (const [an, bn] of sketch.segments) {
      const a = byName.get(an), b = byName.get(bn);
      if (!a || !b) continue;
      const st = LINE_3D[segmentKind(a, b)];
      const isSel = chosen === [an, bn].sort().join("|");
      fatLine([at(a.x, a.y, a.z), at(b.x, b.y, b.z)],
              isSel ? 0x3b7455 : st.color, isSel ? st.w + 2.4 : st.w,
              st.dash, [an, bn]);
    }

    /* The outline being drawn sits over the top so it stays readable. */
    const path = ring.map((n) => byName.get(n)).filter(Boolean) as Point[];
    if (path.length > 1) {
      const verts = path.map((p) => at(p.x, p.y, p.z));
      if (path.length > 2) verts.push(verts[0]);
      fatLine(verts, 0xa87a26, 4.2);

      if (path.length > 2) {
        const shape = new THREE.Shape(path.map((p) =>
          new THREE.Vector2(p.x * CM - mid.x, p.y * CM - mid.y)));
        const plate = new THREE.Mesh(new THREE.ShapeGeometry(shape),
          new THREE.MeshBasicMaterial({
            color: 0xa87a26, transparent: true, opacity: 0.11,
            side: THREE.DoubleSide, depthWrite: false,
          }));
        plate.position.z = at(0, 0, path[0].z).z;
        s.sketch.add(plate);
      }
    }

    /* Points last, so they sit on top of every line. */
    const geo = new THREE.SphereGeometry(1, 18, 12);
    for (const p of points) {
      const inRing = ring.includes(p.name);
      const chosen = p.name === selectedPoint;
      const waiting = p.name === pending;
      const dot = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
        color: new THREE.Color(inRing ? "#A87A26" : ROLE_COLOR[p.role] ?? "#7C7B82"),
        roughness: 0.45, metalness: 0.05,
        emissive: new THREE.Color(waiting ? "#3B7455" : chosen ? "#C99B3F" : "#000000"),
        emissiveIntensity: waiting || chosen ? 0.95 : 0,
      }));
      dot.scale.setScalar(chosen || waiting ? 0.064 : inRing ? 0.05 : 0.036);
      dot.position.copy(at(p.x, p.y, p.z));
      dot.userData.name = p.name;
      dot.renderOrder = 2;
      s.sketch.add(dot);
      s.dots.push(dot);
    }

    // Only reframe when the view actually changes what it is showing. Picking
    // a point or switching tool must leave the camera exactly where it was.
    if (!wasSketching) frame(s, box.getSize(new THREE.Vector3()).length());
  }, [sketch]);

  /* ---------------- theme ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s) return;
    s.dark = dark;
    if (s.edges) {
      (s.edges.material as THREE.LineBasicMaterial).color.set(
        dark ? 0x8d8c94 : 0x4a4a50);
    }
    if (s.shadow) {
      (s.shadow.material as THREE.MeshBasicMaterial).opacity = dark ? 0.5 : 0.34;
    }
    paint(s, s.selected, s.hovered);
  }, [dark, mesh]);

  /* ---------------- see-through ---------------- */
  useEffect(() => {
    const s = S.current;
    const mat = s?.body?.material as THREE.MeshStandardMaterial | undefined;
    if (!mat) return;
    mat.transparent = ghost;
    mat.opacity = ghost ? 0.32 : 1;
    mat.depthWrite = !ghost;
    mat.needsUpdate = true;
    if (s?.edges) (s.edges.material as THREE.LineBasicMaterial).opacity =
      ghost ? 0.85 : 0.55;
  }, [ghost, mesh]);

  /* ---------------- stand inside the room ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s) return;
    const wantInside = look === "inside" && !sketch && !!s.body;
    const sig = `${wantInside}|${!!sketch}|${!!s.body}`;
    if (viewRef.current === sig) return;      // nothing about the view changed
    viewRef.current = sig;

    s.inside = wantInside;
    s.controls.enabled = !wantInside;

    if (wantInside) {
      // Start facing the longest wall rather than an arbitrary direction.
      s.yaw = 0;
      s.pitch = 0;
      s.camera.position.copy(s.eye);
      s.camera.fov = 75;
      s.camera.near = 0.02;
      s.camera.updateProjectionMatrix();
      s.camera.rotation.order = "YXZ";
      s.camera.rotation.set(0, 0, 0);
    } else if (s.geom?.boundingBox) {
      s.camera.fov = 38;
      s.camera.rotation.set(0, 0, 0);
      frame(s, s.geom.boundingBox.getSize(new THREE.Vector3()).length());
    }
  }, [look, sketch, mesh]);

  /* ---------------- selection from outside ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s || !s.geom) return;
    s.selected = selected;
    paint(s, selected, s.hovered);
  }, [selected, mesh]);

  /* ---------------- picking ---------------- */
  useEffect(() => {
    const s = S.current;
    const el = host.current;
    if (!s || !el) return;

    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let downAt = { x: 0, y: 0 };
    let onDot = false;

    const aim = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      ray.setFromCamera(ndc, s.camera);
    };

    const faceUnder = (e: PointerEvent): number | null => {
      if (!s.body || !s.solid.visible) return null;
      aim(e);
      const hit = ray.intersectObject(s.body, false)[0];
      if (!hit || hit.faceIndex == null) return null;
      return s.faceIds[hit.faceIndex] ?? null;
    };

    const dotUnder = (e: PointerEvent): string | null => {
      if (!s.sketch.visible || !s.dots.length) return null;
      aim(e);
      const hit = ray.intersectObjects(s.dots, false)[0];
      return (hit?.object.userData.name as string) ?? null;
    };

    const lineUnder = (e: PointerEvent): [string, string] | null => {
      if (!s.sketch.visible || !s.lines.length) return null;
      aim(e);
      ray.params.Line2 = { threshold: 6 };
      const hit = ray.intersectObjects(s.lines, false)[0];
      return (hit?.object.userData.seg as [string, string]) ?? null;
    };

    const move = (e: PointerEvent) => {
      if (s.inside) {
        if (looking) lookMove(e);
        el.style.cursor = looking ? "grabbing" : "grab";
        return;
      }
      if (s.sketch.visible) {
        el.style.cursor = dotUnder(e) || lineUnder(e) ? "pointer" : "grab";
        return;
      }
      const id = faceUnder(e);
      if (id === s.hovered) return;
      s.hovered = id;
      el.style.cursor = id === null ? "default" : "pointer";
      paint(s, s.selected, id);
    };

    let looking = false;
    let lastAt = { x: 0, y: 0 };

    const lookMove = (e: PointerEvent) => {
      if (!looking || !s.inside) return;
      s.yaw -= (e.clientX - lastAt.x) * 0.0032;
      s.pitch -= (e.clientY - lastAt.y) * 0.0032;
      s.pitch = Math.max(-1.35, Math.min(1.35, s.pitch));
      lastAt = { x: e.clientX, y: e.clientY };
      s.camera.rotation.order = "YXZ";
      s.camera.rotation.set(s.pitch, s.yaw, 0);
      s.camera.position.copy(s.eye);
    };

    const wheel = (e: WheelEvent) => {
      if (!s.inside) return;
      e.preventDefault();
      s.camera.fov = Math.max(35, Math.min(95, s.camera.fov + Math.sign(e.deltaY) * 3));
      s.camera.updateProjectionMatrix();
    };

    const down = (e: PointerEvent) => {
      if (s.inside) {
        looking = true;
        lastAt = { x: e.clientX, y: e.clientY };
        el.setPointerCapture?.(e.pointerId);
      }
      downAt = { x: e.clientX, y: e.clientY };
      // Pressing a point selects it. The camera must not move underneath the
      // click, so orbiting is switched off for the whole gesture.
      onDot = !!dotUnder(e);
      if (onDot) s.controls.enabled = false;
    };

    const up = (e: PointerEvent) => {
      const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 4;
      if (s.inside) {
        looking = false;
        el.releasePointerCapture?.(e.pointerId);
        if (!moved) cb.current.onSelect(faceUnder(e));
        return;
      }
      if (onDot) {
        const name = dotUnder(e);
        if (name) cb.current.sketch?.onPickPoint(name);
        s.controls.enabled = true;
        onDot = false;
        return;
      }
      if (moved) return;              // that was an orbit, not a click
      if (s.sketch.visible) {
        // A point wins over a line when both are under the cursor.
        const name = dotUnder(e);
        if (name) { cb.current.sketch?.onPickPoint(name); return; }
        cb.current.sketch?.onPickLine(lineUnder(e));
        return;
      }
      cb.current.onSelect(faceUnder(e));
    };

    const cancel = () => {
      if (!s.inside) s.controls.enabled = true;
      onDot = false;
    };

    el.addEventListener("pointermove", move);
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", cancel);
    el.addEventListener("pointerleave", cancel);
    el.addEventListener("wheel", wheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", wheel);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", cancel);
      el.removeEventListener("pointerleave", cancel);
    };
  }, []);

  return <div ref={host} style={{ position: "absolute", inset: 0 }} />;
}

/* ---------------- helpers ---------------- */

function clear(group: THREE.Group, s: Scene) {
  for (const child of [...group.children]) {
    group.remove(child);
    const m = child as THREE.Mesh;
    m.geometry?.dispose?.();
    const mat = m.material as THREE.Material | THREE.Material[] | undefined;
    if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
    else mat?.dispose?.();
  }
  if (group === s.sketch) s.lineMats = [];
}

/** Put the camera where the whole thing is comfortably in view. */
function frame(s: Scene, size: number) {
  const d = Math.max(size, 1);
  s.camera.position.set(d * 0.55, d * 0.45, d * 0.6);
  s.camera.near = d / 400;
  s.camera.far = d * 12;
  s.camera.updateProjectionMatrix();
  s.controls.target.set(0, 0, 0);
  s.controls.update();
}

/** A soft round gradient, used as the body's contact shadow. */
let shadowTex: THREE.Texture | null = null;
function contactShadow(): THREE.Texture {
  if (shadowTex) return shadowTex;
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(128, 128, 8, 128, 128, 126);
  grad.addColorStop(0, "rgba(20,20,24,0.55)");
  grad.addColorStop(0.55, "rgba(20,20,24,0.20)");
  grad.addColorStop(1, "rgba(20,20,24,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 256, 256);
  shadowTex = new THREE.CanvasTexture(c);
  return shadowTex;
}

/** Repaint per-vertex colours for the current selection and hover. */
function paint(s: Scene, selected: number | null, hovered: number | null) {
  const attr = s.geom?.getAttribute("color") as THREE.BufferAttribute | undefined;
  if (!attr) return;
  for (let tri = 0; tri < s.faceIds.length; tri++) {
    const id = s.faceIds[tri];
    const base = s.dark ? MASS_DARK : MASS_LIGHT;
    const c = id === selected ? GOLD : id === hovered ? HOVER : base;
    for (let v = 0; v < 3; v++) attr.setXYZ(tri * 3 + v, c.r, c.g, c.b);
  }
  attr.needsUpdate = true;
}
