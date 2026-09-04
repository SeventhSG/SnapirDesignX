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
  socket: "#0F8A4E",
  plumbing: "#3D7A96",
  control: "#7C7B82",
  station: "#7C7B82",
  unknown: "#CB4A2A",
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

/** A place in the room, in the survey's own centimetres. */
export interface AimHit { x: number; y: number; z: number }

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
  /** The floor ring in survey centimetres. Inside it is where you may walk. */
  bounds?: [number, number][];
  /** The floor datum in survey centimetres. Not the bottom of the body: the
   *  slab hangs below it, and standing on that is standing underground. */
  floorZ?: number | null;
  /** Where the instrument stood, survey centimetres. Somewhere to stand. */
  stations?: [number, number, number][];
  /** The panorama for the station being stood at, once its heading solved. */
  pano?: { url: string; heading: number; station: number } | null;
  /** Show the photograph instead of the body. */
  panoOpen?: boolean;
  /** Where the eye is now, so the chip above can crop to match. */
  onLook?: (look: { yaw: number; at: number | null }) => void;
  /** Filled with a function that reads whatever the crosshair is pointing at,
   *  so standing inside the room and aiming can add a point the surveyor
   *  missed. Null when nothing is in front of it. */
  aimHandle?: React.MutableRefObject<(() => AimHit | null) | null>;
  /** Doors hooked to another room, in this room's own survey centimetres.
   *  Walking into one, or clicking its ghost, crosses into the room beyond. */
  doors?: DoorLink[];
  /** A faded preview of what is beyond each connected door, already placed
   *  into this room's local frame (rotate then translate). */
  ghostRooms?: GhostRoom[];
  /** A connected door was walked into or clicked on. */
  onCrossDoor?: (connectionId: string) => void;
  /** Stand here instead of at the first station -- set right after crossing
   *  into this room through a connected door, survey centimetres + world
   *  yaw radians (already carried across the connection's own rotation by
   *  the caller, so this is the heading to face, not a fixed "into the
   *  room" direction). */
  enterAt?: { x: number; y: number; yaw: number } | null;
}

export interface DoorLink {
  connectionId: string;
  left: [number, number];
  right: [number, number];
}

export interface GhostRoom {
  connectionId: string;
  outline: [number, number][];
  floorZ: number | null;
  ceilingHeight: number | null;
  dx: number;
  dy: number;
  rotationDeg: number;
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
  /** Metres, the offset that put the body on the origin. Survey cm go through
   *  it to reach the scene. */
  centre: THREE.Vector3;
  floorY: number;
  /** The ring you may walk inside, in world XZ. */
  fence: [number, number][];
  /** Where the instrument stood, in world metres. */
  posts: THREE.Vector3[];
  markers: THREE.Mesh[];
  /** Held movement keys, and where a tap asked us to go. */
  keys: Set<string>;
  goingTo: THREE.Vector3 | null;
  /** Locked at the station while the photograph is up. */
  pinned: boolean;
  at: number | null;
  sky?: THREE.Texture;
  floorFaces: Set<number>;
  last: number;
  saidYaw: number;
  saidAt: number | null;
  /** Connected doors, world XZ. */
  doors: {
    connectionId: string;
    mid: [number, number];
    tangent: [number, number];  // unit, along the doorway's own width
    outward: [number, number];  // unit, away from this room's interior
    halfWidth: number;
  }[];
  ghostGroup: THREE.Group;
  ghostMeshes: THREE.Mesh[];
  /** A lit panel standing in each connected or pickable doorway - the visual
   *  cue for "walk here" or "click here", pulsing so it reads at a glance. */
  doorGlows: THREE.Mesh[];
}

const CM = 0.01;                       // survey centimetres to scene metres

export default function Viewport({
  mesh, selected, onSelect, sketch, look = "orbit", ghost = false, dark = false,
  bounds, stations, floorZ, pano = null, panoOpen = false, onLook,
  doors, ghostRooms, onCrossDoor, enterAt, aimHandle,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const S = useRef<Scene>();
  const cb = useRef({ onSelect, sketch, dark, onLook, onCrossDoor });
  cb.current = { onSelect, sketch, dark, onLook, onCrossDoor };
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

    // Ghosts of connected rooms, world space like the station discs -- not
    // under pivot, since their placement is already computed into this
    // room's local frame before toWorld ever sees it.
    const ghostGroup = new THREE.Group();
    scene.add(ghostGroup);

    const state: Scene = {
      renderer, scene, camera, controls, solid, sketch: sk, lineMats: [],
      faceIds: [], dots: [], lines: [], hovered: null, selected: null,
      sketching: false,
      inside: false, eye: new THREE.Vector3(), yaw: 0, pitch: 0, dark,
      centre: new THREE.Vector3(), floorY: 0, fence: [], posts: [],
      markers: [], keys: new Set(), goingTo: null, pinned: false, at: null,
      floorFaces: new Set(), last: 0, saidYaw: NaN, saidAt: NaN as unknown as null,
      doors: [], ghostGroup, ghostMeshes: [], doorGlows: [],
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
    const tick = (now: number) => {
      if (!alive) return;
      // Movement is integrated against real elapsed time rather than counted
      // in frames, so walking is the same speed on a 60 Hz panel and a 144 Hz
      // one.
      const dt = state.last ? Math.min((now - state.last) / 1000, 0.1) : 0;
      state.last = now;
      // OrbitControls rewrites the camera from its own spherical state on
      // every update, even when disabled. Standing inside the room means
      // driving the camera directly, so it must not run at all.
      if (!state.inside) controls.update();
      else walk(state, dt, cb.current.onLook, cb.current.onCrossDoor);
      if (state.doorGlows.length) {
        const pulse = 0.42 + 0.22 * Math.sin(now / 420);
        for (const g of state.doorGlows) (g.material as THREE.MeshBasicMaterial).opacity = pulse;
      }
      renderer.render(scene, camera);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);

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

    // Everything the survey knows arrives in centimetres about its own origin,
    // and the body has just been moved onto the scene origin. Keep the offset
    // that did it: it is what lets a station or an outline corner be placed
    // exactly where the instrument put it.
    s.centre.copy(c);

    // The bottom of the body is the underside of the floor slab, which is not
    // a floor to stand on. It is only a fallback for a room with no datum.
    const halfH = (bb.max.z - bb.min.z) / 2;
    s.floorY = -halfH;
    s.eye.set(0, s.floorY + 1.6, 0);
    s.solid.add(body);
    s.body = body;
    s.geom = geom;
    s.faceIds = mesh.faceIds;
    // Tapping the floor is how you walk somewhere without a keyboard, so the
    // floor has to be tellable from a wall at pick time.
    s.floorFaces = new Set(
      mesh.faces.filter((f) => f.role === "floor").map((f) => f.id));

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

    // frame() is the orbit-view "fit the whole body in frame" reset. A mesh
    // used to only ever change while looking from outside, so this never had
    // to check - crossing a connected door is the first time it changes
    // while already standing inside, and the entering-through-a-door effect
    // is the one that gets to place the camera then.
    if (!s.sketching && !s.inside)
      frame(s, geom.boundingBox!.getSize(new THREE.Vector3()).length());
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

  /* ---------------- where you may walk, and where to stand ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s || !mesh) return;

    // The surveyed floor datum, which is where a person actually stands. The
    // slab is built downward from it, so the body's own underside is lower by
    // the slab thickness -- a station disc placed there is inside the concrete
    // and only shows once the body is made transparent.
    if (floorZ != null) s.floorY = toWorld(s, 0, 0, floorZ).y;

    s.fence = (bounds ?? []).map(([x, y]) => {
      const w = toWorld(s, x, y, 0);
      return [w.x, w.z] as [number, number];
    });

    s.doors = (doors ?? []).map((d) => {
      const l = toWorld(s, d.left[0], d.left[1], 0);
      const r = toWorld(s, d.right[0], d.right[1], 0);
      const mid: [number, number] = [(l.x + r.x) / 2, (l.z + r.z) / 2];
      const span = Math.hypot(r.x - l.x, r.z - l.z) || 0.01;
      const tangent: [number, number] = [(r.x - l.x) / span, (r.z - l.z) / span];
      let outward: [number, number] = [-tangent[1], tangent[0]];
      // A doorway has two perpendiculars; walk a step down each and keep
      // whichever one lands outside this room's own ring.
      const probe: [number, number] = [mid[0] + outward[0] * 0.3, mid[1] + outward[1] * 0.3];
      if (s.fence.length > 2 && within(s.fence, probe[0], probe[1]))
        outward = [-outward[0], -outward[1]];
      return { connectionId: d.connectionId, mid, tangent, outward, halfWidth: span / 2 };
    });

    for (const g of s.doorGlows) {
      s.scene.remove(g);
      g.geometry.dispose();
      (g.material as THREE.Material).dispose();
    }
    s.doorGlows = (doors ?? []).map((d) => {
      const g = buildDoorGlow(s, d);
      s.scene.add(g);
      return g;
    });

    for (const m of s.markers) {
      s.scene.remove(m);
      m.geometry.dispose();
      (m.material as THREE.Material).dispose();
    }
    s.markers = [];
    s.posts = (stations ?? []).map(([x, y, z]) => toWorld(s, x, y, z));

    // A disc on the floor under each setup. It is somewhere to aim for, and it
    // is the only spot where the photograph taken there is true.
    s.posts.forEach((post, i) => {
      const disc = new THREE.Mesh(
        new THREE.CircleGeometry(0.32, 40),
        new THREE.MeshBasicMaterial({
          color: 0xa87a26, transparent: true, opacity: 0.42,
          depthWrite: false, side: THREE.DoubleSide,
        })
      );
      disc.rotation.x = -Math.PI / 2;
      disc.position.set(post.x, s.floorY + 0.015, post.z);
      disc.renderOrder = 3;
      disc.userData.post = i;
      s.scene.add(disc);
      s.markers.push(disc);
    });
  }, [bounds, stations, floorZ, mesh, doors]);

  /* ---------------- ghosts of connected rooms ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s) return;
    for (const m of s.ghostMeshes) {
      s.ghostGroup.remove(m);
      m.geometry.dispose();
      (m.material as THREE.Material).dispose();
    }
    s.ghostMeshes = (ghostRooms ?? [])
      .filter((g) => g.outline.length >= 3)
      .map((g) => {
        const built = buildGhostMesh(s, g, floorZ ?? 0);
        built.userData.connectionId = g.connectionId;
        s.ghostGroup.add(built);
        return built;
      });
  }, [ghostRooms, floorZ, mesh]);

  /* ---------------- the photograph ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s) return;
    s.sky?.dispose();
    s.sky = undefined;
    if (!pano) {
      s.scene.background = null;
      return;
    }
    const tex = new THREE.TextureLoader().load(pano.url);
    tex.mapping = THREE.EquirectangularReflectionMapping;
    tex.colorSpace = THREE.SRGBColorSpace;
    s.sky = tex;
  }, [pano?.url]);

  useEffect(() => {
    const s = S.current;
    if (!s) return;
    const showing = !!panoOpen && !!pano && !!s.sky;
    s.scene.background = showing ? s.sky! : null;
    // Three samples the background the same way round as the survey, so only
    // the offset differs: image column zero faces the solved heading.
    if (showing) s.scene.backgroundRotation.y = pano!.heading - Math.PI;
    s.pinned = showing;
    if (showing) s.at = pano!.station;
    // The body would sit in front of the photograph and hide it.
    if (s.body) s.solid.visible = !showing && !sketch;
    for (const m of s.markers) m.visible = !showing;
  }, [panoOpen, pano, sketch, mesh]);

  /* ---------------- stand inside the room ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s) return;
    const wantInside = look === "inside" && !sketch && !!s.body;
    const sig = `${wantInside}|${!!sketch}|${!!s.body}|${s.posts.length}`;
    if (viewRef.current === sig) return;      // nothing about the view changed
    viewRef.current = sig;

    s.inside = wantInside;
    s.controls.enabled = !wantInside;

    if (wantInside) {
      s.yaw = 0;
      s.pitch = 0;
      s.keys.clear();
      s.goingTo = null;
      // Start where the surveyor stood, when the survey says. It is the one
      // spot in the room that has a photograph to be compared against.
      const start = s.posts[0];
      if (start) s.eye.set(start.x, s.floorY + EYE, start.z);
      else s.eye.set(0, s.floorY + EYE, 0);
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

  /* ---------------- entering through a connected door ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s || !enterAt || !s.inside) return;
    // enterAt.yaw already carries your heading across the connection's own
    // rotation (the caller's job, not this component's - it is the only
    // side that knows the transform), so this is a plain teleport to it.
    const p = toWorld(s, enterAt.x, enterAt.y, 0);
    s.eye.set(p.x, s.floorY + EYE, p.z);
    s.camera.position.copy(s.eye);
    s.yaw = enterAt.yaw;
    s.pitch = 0;
    s.camera.rotation.set(0, 0, 0);
    s.camera.rotateY(s.yaw);
    s.goingTo = null;
  }, [enterAt]);

  /* ---------------- selection from outside ---------------- */
  useEffect(() => {
    const s = S.current;
    if (!s || !s.geom) return;
    s.selected = selected;
    paint(s, selected, s.hovered);
  }, [selected, mesh]);

  /* ---------------- walking ---------------- */
  useEffect(() => {
    const held = (e: KeyboardEvent, on: boolean) => {
      const s = S.current;
      if (!s?.inside || s.pinned) return;
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k !== "w" && k !== "a" && k !== "s" && k !== "d") return;
      if (on) s.keys.add(k);
      else s.keys.delete(k);
      e.preventDefault();
    };
    const down = (e: KeyboardEvent) => held(e, true);
    const up = (e: KeyboardEvent) => held(e, false);
    // A window that loses focus mid-stride would otherwise walk for ever.
    const stop = () => S.current?.keys.clear();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", stop);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", stop);
    };
  }, []);

  /* ---------------- picking ---------------- */
  useEffect(() => {
    const s = S.current;
    const el = host.current;
    if (!s || !el) return;

    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let downAt = { x: 0, y: 0 };
    let onDot = false;
    /* Inside view has no OrbitControls (it is disabled there), so pinch
     * zoom gets nothing for free the way orbit mode's does - it has to be
     * tracked here, by pointer id, same as OrbitControls does internally. */
    const pinch = new Map<number, { x: number; y: number }>();
    let lastPinchDist = 0;
    let gesturePinched = false;

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

    // What the crosshair is pointing at, in survey centimetres.
    //
    // Straight down the middle of the view rather than at a finger: standing
    // in the room and aiming is the whole gesture, and on a tablet a fingertip
    // covers the very thing being aimed at.
    const aimCentre = (): AimHit | null => {
      if (!s.body || !s.solid.visible) return null;
      ndc.x = 0;
      ndc.y = 0;
      ray.setFromCamera(ndc, s.camera);
      const hit = ray.intersectObject(s.body, false)[0];
      if (!hit) return null;
      return toSurvey(s, hit.point);
    };
    if (aimHandle) aimHandle.current = aimCentre;

    const markerUnder = (e: PointerEvent): number | null => {
      if (!s.markers.length || !s.inside) return null;
      aim(e);
      const hit = ray.intersectObjects(s.markers, false)[0];
      return hit ? (hit.object.userData.post as number) : null;
    };

    /* The glow panel itself is the hit target, in orbit view as much as
     * inside - not the whole translucent ghost room, which would say yes to
     * a tap anywhere on it and give no way to tell one candidate door from
     * another. */
    const doorGlowUnder = (e: PointerEvent): string | null => {
      if (!s.doorGlows.length) return null;
      aim(e);
      const hit = ray.intersectObjects(s.doorGlows, false)[0];
      return hit ? (hit.object.userData.connectionId as string) : null;
    };

    const bodyUnder = (e: PointerEvent) => {
      if (!s.body || !s.solid.visible) return null;
      aim(e);
      return ray.intersectObject(s.body, false)[0] ?? null;
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
        if (pinch.has(e.pointerId)) {
          pinch.set(e.pointerId, { x: e.clientX, y: e.clientY });
          if (pinch.size >= 2) {
            const [a, b] = Array.from(pinch.values());
            const dist = Math.hypot(a.x - b.x, a.y - b.y);
            // Fingers spreading apart narrows the fov (zooms in); the first
            // sample after a finger touches down has no prior distance to
            // diff against, so it only sets the baseline.
            if (lastPinchDist > 0) {
              s.camera.fov = Math.max(35, Math.min(95,
                s.camera.fov - (dist - lastPinchDist) * 0.15));
              s.camera.updateProjectionMatrix();
            }
            lastPinchDist = dist;
            el.style.cursor = "grabbing";
            return;
          }
        }
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
    };

    const wheel = (e: WheelEvent) => {
      if (!s.inside) return;
      e.preventDefault();
      s.camera.fov = Math.max(35, Math.min(95, s.camera.fov + Math.sign(e.deltaY) * 3));
      s.camera.updateProjectionMatrix();
    };

    const down = (e: PointerEvent) => {
      if (s.inside) {
        pinch.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (pinch.size >= 2) {
          // A second finger landing mid-look is a pinch starting, not two
          // people trying to look around at once.
          gesturePinched = true;
          looking = false;
          lastPinchDist = 0;
        } else {
          looking = true;
          lastAt = { x: e.clientX, y: e.clientY };
        }
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
        pinch.delete(e.pointerId);
        el.releasePointerCapture?.(e.pointerId);
        if (pinch.size === 1) {
          // One finger still down after a pinch: keep looking from where
          // that finger already is, rather than jumping to wherever it
          // first touched down.
          const [remaining] = pinch.values();
          looking = true;
          lastAt = remaining;
          return;
        }
        looking = false;
        lastPinchDist = 0;
        if (gesturePinched) { gesturePinched = false; return; }
        if (moved || s.pinned) return;

        // A tap on a glowing door crosses into the room beyond it, same as
        // walking through the doorway would.
        const doorId = doorGlowUnder(e);
        if (doorId != null) { cb.current.onCrossDoor?.(doorId); return; }

        // A tap on a station disc walks you to where the instrument stood.
        const post = markerUnder(e);
        if (post != null) {
          s.goingTo = s.posts[post].clone();
          return;
        }
        // A tap on the floor walks you there, which is how a phone gets around
        // a room with no keyboard on it. A tap on a wall still selects it.
        const hit = bodyUnder(e);
        const id = hit?.faceIndex != null ? s.faceIds[hit.faceIndex] ?? null : null;
        if (hit && id != null && s.floorFaces.has(id)) {
          s.goingTo = new THREE.Vector3(hit.point.x, s.floorY + EYE, hit.point.z);
          return;
        }
        cb.current.onSelect(id);
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
      // A glowing door reads from outside the room just as it does from
      // inside it - orbiting around a body to find its doors is normal.
      const doorId = doorGlowUnder(e);
      if (doorId != null) { cb.current.onCrossDoor?.(doorId); return; }
      cb.current.onSelect(faceUnder(e));
    };

    const cancel = (e: PointerEvent) => {
      if (!s.inside) s.controls.enabled = true;
      else {
        pinch.delete(e.pointerId);
        if (pinch.size < 2) { looking = false; lastPinchDist = 0; gesturePinched = false; }
      }
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

/* ---------------- standing in the room ---------------- */

const SPEED = 2.4;      // metres a second: an unhurried walk, not a sprint
const EYE = 1.6;        // metres above the floor, standing
const SNAP = 0.5;       // metres: near enough to a station to be at it

/**
 * Survey centimetres to scene metres.
 *
 * The survey is Z-up about its own origin; the scene is Y-up with the body
 * moved onto the origin. Both steps are folded in here so nothing else has to
 * think about it.
 */
/** The inverse of toWorld: a place in the scene, back in survey centimetres. */
function toSurvey(s: Scene, v: THREE.Vector3): AimHit {
  return {
    x: (v.x + s.centre.x) / CM,
    y: (s.centre.y - v.z) / CM,
    z: (v.y + s.centre.z) / CM,
  };
}

function toWorld(s: Scene, x: number, y: number, z: number): THREE.Vector3 {
  return new THREE.Vector3(
    x * CM - s.centre.x,
    z * CM - s.centre.z,
    -(y * CM - s.centre.y),
  );
}

// cm above the survey's own z=0, same baseline the door markers use - tall
// enough to read as a doorway without claiming to be the room's real height.
const DOOR_GLOW_HEIGHT = 210;

/** A lit panel filling a doorway, survey centimetres in, world metres out. */
function buildDoorGlow(s: Scene, d: DoorLink): THREE.Mesh {
  const bl = toWorld(s, d.left[0], d.left[1], 0);
  const br = toWorld(s, d.right[0], d.right[1], 0);
  const tl = toWorld(s, d.left[0], d.left[1], DOOR_GLOW_HEIGHT);
  const tr = toWorld(s, d.right[0], d.right[1], DOOR_GLOW_HEIGHT);

  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute([
    bl.x, bl.y, bl.z, br.x, br.y, br.z, tr.x, tr.y, tr.z,
    bl.x, bl.y, bl.z, tr.x, tr.y, tr.z, tl.x, tl.y, tl.z,
  ], 3));

  const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
    color: 0xC99B3F, transparent: true, opacity: 0.5,
    side: THREE.DoubleSide, depthWrite: false,
  }));
  mesh.renderOrder = 4;
  mesh.userData.connectionId = d.connectionId;
  return mesh;
}

/**
 * A faded wall loop for a connected room's outline, placed into the current
 * room's local frame (rotate then translate, both in survey centimetres)
 * before going through the same toWorld every other marker uses.
 *
 * Just the walls, not the fixtures or the exact B-rep: this is a "a room
 * continues beyond this door" cue, not a second body to measure from.
 */
function buildGhostMesh(s: Scene, g: GhostRoom, fallbackFloorZ: number): THREE.Mesh {
  const rad = (g.rotationDeg * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  const floorZ = g.floorZ ?? fallbackFloorZ;
  const ceilZ = floorZ + (g.ceilingHeight ?? 270);

  const bottom: THREE.Vector3[] = [];
  const top: THREE.Vector3[] = [];
  for (const [x, y] of g.outline) {
    const rx = x * cos - y * sin + g.dx;
    const ry = x * sin + y * cos + g.dy;
    bottom.push(toWorld(s, rx, ry, floorZ));
    top.push(toWorld(s, rx, ry, ceilZ));
  }

  const positions: number[] = [];
  const n = g.outline.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const quad = [bottom[i], bottom[j], top[j], bottom[i], top[j], top[i]];
    for (const p of quad) positions.push(p.x, p.y, p.z);
  }

  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geom.computeVertexNormals();
  const mesh = new THREE.Mesh(
    geom,
    new THREE.MeshStandardMaterial({
      color: 0xa87a26, transparent: true, opacity: 0.28,
      side: THREE.DoubleSide, depthWrite: false,
    })
  );
  mesh.renderOrder = 2;
  return mesh;
}

/** Whether a world XZ point is inside the surveyed ring. */
function within(fence: [number, number][], x: number, z: number): boolean {
  let hit = false;
  for (let i = 0, j = fence.length - 1; i < fence.length; j = i++) {
    const [xi, zi] = fence[i];
    const [xj, zj] = fence[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) {
      hit = !hit;
    }
  }
  return hit;
}

/**
 * Move the eye for this frame.
 *
 * The room is the only thing stopping you: the surveyed ring is a real
 * polygon, so a wall is a wall. A blocked move is retried one axis at a time,
 * which turns walking into a wall into sliding along it rather than sticking
 * to it.
 */
// Extra clearance on each side of a doorway's own width, so the fence still
// stops you either side of a connected door but not for stepping through it
// slightly off-centre - a real doorway is forgiving that way too.
const DOOR_MARGIN = 0.25;
// Metres past the wall line, along the doorway, that counts as having
// actually walked through - not just approached. Short of the far room's
// own furniture, long enough that brushing the opening does not fire it.
const DOOR_CROSS_DEPTH = 0.4;

function walk(
  s: Scene,
  dt: number,
  onLook?: (look: { yaw: number; at: number | null }) => void,
  onCrossDoor?: (connectionId: string) => void,
): void {
  if (dt) {
    const from = s.camera.position.clone();
    const to = from.clone();

    if (s.pinned && s.at != null && s.posts[s.at]) {
      // The photograph is only true from where it was taken, so while it is up
      // the eye is held exactly there.
      to.copy(s.posts[s.at]);
    } else {
      let fwd = 0;
      let side = 0;
      if (s.keys.has("w")) fwd += 1;
      if (s.keys.has("s")) fwd -= 1;
      if (s.keys.has("d")) side += 1;
      if (s.keys.has("a")) side -= 1;

      if (fwd || side) {
        s.goingTo = null;               // the keys overrule a tap in flight
        const sin = Math.sin(s.yaw);
        const cos = Math.cos(s.yaw);
        // Forward is where the eye points, flattened onto the floor.
        const dx = -sin * fwd + cos * side;
        const dz = -cos * fwd - sin * side;
        const len = Math.hypot(dx, dz) || 1;
        to.x += (dx / len) * SPEED * dt;
        to.z += (dz / len) * SPEED * dt;
      } else if (s.goingTo) {
        const step = s.goingTo.clone().sub(from);
        step.y = 0;
        const far = step.length();
        if (far < 0.06) s.goingTo = null;
        else to.add(step.multiplyScalar(Math.min(1, (SPEED * 1.7 * dt) / far)));
      }

      to.y = s.floorY + EYE;

      // Walking toward a connected door should feel like walking through a
      // doorway, not bumping a trigger near it: free passage down its own
      // corridor regardless of the fence, and the room only actually changes
      // once you have come out the far side of the wall line.
      let inDoorway = false;
      for (const door of s.doors) {
        const dx = to.x - door.mid[0], dz = to.z - door.mid[1];
        const lateral = dx * door.tangent[0] + dz * door.tangent[1];
        if (Math.abs(lateral) > door.halfWidth + DOOR_MARGIN) continue;
        inDoorway = true;
        const depth = dx * door.outward[0] + dz * door.outward[1];
        if (depth > DOOR_CROSS_DEPTH) {
          onCrossDoor?.(door.connectionId);
          s.goingTo = null;
          return;
        }
      }

      if (!inDoorway && s.fence.length > 2 && !within(s.fence, to.x, to.z)) {
        if (within(s.fence, to.x, from.z)) to.z = from.z;
        else if (within(s.fence, from.x, to.z)) to.x = from.x;
        else {
          to.x = from.x;
          to.z = from.z;
          s.goingTo = null;
        }
      }
    }

    s.camera.position.copy(to);
    s.eye.copy(to);
  }

  // Which station we are standing at, if any. The panorama chip needs it, and
  // so does the decision about whether the photograph can be trusted at all.
  let at: number | null = null;
  let best = SNAP;
  for (let i = 0; i < s.posts.length; i++) {
    const d = Math.hypot(
      s.posts[i].x - s.camera.position.x,
      s.posts[i].z - s.camera.position.z,
    );
    if (d < best) {
      best = d;
      at = i;
    }
  }
  s.at = at;
  for (let i = 0; i < s.markers.length; i++) {
    const m = s.markers[i].material as THREE.MeshBasicMaterial;
    m.opacity = i === at ? 0.9 : 0.42;
  }

  // React must not be re-rendered sixty times a second for a camera that has
  // barely moved.
  if (onLook && (Math.abs(s.yaw - s.saidYaw) > 0.008 || at !== s.saidAt)) {
    s.saidYaw = s.yaw;
    s.saidAt = at;
    onLook({ yaw: s.yaw, at });
  }
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
