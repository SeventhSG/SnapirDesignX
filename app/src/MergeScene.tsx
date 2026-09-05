/**
 * The merge, in three dimensions.
 *
 * A stairwell is the reason this exists at all, and a stairwell is the one
 * thing a plan cannot show: its floors sit on top of each other, so drawn flat
 * they land in the same place on the paper and the corner you are trying to
 * click is under three other corners. Stacked properly they are four separate
 * things at four separate heights, and matching one to the next is a matter of
 * looking at it.
 *
 * The scene draws what it is given and reports what was clicked. Where each
 * room sits, and what a click means, is the caller's business.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

/** One room, already carried into the project's frame by the caller. */
export interface MergeDraw {
  room: string;
  colour: string;
  placed: boolean;
  points: { name: string; at: [number, number, number]; role: string;
            paired: boolean; picked: boolean }[];
  lines: { a: string; b: string; from: [number, number, number];
           to: [number, number, number]; picked: boolean }[];
}

const CM = 0.01;                    // survey centimetres to scene metres
const ROLE_COLOR: Record<string, string> = {
  floor: "#26262A", ceiling: "#9E9D95", opening: "#A87A26",
  socket: "#0F8A4E", plumbing: "#3D7A96", control: "#7C7B82",
  station: "#7C7B82", stairs: "#8A5CC4", pervaz: "#B07A3C",
  depth: "#C0483C", unknown: "#CB4A2A",
};

interface Scene {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  world: THREE.Group;
  dots: THREE.Mesh[];
  runs: THREE.LineSegments[];
  centre: THREE.Vector3;
}

export default function MergeScene({
  draw, dark, fitKey, onPickPoint, onPickLine, onClear,
}: {
  draw: MergeDraw[];
  dark: boolean;
  /** Changes when the caller wants the view reframed. */
  fitKey: number;
  onPickPoint: (room: string, point: string) => void;
  onPickLine: (room: string, line: [string, string]) => void;
  onClear: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const S = useRef<Scene>();
  const cb = useRef({ onPickPoint, onPickLine, onClear });
  cb.current = { onPickPoint, onPickLine, onClear };

  /* ---------------- the scene, once ---------------- */
  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 2000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;

    scene.add(new THREE.HemisphereLight(0xffffff, 0x9a9a92, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(4, 8, 6);
    scene.add(key);

    // Survey coordinates are Z-up; three.js is Y-up.
    const pivot = new THREE.Group();
    pivot.rotation.x = -Math.PI / 2;
    scene.add(pivot);
    const world = new THREE.Group();
    pivot.add(world);

    const state: Scene = {
      renderer, scene, camera, controls, world,
      dots: [], runs: [], centre: new THREE.Vector3(),
    };
    S.current = state;

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    let alive = true;
    const tick = () => {
      if (!alive) return;
      controls.update();
      renderer.render(scene, camera);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);

    /* ---------------- picking ---------------- */
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let downAt = { x: 0, y: 0 };

    const aim = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      ray.setFromCamera(ndc, camera);
    };

    const down = (e: PointerEvent) => { downAt = { x: e.clientX, y: e.clientY }; };

    const up = (e: PointerEvent) => {
      // A drag is an orbit, not a click.
      if (Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 4) return;
      aim(e);
      const hit = ray.intersectObjects(state.dots, false)[0];
      if (hit) {
        const d = hit.object.userData as { room: string; point: string };
        cb.current.onPickPoint(d.room, d.point);
        return;
      }
      // Lines are one buffer per room, so the hit comes back as a vertex index;
      // two vertices to a segment.
      ray.params.Line = { threshold: 0.07 };
      const line = ray.intersectObjects(state.runs, false)[0];
      if (line && line.index != null) {
        const owner = line.object.userData as {
          room: string; pairs: [string, string][];
        };
        const seg = owner.pairs[Math.floor(line.index / 2)];
        if (seg) { cb.current.onPickLine(owner.room, seg); return; }
      }
      cb.current.onClear();
    };

    const move = (e: PointerEvent) => {
      aim(e);
      const over = ray.intersectObjects(state.dots, false).length > 0;
      el.style.cursor = over ? "pointer" : "grab";
    };

    el.addEventListener("pointerdown", down);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointermove", move);
    return () => {
      alive = false;
      ro.disconnect();
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointermove", move);
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
      S.current = undefined;
    };
  }, []);

  /* ---------------- what is in it ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s) return;

    for (const child of [...s.world.children]) {
      s.world.remove(child);
      const m = child as THREE.Mesh;
      m.geometry?.dispose?.();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
      else mat?.dispose?.();
    }
    s.dots = [];
    s.runs = [];

    const box = new THREE.Box3();
    for (const r of draw)
      for (const p of r.points)
        box.expandByPoint(new THREE.Vector3(p.at[0] * CM, p.at[1] * CM, p.at[2] * CM));
    if (box.isEmpty()) box.expandByPoint(new THREE.Vector3());
    const mid = box.getCenter(new THREE.Vector3());
    s.centre.copy(mid);
    const at = (p: [number, number, number]) =>
      new THREE.Vector3(p[0] * CM - mid.x, p[1] * CM - mid.y, p[2] * CM - mid.z);

    const span = Math.max(box.getSize(new THREE.Vector3()).length(), 1);
    const dot = Math.min(Math.max(span * 0.004, 0.02), 0.09);
    const geo = new THREE.SphereGeometry(1, 12, 8);

    for (const r of draw) {
      const colour = new THREE.Color(r.colour);

      if (r.lines.length) {
        const pos: number[] = [];
        const pairs: [string, string][] = [];
        let anyPicked = false;
        for (const l of r.lines) {
          const a = at(l.from), b = at(l.to);
          pos.push(a.x, a.y, a.z, b.x, b.y, b.z);
          pairs.push([l.a, l.b]);
          anyPicked = anyPicked || l.picked;
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
        const runs = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
          color: colour, transparent: true,
          opacity: r.placed ? (anyPicked ? 1 : 0.75) : 0.4,
        }));
        runs.userData = { room: r.room, pairs };
        s.world.add(runs);
        s.runs.push(runs);
      }

      // The picked line again, thicker, so it reads as picked. A line width
      // over 1 is ignored on most platforms, hence a second pass rather than a
      // wider material.
      for (const l of r.lines) {
        if (!l.picked) continue;
        const g = new THREE.BufferGeometry().setFromPoints([at(l.from), at(l.to)]);
        const lit = new THREE.LineSegments(
          g, new THREE.LineBasicMaterial({ color: 0xc99b3f }));
        lit.renderOrder = 3;
        s.world.add(lit);
      }

      for (const p of r.points) {
        const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
          color: new THREE.Color(p.picked ? "#C99B3F"
            : p.paired ? r.colour : ROLE_COLOR[p.role] ?? "#7C7B82"),
          emissive: new THREE.Color(p.picked ? "#C99B3F" : "#000000"),
          emissiveIntensity: p.picked ? 0.85 : 0,
          roughness: 0.5, metalness: 0.05,
          transparent: !r.placed, opacity: r.placed ? 1 : 0.55,
        }));
        mesh.scale.setScalar(dot * (p.picked ? 2.1 : p.paired ? 1.6 : 1));
        mesh.position.copy(at(p.at));
        mesh.userData = { room: r.room, point: p.name };
        s.world.add(mesh);
        s.dots.push(mesh);
      }
    }
  }, [draw]);

  /* ---------------- framing ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s || !draw.length) return;
    const box = new THREE.Box3();
    for (const r of draw)
      for (const p of r.points)
        box.expandByPoint(new THREE.Vector3(
          p.at[0] * CM - s.centre.x, p.at[1] * CM - s.centre.y,
          p.at[2] * CM - s.centre.z));
    const size = Math.max(box.getSize(new THREE.Vector3()).length(), 1);
    // Survey Z is world Y once the pivot has turned it, so the eye goes up in Y.
    s.camera.position.set(size * 0.62, size * 0.52, size * 0.68);
    s.camera.near = size / 900;
    s.camera.far = size * 14;
    s.camera.updateProjectionMatrix();
    s.controls.target.set(0, 0, 0);
    s.controls.update();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  useEffect(() => {
    const s = S.current;
    if (s) s.scene.background = null;
  }, [dark]);

  return <div ref={host} className="mergeplan" />;
}
