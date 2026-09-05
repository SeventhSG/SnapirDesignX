import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, panoramaUrl, type BuildResult, type Connection, type Crossing,
         type Project, type Room, type Status } from "./api";
import { t, type Key, type Lang } from "./i18n";
import Sketch, { type EditMode } from "./Sketch";
import Viewport, { ROLE_COLOR, type AimHit, type DoorLink,
         type GhostRoom } from "./Viewport";
import { solveRoom, type Pose } from "./panorama";

/** A room's own floor outline, resolved from point names to coordinates. */
function outlinePoints(r: Room): [number, number][] {
  const named = new Map(r.points.map((p) => [p.name, p]));
  return r.outline
    .map((n) => named.get(n))
    .filter((p): p is NonNullable<typeof p> => !!p)
    .map((p) => [p.x, p.y] as [number, number]);
}

function centroid(pts: [number, number][]): [number, number] {
  let sx = 0, sy = 0;
  for (const [x, y] of pts) { sx += x; sy += y; }
  return pts.length ? [sx / pts.length, sy / pts.length] : [0, 0];
}

/** Ray-cast point-in-polygon, same test the viewport uses for walking
 *  collision - exact for a concave outline (an L, a U), unlike a straight
 *  line to the centroid, which such a shape can put on the wrong side of a
 *  wall entirely. */
function pointInPolygon(poly: [number, number][], x: number, y: number): boolean {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

/** A door's midpoint and the direction pointing into its own room, survey cm. */
function doorFrame(r: Room, openingIndex: number) {
  const o = r.openings[openingIndex];
  const mid: [number, number] = [(o.left[0] + o.right[0]) / 2, (o.left[1] + o.right[1]) / 2];
  const dx = o.right[0] - o.left[0], dy = o.right[1] - o.left[1];
  const len = Math.hypot(dx, dy) || 1;
  let nx = -dy / len, ny = dx / len;
  // Either perpendicular could be "inward" - a short step down one either
  // lands inside the room's own outline or it doesn't, which holds for any
  // shape, unlike guessing from the centroid.
  const outline = outlinePoints(r);
  if (outline.length > 2) {
    const probe: [number, number] = [mid[0] + nx * 30, mid[1] + ny * 30];
    if (!pointInPolygon(outline, probe[0], probe[1])) { nx = -nx; ny = -ny; }
  } else {
    const [cx, cy] = centroid(outline);
    if (nx * (cx - mid[0]) + ny * (cy - mid[1]) < 0) { nx = -nx; ny = -ny; }
  }
  return { mid, dir: [dx / len, dy / len] as [number, number], normal: [nx, ny] as [number, number] };
}

/** Room B's placement in room A's local frame that lines their two doorways
 *  up, facing each other - the default a new connection starts from. */
function alignDoors(roomA: Room, openingA: number, roomB: Room, openingB: number) {
  const a = doorFrame(roomA, openingA);
  const b = doorFrame(roomB, openingB);
  // Aligning the doors' own left/right tangent only makes them coincide - it
  // says nothing about which side either room's interior ends up on, and
  // that side is an arbitrary survey convention independent per room, so
  // that alone lands room B inside room A as often as not. What has to line
  // up is the normals: B's own inward direction, rotated, has to point the
  // opposite way from A's, so the two interiors open away from each other.
  const angleA = Math.atan2(a.normal[1], a.normal[0]);
  const angleB = Math.atan2(b.normal[1], b.normal[0]);
  const rotation = angleA + Math.PI - angleB;
  const cos = Math.cos(rotation), sin = Math.sin(rotation);
  const rbx = b.mid[0] * cos - b.mid[1] * sin;
  const rby = b.mid[0] * sin + b.mid[1] * cos;
  return { dx: a.mid[0] - rbx, dy: a.mid[1] - rby, rotationDeg: (rotation * 180) / Math.PI };
}

/** The same rigid placement, seen from the other room: if this places B in
 *  A's frame, the inverse places A in B's frame. */
function invertTransform(t: { dx: number; dy: number; rotationDeg: number }) {
  const rad = (t.rotationDeg * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  return {
    dx: -(t.dx * cos + t.dy * sin),
    dy: -(-t.dx * sin + t.dy * cos),
    rotationDeg: -t.rotationDeg,
  };
}

/** A point in room B's own frame, placed into room A's frame by the same
 *  rigid transform the ghost mesh itself is built with (rotate, then
 *  translate) - so a door marker computed here lands exactly on the ghost. */
function applyTransform(
  p: [number, number], t: { dx: number; dy: number; rotationDeg: number },
): [number, number] {
  const rad = (t.rotationDeg * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  return [p[0] * cos - p[1] * sin + t.dx, p[0] * sin + p[1] * cos + t.dy];
}

/** Where room B sits before either of you has picked its door: parked just
 *  outside door A, facing square on, so its own doors are in view and
 *  clickable. Picking a door there replaces this with alignDoors' exact fit. */
function parkBeside(roomA: Room, openingA: number, roomB: Room) {
  const a = doorFrame(roomA, openingA);
  const bOutline = outlinePoints(roomB);
  const [cx, cy] = centroid(bOutline);
  // Room B sits at rotation 0, whichever way that turns out to face, so the
  // clearance has to hold for every point in its outline, not just its
  // centroid - its own bounding radius past the door, plus a clear margin.
  let radius = 0;
  for (const [x, y] of bOutline) radius = Math.max(radius, Math.hypot(x - cx, y - cy));
  const standoff = radius + 300;
  // a.normal points into room A, not out of it - away from A is the other way.
  const targetX = a.mid[0] - a.normal[0] * standoff;
  const targetY = a.mid[1] - a.normal[1] * standoff;
  return { dx: targetX - cx, dy: targetY - cy, rotationDeg: 0 };
}

/** Carry a walking heading across a connection's rigid transform, so walking
 *  "forward" through a door keeps feeling forward on the far side instead of
 *  keeping the same raw world angle - the two rooms share no coordinate
 *  frame, so that number means nothing between them on its own. */
function rotateYaw(yaw: number, deltaDeg: number): number {
  // Inverse of toWorld's fixed y-to-z flip (see Viewport's own comment by
  // the same name): recover the survey-space direction this yaw represents.
  const nx = -Math.sin(yaw), ny = Math.cos(yaw);
  const rad = (deltaDeg * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  const rx = nx * cos - ny * sin, ry = nx * sin + ny * cos;
  return Math.atan2(-rx, ry);
}

/** Where to stand just inside the target room, survey centimetres. */
function entryPoint(target: Room, openingIndex: number) {
  const { mid, normal } = doorFrame(target, openingIndex);
  const STAND_OFF = 90;  // cm past the threshold, clear of the door trigger
  return { x: mid[0] + normal[0] * STAND_OFF, y: mid[1] + normal[1] * STAND_OFF };
}

const bridge = (window as any).snapir;

/* The real mark, traced from the logo. currentColor so it works anywhere. */
const MARK_D =
  "M27.48 17.73 L27.48 27.84 L12.77 42.73 L47.52 42.73 L67.38 22.87 L67.38 22.16 " +
  "L72.52 17.73 L100.00 44.86 L100.00 82.45 L92.55 82.45 L92.55 47.16 L72.52 27.84 " +
  "L53.19 47.16 L53.19 82.45 L45.74 82.45 L45.74 50.53 L7.45 50.53 L7.45 82.45 " +
  "L0.00 82.45 L0.00 44.86Z";

function Mark({ className = "mk" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 100 100" aria-hidden="true" fill="currentColor">
      <path fillRule="evenodd" d={MARK_D} />
    </svg>
  );
}

type Theme = "light" | "dark";

type Screen = "launch" | "home" | "projects" | "rooms" | "flat" | "work"
  | "project" | "settings";

/** Roles the operator can assign, in the order they appear in the picker. */
const ROLES: { role: string; key: Key }[] = [
  { role: "floor", key: "rFloor" },
  { role: "ceiling", key: "rCeiling" },
  { role: "opening", key: "rOpening" },
  { role: "socket", key: "rSocket" },
  { role: "plumbing", key: "rPlumbing" },
  { role: "control", key: "rControl" },
];

// Four formats, for four different jobs. STEP is the body to work from and
// comes back through the kernel exactly. STL is triangles, for opening the
// room in something that will not read a STEP file. DXF is a plan with every
// element - floor, ceiling, each wall, each fixture - on its own layer, for
// AutoCAD or anything else that only wants a 2D drawing. GLB carries that
// same split as real solid meshes instead of 2D lines, for SketchUp and
// anything else with no STEP/IGES importer.
const EXPORT_FORMATS = [
  { id: "step", label: "STEP", suffix: ".step" },
  { id: "stl", label: "STL", suffix: ".stl" },
  { id: "dxf", label: "DXF", suffix: ".dxf" },
  { id: "glb", label: "GLB", suffix: ".glb" },
];
const STEP_SCHEMAS = ["AP203", "AP214", "AP242"];

const fmtLabel = (fmt: string, schema: string) =>
  fmt === "step" ? `STEP ${schema}`
                 : (EXPORT_FORMATS.find((f) => f.id === fmt)?.label ?? fmt);

export default function App() {
  const [lang, setLang] = useState<Lang>(
    () => (localStorage.getItem("lang") as Lang) || "en");
  const T = useCallback((k: Key) => t(lang, k), [lang]);

  const pickFmt = (f: string) => { setFmt(f); localStorage.setItem("exportFormat", f); };
  const pickSchema = (v: string) => { setSchema(v); localStorage.setItem("stepSchema", v); };

  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme) || "light");
  const [dark, setDark] = useState(false);

  const [screen, setScreen] = useState<Screen>("launch");
  const [bootError, setBootError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; bad?: boolean } | null>(null);

  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<{ id: string; name: string; thickness: number } | null>(null);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [flat, setFlat] = useState("");        // the flat being browsed
  const [room, setRoom] = useState<Room | null>(null);
  const [switcher, setSwitcher] = useState(false);  // sibling rooms popover
  const [result, setResult] = useState<BuildResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingAll, setLoadingAll] = useState(false);

  const [face, setFace] = useState<number | null>(null);
  const [tool, setTool] = useState<"face" | "sketch">("face");
  const [view, setView] = useState<"2d" | "3d">("3d");
  const [edit, setEdit] = useState<EditMode>("outline");
  /* Move mode: the axis handles on the selected point. Off by default, and
     only reachable from Layer mode - a shot is where the instrument said it
     is, so putting it somewhere else has to be a decision, not a slip. */
  const [axisMove, setAxisMove] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [lineSel, setLineSel] = useState<[string, string] | null>(null);
  const [ring, setRing] = useState<string[]>([]);
  const [pointName, setPointName] = useState<string | null>(null);
  const [look, setLook] = useState<"orbit" | "inside">("orbit");
  /** Standing in the room with the crosshair up, ready to add what was missed. */
  const [aiming, setAiming] = useState(false);
  const aimHandle = useRef<(() => AimHit | null) | null>(null);
  const [ghost, setGhost] = useState(false);
  /* Doors hooked to other rooms, for the whole project (a connection can
     point at any room, not just the current one's flat-mates), whether the
     walkthrough is allowed to use them right now, where crossing one should
     stand you, and the door being wired up in the connect tool. */
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectedMode, setConnectedMode] = useState(false);
  const [enterAt, setEnterAt] = useState<{ x: number; y: number; yaw: number } | null>(null);
  const [doorsOpen, setDoorsOpen] = useState(false);
  const [connecting, setConnecting] = useState<number | null>(null);
  /* Room B, once picked - the door itself is picked in the viewport, not from
     a list, so nothing here names it until a glowing door is clicked there. */
  const [connectTo, setConnectTo] = useState<string | null>(null);
  const [pendingOpeningB, setPendingOpeningB] = useState<number | null>(null);
  /* The panoramas whose heading was recovered, where the eye is standing now,
     and whether the photograph is up instead of the body. */
  const [poses, setPoses] = useState<Pose[]>([]);
  const [solving, setSolving] = useState(false);
  const [panoOpen, setPanoOpen] = useState(false);
  const [eye, setEye] = useState<{ yaw: number; at: number | null }>(
    { yaw: 0, at: null });
  const [panoWarn, setPanoWarn] = useState(false);

  /* The ring you may walk inside, and the setups you may stand at. */
  const bounds = useMemo<[number, number][]>(() => {
    if (!room) return [];
    const named = new Map(room.points.map((p) => [p.name, p]));
    return room.outline
      .map((n) => named.get(n))
      .filter((p): p is NonNullable<typeof p> => !!p)
      .map((p) => [p.x, p.y] as [number, number]);
  }, [room]);
  const posts = useMemo<[number, number, number][]>(
    () => (room?.stations ?? []).map((s) => [s.x, s.y, s.z]), [room]);

  /* The shot for wherever the eye is standing, and where in it we are looking.
     A room with no solved pose still gets its picture; it just does not claim
     to know which way round it is. */
  const pose = poses.find((p) => p.station === (eye.at ?? 0)) ?? poses[0] ?? null;
  const panoUrl = project && room && room.panoramas > 0
    ? panoramaUrl(project.id, room.name, pose ? pose.panorama : 0)
    : null;


  const [fmt, setFmt] = useState(
    () => localStorage.getItem("exportFormat") || "step");
  const [schema, setSchema] = useState(
    () => localStorage.getItem("stepSchema") || "AP214");

  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [tab, setTab] = useState("build");
  const [addedLines, setAddedLines] = useState<[string, string][]>([]);
  const [droppedLines, setDroppedLines] = useState<[string, string][]>([]);
  const [droppedPoints, setDroppedPoints] = useState<string[]>([]);
  const [draftName, setDraftName] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);

  useEffect(() => localStorage.setItem("lang", lang), [lang]);

  /* Theme: an explicit choice wins, otherwise follow the OS and keep
     following it if the user changes it while the app is open. */
  useEffect(() => {
    localStorage.setItem("theme", theme);
    const isDark = theme === "dark";
    setDark(isDark);
    document.documentElement.setAttribute("data-theme", theme);
    bridge?.setTheme?.(isDark);
  }, [theme]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(id);
  }, [toast]);

  const say = (msg: string, bad = false) => setToast({ msg, bad });

  /* ---------------- boot ---------------- */
  const boot = useCallback(async () => {
    setBootError(null);
    const started = Date.now();
    const r = bridge ? await bridge.backendReady() : { ok: true };
    if (!r.ok) { setBootError(r.error); return; }
    try {
      const list = await api.projects();
      // Hold the splash for its full run rather than flashing it for a frame.
      const left = 5000 - (Date.now() - started);
      if (left > 0) await new Promise((res) => setTimeout(res, left));
      setProjects(list);
      setScreen("home");
    } catch (e) { setBootError(String((e as Error).message)); }
  }, []);
  useEffect(() => { void boot(); }, [boot]);

  /* Leaving the inside view puts the model back: the photograph is only
     meaningful from where it was taken. */
  useEffect(() => {
    if (look !== "inside") setPanoOpen(false);
  }, [look]);

  /* A photograph that could not be lined up says so on opening and then stops
     saying it. Standing in a permanent warning helps nobody. */
  useEffect(() => {
    if (!panoOpen || pose) { setPanoWarn(false); return; }
    setPanoWarn(true);
    const t = setTimeout(() => setPanoWarn(false), 5000);
    return () => clearTimeout(t);
  }, [panoOpen, pose]);

  /* The panorama's heading is in none of the survey files, so it is recovered
     from the picture itself the first time a room is opened. One decode per
     shot, and the answer never changes, so it is done once and kept. */
  useEffect(() => {
    setPoses([]);
    setPanoOpen(false);
    if (!project || !room || !room.panoramas || !room.stations.length) return;
    const id = project.id;
    const name = room.name;
    let alive = true;
    setSolving(true);
    solveRoom(room, (i) => panoramaUrl(id, name, i))
      .then((p) => { if (alive) setPoses(p); })
      .catch(() => { /* a shot we cannot read simply does not line up */ })
      .finally(() => { if (alive) setSolving(false); });
    return () => { alive = false; };
  }, [project?.id, room?.name, room?.panoramas, room?.stations.length]);

  /* ---------------- projects and rooms ---------------- */
  const openProject = async (id: string) => {
    setBusy(true);
    try {
      const data = await api.rooms(id);
      setProject({ id: data.id, name: data.name, thickness: data.thickness });
      setRooms(data.rooms);
      setFlat(data.rooms[0]?.flat ?? "");
      setScreen("rooms");
      api.connections(id).then((c) => setConnections(c.connections)).catch(() => {});
    } catch (e) { say((e as Error).message, true); }
    finally { setBusy(false); }
  };

  const newProject = async () => {
    const folder = await bridge?.pickFolder();
    if (!folder) return;
    try {
      const { id } = await api.createProject(folder);
      setProjects(await api.projects());
      await openProject(id);
    } catch (e) { say((e as Error).message, true); }
  };

  /* A portable .sdxp: survey folder plus every override and connection,
   * zipped so the project opens on another device with nothing else needed. */
  const exportProject = async (p: Pick<Project, "id" | "name">) => {
    try {
      const r = await api.exportSdxp(p.id);
      say(`${T("exportedProjectTo")} · ${(r.bytes / 1024).toFixed(0)} KB`);
      bridge?.reveal(r.path);
    } catch (e) { say((e as Error).message, true); }
  };

  const importProject = async () => {
    const picked = await bridge?.pickSdxp();
    if (!picked) return;
    try {
      const { id } = await api.importSdxp(picked);
      setProjects(await api.projects());
      say(T("importedProject"));
      await openProject(id);
    } catch (e) { say((e as Error).message, true); }
  };

  const openFlat = (name: string) => { setFlat(name); setScreen("flat"); };

  /* Back out of the workspace to wherever the room came from. */
  const leaveRoom = () => setScreen(grouped ? "flat" : "rooms");

  const openRoom = async (r: Room) => {
    setFlat(r.flat);
    setSwitcher(false);
    setRoom(r);
    setRing(r.outline);
    setFace(null);
    setPointName(null);
    setPending(null);
    setLineSel(null);
    setAddedLines([]); setDroppedLines([]); setDroppedPoints([]);
    applied.current = "";
    setResult(null);
    setTool("face");
    setScreen("work");
    if (r.status !== "needs-you") void buildRoom(r);
  };

  const buildRoom = async (r: Room) => {
    if (!project) return;
    setBusy(true);
    try { setResult(await api.build(project.id, r.name)); }
    catch (e) { setResult(null); say((e as Error).message, true); }
    finally { setBusy(false); }
  };

  /** Builds every buildable room in this flat, one at a time, so crossing a
   *  connected door later never sits on a first build - a room already known
   *  to need the operator's input is skipped, since building it would just
   *  fail. */
  const loadAllRooms = async () => {
    if (!project || !room) return;
    setLoadingAll(true);
    let failed = 0;
    for (const r of rooms.filter((x) => x.flat === room.flat && x.status !== "needs-you")) {
      try { await api.build(project.id, r.name); }
      catch { failed++; }
    }
    setLoadingAll(false);
    say(failed ? `${failed} ${T("roomsFailedToLoad")}` : T("allRoomsLoaded"));
  };

  const patch = async (body: Record<string, unknown>, keepRing = false) => {
    if (!project || !room) return;
    try {
      const updated = await api.patchRoom(project.id, room.name, body);
      setRoom(updated);
      if (!keepRing) setRing(updated.outline);
      setRooms((rs) => rs.map((x) => (x.name === updated.name ? updated : x)));
      if (updated.status !== "needs-you") await buildRoom(updated);
      else setResult(null);
    } catch (e) { say((e as Error).message, true); }
  };

  const setRole = (name: string, role: string) =>
    patch({ roleOverrides: { [name]: role } }, true);

  /** Say what a rectangle on a wall actually is. Keyed by the points it was
   *  built from, so the answer sticks across every later rebuild. */
  const setOpeningKind = (key: string, kind: string) =>
    patch({ openingKindOverrides: { [key]: kind } }, true);

  /**
   * Add a point where the crosshair is pointing.
   *
   * For the corner nobody shot: stand in the room, turn the panorama on to see
   * what is actually there, aim, and put a point on it. It is constructed, not
   * measured, so it is marked that way and left unclassified for the operator
   * to say what it is.
   */
  const addAimedPoint = async () => {
    if (!room) return;
    const at = aimHandle.current?.();
    if (!at) { say(T("aimNothing"), true); return; }

    const name = nextDerived();
    const derived = [
      ...room.points.filter((p) => p.derived)
        .map((p) => ({ name: p.name, x: p.x, y: p.y, z: p.z,
                       role: p.role, from: p.source })),
      { name, x: +at.x.toFixed(2), y: +at.y.toFixed(2), z: +at.z.toFixed(2),
        role: "unknown", from: "added from inside the room" },
    ];
    await patch({ derivedPoints: derived }, true);
    say(`${T("pointAdded")} ${name}`);
  };

  /** Round or square. The survey cannot tell, so the operator does. */
  const setOpeningShape = (key: string, shape: string) =>
    patch({ openingShapeOverrides: { [key]: shape } }, true);

  /** Give this one room its own wall thickness, or hand it back to the job. */
  const setRoomThickness = (mm: number | null) =>
    patch({ wallThickness: mm }, true);

  /* ---------------- doors hooked to other rooms ---------------- */

  const linkDoor = async (openingA: number, roomBName: string, openingB: number) => {
    if (!project || !room) return;
    const roomB = rooms.find((r) => r.name === roomBName);
    if (!roomB) return;
    const t = alignDoors(room, openingA, roomB, openingB);
    try {
      const c = await api.createConnection(project.id, {
        roomA: room.name, openingA, roomB: roomBName, openingB, ...t,
      });
      setConnections((cs) => [...cs, c]);
      setConnecting(null);
      setConnectTo(null);
      setPendingOpeningB(null);
    } catch (e) { say((e as Error).message, true); }
  };

  const cancelLink = () => {
    setConnecting(null);
    setConnectTo(null);
    setPendingOpeningB(null);
  };

  const unlinkConnection = async (id: string) => {
    if (!project) return;
    try {
      await api.deleteConnection(project.id, id);
      setConnections((cs) => cs.filter((c) => c.id !== id));
    } catch (e) { say((e as Error).message, true); }
  };

  const toggleConnection = async (c: Connection) => {
    if (!project) return;
    try {
      const updated = await api.patchConnection(project.id, c.id, { enabled: !c.enabled });
      setConnections((cs) => cs.map((x) => (x.id === c.id ? updated : x)));
    } catch (e) { say((e as Error).message, true); }
  };

  /** Cross through a connected door: switch to the room on the other side and
   *  stand just inside it, facing in. */
  const crossInto = async (connectionId: string) => {
    const c = connections.find((x) => x.id === connectionId);
    if (!c || !c.enabled || !room) return;
    const iAmA = room.name === c.roomA;
    const targetName = iAmA ? c.roomB : c.roomA;
    const targetOpening = iAmA ? c.openingB : c.openingA;
    const target = rooms.find((r) => r.name === targetName);
    if (!target || !target.openings[targetOpening]) return;

    // Same room-open bookkeeping openRoom does, but the build is awaited
    // here (openRoom fires it and moves on) - the eye must not land until
    // the far room's geometry actually exists to stand in, and doing it this
    // way means the ordinary "Building..." cover carries the wait, the same
    // as opening any other room does.
    // c.rotationDeg turns room B's frame into room A's; carrying a heading
    // the other way needs the inverse.
    const heading = rotateYaw(eye.yaw, iAmA ? -c.rotationDeg : c.rotationDeg);

    setFlat(target.flat);
    setRoom(target);
    setRing(target.outline);
    setFace(null);
    setPointName(null);
    setEnterAt(null);
    await buildRoom(target);
    setEnterAt({ ...entryPoint(target, targetOpening), yaw: heading });
    setLook("inside");
  };

  /** This room's doors that lead somewhere, and a faded preview of what is
   *  through each one - only while the walkthrough is allowed to use them. */
  const doors = useMemo<DoorLink[]>(() => {
    if (!room || !connectedMode) return [];
    return connections
      .filter((c) => c.enabled && (c.roomA === room.name || c.roomB === room.name))
      .map((c) => {
        const mine = c.roomA === room.name ? c.openingA : c.openingB;
        const o = room.openings[mine];
        return o ? { connectionId: c.id, left: o.left, right: o.right } : null;
      })
      .filter((d): d is DoorLink => !!d);
  }, [room, connections, connectedMode]);

  const ghostRooms = useMemo<GhostRoom[]>(() => {
    if (!room || !connectedMode) return [];
    return connections
      .filter((c) => c.enabled && (c.roomA === room.name || c.roomB === room.name))
      .map((c) => {
        const iAmA = c.roomA === room.name;
        const other = rooms.find((r) => r.name === (iAmA ? c.roomB : c.roomA));
        if (!other) return null;
        // dx/dy/rotationDeg place B in A's frame; from B looking at A it is
        // the inverse of that rigid transform.
        const t = iAmA ? c : invertTransform(c);
        return {
          connectionId: c.id, outline: outlinePoints(other),
          floorZ: other.floorZ, ceilingHeight: other.ceilingHeight,
          dx: t.dx, dy: t.dy, rotationDeg: t.rotationDeg,
        };
      })
      .filter((g): g is GhostRoom => !!g);
  }, [room, rooms, connections, connectedMode]);

  /* ---------------- picking a door for a new connection, in the viewport
     itself rather than from a list of look-alike widths ---------------- */

  const pickRoomB = useMemo(
    () => (connectTo ? rooms.find((r) => r.name === connectTo) ?? null : null),
    [connectTo, rooms],
  );

  /* Parked beside room A until a door is picked, then the exact fit -
     alignDoors is the same function an established connection was built
     with, so the snap lands exactly where the connection will actually sit. */
  const pickTransform = useMemo(() => {
    if (!room || connecting == null || !pickRoomB) return null;
    return pendingOpeningB != null
      ? alignDoors(room, connecting, pickRoomB, pendingOpeningB)
      : parkBeside(room, connecting, pickRoomB);
  }, [room, connecting, pickRoomB, pendingOpeningB]);

  const pickGhost = useMemo<GhostRoom | null>(() => {
    if (!pickRoomB || !pickTransform) return null;
    return {
      connectionId: "pick", outline: outlinePoints(pickRoomB),
      floorZ: pickRoomB.floorZ, ceilingHeight: pickRoomB.ceilingHeight,
      ...pickTransform,
    };
  }, [pickRoomB, pickTransform]);

  /* Room B's own doors, glowing where they actually stand next to room A -
     the thing a cm width on a dropdown could never show. Once one is picked
     these go quiet; the confirm bar takes over. */
  const pickDoors = useMemo<DoorLink[]>(() => {
    if (!pickRoomB || !pickTransform || pendingOpeningB != null) return [];
    return pickRoomB.openings
      .map((o, j) => o.kind === "door"
        ? { connectionId: `pick:${j}`,
            left: applyTransform(o.left, pickTransform),
            right: applyTransform(o.right, pickTransform) }
        : null)
      .filter((d): d is DoorLink => !!d);
  }, [pickRoomB, pickTransform, pendingOpeningB]);

  const pickOpeningB = (id: string) => {
    const j = Number(id.slice("pick:".length));
    if (Number.isFinite(j)) setPendingOpeningB(j);
  };

  /* This room's own doors, glowing from the moment the Doors popover opens -
     the "click one and confirm" step the cm list used to stand in for.
     Narrows to just the one already picked once a link is in progress, so
     the confirmation stays on screen through the room-picking step too. */
  const myDoors = useMemo<DoorLink[]>(() => {
    if (!room || !doorsOpen) return [];
    if (connecting == null) {
      return room.openings
        .map((o, i) => (o.kind === "door" && !connections.some((c) =>
            (c.roomA === room.name && c.openingA === i) ||
            (c.roomB === room.name && c.openingB === i)))
          ? { connectionId: `a:${i}`, left: o.left, right: o.right } : null)
        .filter((d): d is DoorLink => !!d);
    }
    if (connectTo) return [];
    const o = room.openings[connecting];
    return o ? [{ connectionId: `a:${connecting}`, left: o.left, right: o.right }] : [];
  }, [room, doorsOpen, connecting, connectTo, connections]);

  const pickOpeningA = (id: string) => {
    const i = Number(id.slice("a:".length));
    if (Number.isFinite(i)) setConnecting(i);
  };

  const viewportDoors = pickDoors.length ? pickDoors : myDoors.length ? myDoors : doors;
  const viewportGhosts = pickGhost ? [...ghostRooms, pickGhost] : ghostRooms;
  const viewportOnDoor = pickDoors.length ? pickOpeningB
    : myDoors.length && connecting == null ? pickOpeningA : crossInto;

  const doExport = async () => {
    if (!project || !room) return;
    setBusy(true);
    try {
      const r = await api.exportStep(project.id, room.name, fmt, schema);
      say(`${T("exported")} · ${fmtLabel(fmt, schema)} · ${(r.bytes / 1024).toFixed(0)} KB`);
      bridge?.reveal(r.path);
      setRooms((rs) => rs.map((x) =>
        x.name === room.name ? { ...x, status: "built" as const } : x));
    } catch (e) { say((e as Error).message, true); }
    finally { setBusy(false); }
  };

  /** Export the wall under the picked face as its own STEP body. */
  const doExportWall = async () => {
    if (!project || !room || face === null) return;
    setBusy(true);
    try {
      const r = await api.exportWall(project.id, room.name, face, fmt, schema);
      say(`${T("exported")} · ${fmtLabel(fmt, schema)} · ${T("wallFace")} ${r.wall} · ` +
          `${r.length.toFixed(0)} cm · ${(r.bytes / 1024).toFixed(0)} KB`);
      bridge?.reveal(r.path);
    } catch (e) { say((e as Error).message, true); }
    finally { setBusy(false); }
  };

  const doDesignX = async () => {
    if (!project || !room) return;
    try {
      const r = await api.exportDesignX(project.id, room.name, "iges");
      say(`${T("exported")} · IGES`);
      bridge?.reveal(r.path);
    } catch (e) { say((e as Error).message, true); }
  };

  /* The trip back. A sketch tidied up in Design X replaces the last one this
     room was given, rather than being layered on top of it - so importing
     twice leaves the room exactly where importing once did. */
  const doImportDesignX = async () => {
    if (!project || !room) return;
    const picked = await bridge?.pickSketch();
    if (!picked) return;
    setBusy(true);
    try {
      const r = await api.importDesignX(project.id, room.name, picked);
      setRoom(r);
      setRing([]);
      setResult(null);
      const n = r.imported;
      say(`${T("importedSketch")} · ${n.matched} ${T("matchedShots")} · ` +
          `${n.points} ${T("newPoints")} · ${n.outline} ${T("ringCorners")}`);
    } catch (e) { say((e as Error).message, true); }
    finally { setBusy(false); }
  };

  const doClearDesignX = async () => {
    if (!project || !room) return;
    try {
      setRoom(await api.clearDesignX(project.id, room.name));
      setRing([]);
      setResult(null);
      say(T("clearedSketch"));
    } catch (e) { say((e as Error).message, true); }
  };

  const openProjectSettings = () => {
    if (!project) return;
    setDraftName(project.name);
    setConfirmRemove(false);
    setScreen("project");
  };

  const renameProject = async (name: string) => {
    if (!project || !name.trim() || name === project.name) return;
    try {
      await api.patchProject(project.id, { name: name.trim() });
      setProject({ ...project, name: name.trim() });
      setProjects(await api.projects());
      say(T("renamed"));
    } catch (e) { say((e as Error).message, true); }
  };

  const setJobThickness = async (v: number) => {
    if (!project) return;
    setProject({ ...project, thickness: v });
    try {
      await api.patchProject(project.id, { thickness: v });
      if (room && room.status !== "needs-you") await buildRoom(room);
    } catch (e) { say((e as Error).message, true); }
  };

  const removeProject = async () => {
    if (!project) return;
    try {
      await api.deleteProject(project.id);
      setProjects(await api.projects());
      setProject(null); setRooms([]); setRoom(null); setResult(null);
      setConfirmRemove(false);
      setScreen("home");
      say(T("removed"));
    } catch (e) { say((e as Error).message, true); }
  };

  const openSettings = async () => {
    try { setSettings(await api.settings()); setScreen("settings"); }
    catch (e) { say((e as Error).message, true); }
  };

  const saveSetting = async (k: string, v: unknown) => {
    setSettings((s) => (s ? { ...s, [k]: v } : s));
    try {
      await api.patchSettings({ [k]: v });
      // Every one of these settings changes the geometry: whether openings are
      // cut at all, how thick the shell is, whether fixtures are included. The
      // body on screen was built under the old ones, so it is now wrong. Build
      // it again rather than leave a stale solid the operator might export.
      if (room && room.status !== "needs-you") await buildRoom(room);
    } catch (e) { say((e as Error).message, true); }
  };

  /* ---------------- derived ---------------- */
  const selectedFace = useMemo(
    () => result?.mesh.faces.find((f) => f.id === face) ?? null, [result, face]);
  const selectedPoint = useMemo(
    () => room?.points.find((p) => p.name === pointName) ?? null, [room, pointName]);
  /** The wall rectangle the picked face belongs to, if it belongs to one. */
  const selectedRect = useMemo(() => {
    const key = selectedFace?.element;
    if (!key || !room) return null;
    return room.openings.find((o) => o.key === key) ?? null;
  }, [selectedFace, room]);

  const counts = useMemo(() => tally(rooms), [rooms]);

  /* The survey grouped by flat, in the order the rooms were read. "Daire 51 -
     Salon" carries its flat in its own name, so nothing has to be entered. */
  const flats = useMemo(() => {
    const by = new Map<string, Room[]>();
    for (const r of rooms) {
      const list = by.get(r.flat);
      if (list) list.push(r);
      else by.set(r.flat, [r]);
    }
    return [...by].map(([name, rs]) => ({ name, rooms: rs, ...tally(rs) }));
  }, [rooms]);

  // A survey with no flat prefix at all is one nameless group; showing a card
  // grid of one would be silly, so that case goes straight to the rooms.
  const grouped = flats.length > 1;
  const flatRooms = useMemo(
    () => (grouped ? rooms.filter((r) => r.flat === flat) : rooms),
    [rooms, flat, grouped]);

  /* Where the workspace's room switcher gets its list: everything else in the
     same flat as the open room. */
  const siblings = useMemo(
    () => (room ? rooms.filter((r) => r.flat === room.flat && r.name !== room.name) : []),
    [rooms, room]);

  const totalRooms = useMemo(
    () => projects.reduce((n, p) => n + p.rooms, 0), [projects]);

  const pickPoint = (name: string) => {
    setPointName(name);
    if (edit === "outline") {
      setRing((r) => (r.includes(name) ? r.filter((n) => n !== name) : [...r, name]));
      return;
    }
    if (edit === "line") {
      if (!pending) { setPending(name); return; }
      if (pending === name) { setPending(null); return; }
      void toggleLine(pending, name);
      setPending(null);
    }
  };

  const key2 = (a: string, b: string) => [a, b].sort().join("|");

  /** Connect two points, or unlink them when that line already exists. */
  const toggleLine = async (a: string, b: string) => {
    if (!room) return;
    const k = key2(a, b);
    const match = room.segments.filter(([x, y]) => key2(x, y) === k);
    if (match.length) {
      const next = [...droppedLines,
                    ...match.map(([x, y]) => [x, y] as [string, string])];
      setDroppedLines(next);
      await patch({ removedSegments: next, addedSegments: addedLines }, true);
      say(T("lineRemoved"));
    } else {
      const next: [string, string][] = [...addedLines, [a, b]];
      setAddedLines(next);
      await patch({ addedSegments: next, removedSegments: droppedLines }, true);
      say(T("lineAdded"));
    }
  };

  /** Next free name for a point the operator constructed rather than shot. */
  const nextDerived = () => {
    const used = new Set((room?.points ?? [])
      .filter((p) => p.derived).map((p) => p.name));
    for (let i = 1; ; i++) {
      const name = `D_${String(i).padStart(3, "0")}`;
      if (!used.has(name)) return name;
    }
  };

  /**
   * Run a line further than the survey reached. The far end becomes a
   * constructed point; the original shot stays exactly where it was, and the
   * line is re-drawn to the new end.
   */
  const extendLine = async ([an, bn]: [string, string], end: string,
                            to: [number, number]) => {
    if (!room) return;
    const fixed = end === an ? bn : an;
    const moving = room.points.find((p) => p.name === end);
    if (!moving) return;

    // Dragging the same constructed end again moves it, rather than leaving a
    // trail of abandoned points behind.
    const reuse = moving.derived;
    const name = reuse ? end : nextDerived();
    const derived = [
      ...(room.points.filter((p) => p.derived && p.name !== name)
          .map((p) => ({ name: p.name, x: p.x, y: p.y, z: p.z,
                         role: p.role, from: p.source }))),
      { name, x: to[0], y: to[1], z: moving.z, role: moving.role,
        from: `extended from ${fixed}` },
    ];

    const body: Record<string, unknown> = { derivedPoints: derived };
    if (!reuse) {
      // The old line is replaced rather than added to, so the drawing never
      // shows both the short and the long version of the same wall.
      const dropped = [...droppedLines, [an, bn] as [string, string]];
      const added: [string, string][] = [...addedLines, [fixed, name]];
      setDroppedLines(dropped);
      setAddedLines(added);
      body.removedSegments = dropped;
      body.addedSegments = added;
    }
    await patch(body, true);
    setLineSel(reuse ? [fixed, name] : [fixed, name]);
    say(T("lineExtended"));
  };

  /** Turn a place where two lines cross into a corner both of them share. */
  const adoptCrossing = async (c: Crossing) => {
    if (!room) return;
    const name = nextDerived();
    const [[a1, b1], [a2, b2]] = c.lines;
    const z = room.floorZ ?? 0;

    const derived = [
      ...room.points.filter((p) => p.derived)
        .map((p) => ({ name: p.name, x: p.x, y: p.y, z: p.z,
                       role: p.role, from: p.source })),
      { name, x: c.at[0], y: c.at[1], z, role: "floor",
        from: `crossing of ${a1}-${b1} and ${a2}-${b2}` },
    ];

    // Both lines are split at the crossing, which is what makes it a join
    // rather than two lines that merely overlap on screen.
    const dropped: [string, string][] = [...droppedLines, [a1, b1], [a2, b2]];
    const added: [string, string][] = [...addedLines,
      [a1, name], [name, b1], [a2, name], [name, b2]];
    setDroppedLines(dropped);
    setAddedLines(added);
    await patch({ derivedPoints: derived, removedSegments: dropped,
                  addedSegments: added }, true);
    say(T("cornerMade"));
  };

  /**
   * Put a point somewhere else. The CSV is never touched: the shot as the
   * instrument took it is still in the file, and clearing the move brings it
   * straight back. Everything the room is worked out from reads the new place.
   */
  const movePoint = async (name: string, to: [number, number, number]) => {
    if (!room) return;
    const shot = room.points.find((p) => p.name === name);
    if (!shot) return;
    // A constructed point is edited where it lives, so it keeps its provenance
    // instead of gaining a second record saying it was moved from itself.
    if (shot.derived) {
      const derived = room.points.filter((p) => p.derived).map((p) =>
        p.name === name
          ? { name: p.name, x: to[0], y: to[1], z: to[2], role: p.role, from: p.source }
          : { name: p.name, x: p.x, y: p.y, z: p.z, role: p.role, from: p.source });
      await patch({ derivedPoints: derived }, true);
    } else {
      await patch({ movedPoints: { ...moves(), [name]: to } }, true);
    }
    say(`${T("pointMoved")} · ${to[0].toFixed(1)}, ${to[1].toFixed(1)}, ${to[2].toFixed(1)}`);
  };

  /* Every point that is not where it was shot, read back off the room rather
     than remembered here: the room is what the service actually holds, and a
     list kept alongside it goes stale the moment anything else edits one. */
  const moves = (): Record<string, [number, number, number]> =>
    Object.fromEntries((room?.points ?? []).filter((p) => p.moved)
      .map((p) => [p.name, [p.x, p.y, p.z] as [number, number, number]]));

  /** Back to where the instrument put it. */
  const unmovePoint = async (name: string) => {
    const next = moves();
    if (!next[name]) return;
    delete next[name];
    await patch({ movedPoints: next }, true);
    say(T("pointRestored"));
  };

  /** Remove the line the operator has selected. */
  const deleteLine = async () => {
    if (!room || !lineSel) return;
    const k = key2(lineSel[0], lineSel[1]);
    const match = room.segments
      .filter(([x, y]) => key2(x, y) === k)
      .map(([x, y]) => [x, y] as [string, string]);
    // A line the operator drew this session is simply dropped again.
    const stillAdded = addedLines.filter(([x, y]) => key2(x, y) !== k);
    const next = [...droppedLines, ...match];
    setAddedLines(stillAdded);
    setDroppedLines(next);
    setLineSel(null);
    await patch({ removedSegments: next, addedSegments: stillAdded }, true);
    say(T("lineRemoved"));
  };

  const deletePoint = async () => {
    if (!pointName) return;
    const next = [...droppedPoints, pointName];
    setDroppedPoints(next);
    setPointName(null);
    await patch({ droppedPoints: next }, true);
    say(T("deleted"));
  };

  const inSketch = tool === "sketch";

  /* Every change to the ring goes straight into the body.
   *
   * Drawing an outline and then having to remember to press Apply meant the
   * 3D was quietly one edit behind for as long as you were working, and the
   * body you were looking at was not the room you had just drawn. Every other
   * edit in the sketch already rebuilt on the spot; the ring was the one that
   * did not.
   *
   * Debounced, because a ring is drawn as a run of clicks and each one is not
   * worth its own trip through the kernel. Under three corners there is no
   * room to build yet, so nothing is sent. */
  const applied = useRef("");
  useEffect(() => {
    if (!inSketch || edit !== "outline" || !room || ring.length < 3) return;
    const key = ring.join("|");
    if (key === applied.current) return;
    // Already what the room is built from - the ring was only reset, not redrawn.
    if (key === room.outline.join("|")) { applied.current = key; return; }
    const t = setTimeout(() => {
      applied.current = key;
      void patch({ outlineOrder: ring }, true);
    }, 400);
    return () => clearTimeout(t);
    // patch closes over project/room, both already here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ring, edit, inSketch, room]);

  const sketchProps = useMemo(() => {
    if (!inSketch || !room) return null;
    return {
      points: room.points,
      segments: room.segments,
      ring: edit === "outline" ? ring : room.outline,
      selectedPoint: pointName,
      pending,
      selectedLine: lineSel,
      onPickPoint: pickPoint,
      onPickLine: setLineSel,
      moveMode: edit === "layer" && axisMove,
      onMovePoint: movePoint,
    };
    // pickPoint closes over edit/pending, which are both in the list already.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inSketch, room, ring, edit, pointName, pending, lineSel, axisMove]);

  /* ================================================================== */
  return (
    <div className="app">
      <header className="titlebar">
        <Mark />
        <b>Snapir Design X</b>
        {project && screen !== "home" && screen !== "projects" && (
          <span className="crumb">
            · {project.name}{room && screen === "work" ? ` · ${room.label}` : ""}
          </span>
        )}
        <div className="right">
          {screen !== "launch" && screen !== "home" && (
            <button className="btn q sm" onClick={() => setScreen("home")}>
              {T("home")}</button>
          )}
          {screen !== "launch" && (
            <button className="btn q sm" onClick={openSettings}>{T("navSettings")}</button>
          )}
          <div className="lang" role="group" aria-label="Language">
            {(["en", "tr"] as Lang[]).map((l) => (
              <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>
                {l.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="main">
        {/* Keyed so each screen mounts fresh and plays its entrance. */}
        <div className="screen" key={screen}>
        {/* ---------------- launch ---------------- */}
        {screen === "launch" && (
          <div className="launch"><div className="in">
            <Mark />
            <h2>Snapir<em>Design X</em></h2>
            {bootError ? (
              <>
                <p className="err">{T("bootFail")}<br />{bootError}</p>
                <button className="btn" onClick={boot}>{T("retry")}</button>
              </>
            ) : (
              <><div className="track"><i /></div><small>{T("boot")}</small></>
            )}
          </div></div>
        )}

        {/* ---------------- home ---------------- */}
        {screen === "home" && (
          <div className="page home">
            <div className="hero">
              <Mark className="hero-mk" />
              <div>
                <h1>Snapir <span>Design X</span></h1>
                <p>{T("continueWork")}</p>
              </div>
              <div className="stats">
                <div><span className="num">{projects.length}</span><span>{T("statProjects")}</span></div>
                <div><span className="num">{totalRooms}</span><span>{T("statRooms")}</span></div>
              </div>
            </div>

            {projects.length === 0 ? (
              <div className="empty">
                <Mark />
                <b>{T("noRecent")}</b>
                <p>{T("noRecentHelp")}</p>
                <button className="btn" onClick={newProject}>{T("openFolder")}</button>
              </div>
            ) : (
              <>
                {/* Every project, not the newest few. Capping the list meant
                    importing one pushed another off the screen, which reads as
                    the older one having been lost. They are in most-recently-
                    opened order and the grid wraps, so a long list costs
                    nothing but scrolling. */}
                <div className="cards">
                  {projects.map((p) => (
                    <button className="card" key={p.id} onClick={() => openProject(p.id)}>
                      <b>{p.name}</b>
                      <span className="path">{p.folder}</span>
                      <div className="cardfoot">
                        <span className="num">{p.rooms}</span>
                        <span>{T("rooms")}</span>
                        {p.missing && <span className="tag t-warn"><i />{T("missing")}</span>}
                      </div>
                    </button>
                  ))}
                </div>
                <div className="homeacts">
                  <button className="btn" onClick={newProject}>{T("newProject")}</button>
                  <button className="btn q" onClick={() => setScreen("projects")}>
                    {T("openProjects")}</button>
                </div>
              </>
            )}
          </div>
        )}

        {/* ---------------- projects ---------------- */}
        {screen === "projects" && (
          <div className="page">
            <div className="page-head">
              <button className="btn q sm" onClick={() => setScreen("home")}>{T("back")}</button>
              <h2>{T("navProjects")}</h2>
              <span className="num">{projects.length}</span>
              <div className="sp">
                <button className="btn q sm" onClick={importProject}>{T("importProject")}</button>
                <button className="btn" onClick={newProject}>{T("newProject")}</button>
              </div>
            </div>
            {projects.length === 0 ? (
              <div className="empty">
                <Mark /><b>{T("noProjects")}</b><p>{T("noProjectsHelp")}</p>
                <button className="btn" onClick={newProject}>{T("openFolder")}</button>
              </div>
            ) : (
              <div className="list">
                {projects.map((p) => (
                  <div className="lrow" key={p.id} tabIndex={0}
                       onClick={() => openProject(p.id)}
                       onKeyDown={(e) => e.key === "Enter" && openProject(p.id)}>
                    <div className="nm">
                      <b>{p.name}</b><span className="path">{p.folder}</span>
                    </div>
                    <div className="meta">
                      {p.missing
                        ? <span className="tag t-warn"><i />{T("missing")}</span>
                        : <div><span className="num">{p.rooms}</span><span>{T("rooms")}</span></div>}
                      <button className="btn q sm"
                              onClick={(e) => { e.stopPropagation(); void exportProject(p); }}>
                        {T("exportProject")}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ---------------- flats ---------------- */}
        {screen === "rooms" && project && (
          <div className="page">
            <div className="page-head">
              <button className="btn q sm" onClick={() => setScreen("home")}>{T("back")}</button>
              <h2>{project.name}</h2>
              <span className="num">
                {counts.ready} {T("ready")} · {counts.built} {T("built")} · {counts.needs} {T("needsYou")}
              </span>
              <div className="sp">
                <button className="btn q sm" onClick={openProjectSettings}>
                  {T("projectSettings")}</button>
              </div>
            </div>

            {grouped ? (
              <div className="flats">
                {flats.map((f) => (
                  <button className="fcard" key={f.name} onClick={() => openFlat(f.name)}>
                    <b>{f.name || T("allRooms")}</b>
                    <div className="fcard-m">
                      <span className="num">{f.rooms.length}</span>
                      <span>{T("rooms")}</span>
                    </div>
                    <div className="fcard-t">
                      {f.built > 0 && <span className="tag t-done"><i />{f.built}</span>}
                      {f.ready > 0 && <span className="tag t-ok"><i />{f.ready}</span>}
                      {f.needs > 0 && <span className="tag t-warn"><i />{f.needs}</span>}
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="rooms">
                {rooms.map((r) => (
                  <RoomCard key={r.name} room={r} projectId={project.id} T={T}
                            onOpen={() => openRoom(r)} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ---------------- rooms in one flat ---------------- */}
        {screen === "flat" && project && (
          <div className="page">
            <div className="page-head">
              <button className="btn q sm" onClick={() => setScreen("rooms")}>{T("back")}</button>
              <h2 className="flatname">{flat || project.name}</h2>
              <span className="num">{flatRooms.length} {T("rooms")}</span>
            </div>
            <div className="rooms">
              {flatRooms.map((r) => (
                <RoomCard key={r.name} room={r} projectId={project.id} T={T}
                          onOpen={() => openRoom(r)} />
              ))}
            </div>
          </div>
        )}

        {/* ---------------- workspace ---------------- */}
        {screen === "work" && room && (
          <div className={inSketch ? "ws sketching" : "ws"}>
            <div className="vp">
              {(!inSketch || view === "3d") && (
                <Viewport
                  mesh={result?.mesh ?? null}
                  selected={face}
                  onSelect={setFace}
                  sketch={sketchProps}
                  look={look}
                  ghost={ghost}
                  dark={dark}
                  bounds={bounds}
                  stations={posts}
                  floorZ={room.floorZ}
                  pano={panoUrl
                    ? { url: panoUrl, heading: pose?.heading ?? 0,
                        station: pose?.station ?? 0 }
                    : null}
                  panoOpen={panoOpen}
                  onLook={setEye}
                  doors={viewportDoors}
                  ghostRooms={viewportGhosts}
                  onCrossDoor={viewportOnDoor}
                  enterAt={enterAt}
                  aimHandle={aimHandle}
                />
              )}

              {/* The crosshair sits dead centre, where the ray is cast. On a
                  tablet a fingertip would cover the very thing being aimed at,
                  so nothing is picked by touch here. */}
              {look === "inside" && aiming && !inSketch && (
                <div className="crosshair" aria-hidden="true">
                  <i /><i />
                  <button className="btn sm" onClick={addAimedPoint} disabled={busy}>
                    {T("putPointHere")}
                  </button>
                </div>
              )}
              {inSketch && view === "2d" && (
                <Sketch points={room.points}
                        segments={room.segments}
                        outline={room.outline} draft={ring}
                        selected={pointName} pending={pending}
                        selectedLine={lineSel}
                        crossings={room.crossings ?? []}
                        onExtend={extendLine}
                        onAdoptCrossing={adoptCrossing}
                        mode={edit} onPick={pickPoint} onPickLine={setLineSel} />
              )}

              {inSketch && (
                <div className="rail" role="group">
                  {(["outline", "line", "layer"] as EditMode[]).map((m) => (
                    <button key={m} aria-pressed={edit === m}
                            onClick={() => { setEdit(m); setPending(null);
                                             if (m !== "layer") setAxisMove(false); }}>
                      {T(m === "outline" ? "editRing"
                        : m === "line" ? "editLine" : "editLayer")}
                    </button>
                  ))}
                  {edit === "layer" && (
                    <button aria-pressed={axisMove} title={T("moveHelp")}
                            onClick={() => setAxisMove(!axisMove)}>
                      {T("movePoint")}</button>
                  )}
                </div>
              )}
              <div className="overlay">
                <span className="hud">
                  {inSketch
                    ? (edit === "outline" ? T("ringHelp")
                       : edit === "line" ? T("lineHelp")
                       : axisMove ? T("moveHelp") : T("layerHelp"))
                    : look === "inside" && !panoOpen ? T("insideHint")
                    : room.name}
                </span>
                {/* A photograph that could not be lined up says so once, then
                    gets out of the way and leaves a plain 360 view. */}
                {panoOpen && panoWarn && (
                  <div className="panowarn" role="status">{T("panoUnaligned")}</div>
                )}
                {pickRoomB && (
                  <div className="linkbar" role="group">
                    {pendingOpeningB != null ? (
                      <>
                        <span>{T("connectTo")} <b>{pickRoomB.label}</b>?</span>
                        <button className="btn q sm" onClick={() => setPendingOpeningB(null)}>
                          {T("cancel")}</button>
                        <button className="btn sm"
                                onClick={() => connecting != null &&
                                  void linkDoor(connecting, pickRoomB.name, pendingOpeningB)}>
                          {T("confirm")}</button>
                      </>
                    ) : (
                      <>
                        <span>{T("pickDoorHint")} <b>{pickRoomB.label}</b></span>
                        <button className="btn q sm" onClick={cancelLink}>{T("cancel")}</button>
                      </>
                    )}
                  </div>
                )}
                {inSketch && edit === "outline" && (
                  <div className="sketchbar">
                    <span className="num">{ring.length}</span>
                    <span>{T("sketchPoints")}</span>
                    <button className="btn q sm" disabled={ring.length === 0}
                            onClick={() => { setRing([]); setPending(null);
                                             say(T("outlineWiped")); }}>
                      {T("sketchWipe")}</button>
                    <button className="btn q sm" onClick={() => setRing(room.outline)}>
                      {T("sketchReset")}</button>
                    {/* The ring applies itself as it is drawn; this is for
                        when you would rather not wait out the pause. */}
                    <button className="btn sm" disabled={ring.length < 3}
                            onClick={async () => {
                              applied.current = ring.join("|");
                              await patch({ outlineOrder: ring }, true);
                              say(T("outlineApplied"));
                            }}>
                      {T("sketchApply")}</button>
                  </div>
                )}

                {/* One row, wrapping. Two bars pinned to opposite corners
                    collided the moment either of them grew: at 1324 px the
                    door group was sitting on top of Back. */}
                <div className="bar">
                <div className="tools">
                  <div className="seg quiet">
                    <button aria-pressed={tool === "face"}
                            onClick={() => { setTool("face"); setPointName(null); }}>
                      {T("tFace")}</button>
                    <button aria-pressed={inSketch} onClick={() => setTool("sketch")}>
                      {T("tSketch")}</button>
                  </div>
                  {!inSketch && result && (
                    <>
                      <div className="seg quiet">
                        <button aria-pressed={look === "orbit"}
                                onClick={() => setLook("orbit")}>{T("vOrbit")}</button>
                        <button aria-pressed={look === "inside"}
                                onClick={() => setLook("inside")}>{T("vInside")}</button>
                      </div>
                      {look === "inside" && (
                        <div className="seg quiet">
                          <button aria-pressed={aiming}
                                  onClick={() => setAiming(!aiming)}>
                            {T("addPoint")}</button>
                        </div>
                      )}
                      {look === "inside" && panoUrl && (
                        <div className="seg quiet">
                          <button aria-pressed={panoOpen} disabled={solving}
                                  className={!solving && !pose ? "cold" : undefined}
                                  title={solving ? T("panoSolving") : undefined}
                                  onClick={() => setPanoOpen(!panoOpen)}>
                            {T("vPano")}</button>
                        </div>
                      )}
                      <div className="seg quiet">
                        <button aria-pressed={ghost}
                                onClick={() => setGhost(!ghost)}>{T("vGhost")}</button>
                      </div>
                      <div className="seg quiet">
                        <button disabled={loadingAll} onClick={() => void loadAllRooms()}>
                          {loadingAll ? T("loadingAll") : T("loadAll")}</button>
                      </div>
                      <div className="seg quiet">
                        <button aria-pressed={connectedMode}
                                title={T("connectedDoorsHelp")}
                                onClick={() => setConnectedMode(!connectedMode)}>
                          {T("connectedDoors")}</button>
                        <button aria-pressed={doorsOpen}
                                onClick={() => setDoorsOpen(!doorsOpen)}>
                          {T("doors")}</button>
                      </div>
                    </>
                  )}
                  {inSketch && (
                    <>
                      <div className="seg quiet">
                        <button aria-pressed={view === "2d"} onClick={() => setView("2d")}>
                          {T("view2d")}</button>
                        <button aria-pressed={view === "3d"} onClick={() => setView("3d")}>
                          {T("view3d")}</button>
                      </div>
                    </>
                  )}
                </div>
                <div className="acts">
                  <button className="btn q sm" onClick={leaveRoom}>{T("back")}</button>
                  <button className="btn q sm" onClick={doDesignX}>{T("forDesignX")}</button>
                  <button className="btn q sm" onClick={doImportDesignX}
                          title={T("fromDesignXHelp")}>{T("fromDesignX")}</button>
                  {/* Only once there is an import to undo. The survey itself is
                      untouched throughout, so this always has somewhere to go
                      back to. */}
                  {room.outlineSource === "Design X" && (
                    <button className="btn q sm" onClick={doClearDesignX}>
                      {T("clearSketch")}</button>
                  )}
                  <select className="fmt" value={fmt} title={T("formatHelp")}
                          onChange={(e) => pickFmt(e.target.value)}>
                    {EXPORT_FORMATS.map((f) => (
                      <option key={f.id} value={f.id}>{f.label}</option>
                    ))}
                  </select>
                  {fmt === "step" && (
                    <select className="fmt" value={schema} title={T("schemaHelp")}
                            onChange={(e) => pickSchema(e.target.value)}>
                      {STEP_SCHEMAS.map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  )}
                  <button className="btn sm" onClick={doExport} disabled={!result || busy}>
                    {T("exportRoom")}</button>
                </div>
                </div>
              </div>

              {doorsOpen && room && (
                <>
                  {/* Covers the whole window to close on an outside click, same
                      as any other popover here - except while a door is glowing
                      in the viewport underneath it, where the click has to reach
                      the canvas instead of being caught by this. */}
                  <div className="swback"
                       style={myDoors.length ? { pointerEvents: "none" } : undefined}
                       onClick={() => { setDoorsOpen(false); cancelLink(); }} />
                  <div className="swpop doorspop" role="dialog" aria-label={T("doors")}>
                    <h4>{T("doors")}</h4>
                    <div className="swlist">
                      {room.openings.filter((o) => o.kind === "door").length === 0 && (
                        <p className="hint">{T("noDoors")}</p>
                      )}
                      {room.openings.map((o, i) => {
                        if (o.kind !== "door") return null;
                        const link = connections.find((c) =>
                          (c.roomA === room.name && c.openingA === i) ||
                          (c.roomB === room.name && c.openingB === i));
                        const otherName = link
                          ? (link.roomA === room.name ? link.roomB : link.roomA) : null;
                        const other = otherName ? rooms.find((r) => r.name === otherName) : null;
                        return (
                          <div key={i} className="swrow" style={{ display: "block" }}>
                            <b>{T("doorWidth")} {o.width.toFixed(0)} cm</b>
                            {link ? (
                              <div className="rail" role="group">
                                <span>{other?.label ?? otherName}</span>
                                <Switch on={link.enabled}
                                        onChange={() => void toggleConnection(link)} />
                                <button className="btn q sm"
                                        onClick={() => void unlinkConnection(link.id)}>
                                  {T("unlink")}</button>
                              </div>
                            ) : connecting === i ? (
                              <div className="rail" role="group">
                                <select value=""
                                        onChange={(e) => {
                                          if (!e.target.value) return;
                                          setConnectTo(e.target.value);
                                          setDoorsOpen(false);
                                        }}>
                                  <option value="">{T("pickRoom")}</option>
                                  {rooms.filter((r) => r.name !== room.name && r.flat === room.flat).map((r) => (
                                    <option key={r.name} value={r.name}>{r.label}</option>
                                  ))}
                                </select>
                                <button className="btn q sm" onClick={cancelLink}>
                                  {T("cancel")}</button>
                              </div>
                            ) : (
                              <button className="btn q sm" onClick={() => setConnecting(i)}>
                                {T("linkTo")}</button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}

              {busy && <div className="busy">{T("building")}…</div>}
            </div>

            <aside className="insp">
              {room.status === "needs-you" && (
                <div className="warnbox">
                  <p>{room.issues.some((x) => x.code === "no-ceiling")
                    ? T("askCeiling")
                    : room.issues.find((x) => x.severity === "error")?.message}</p>
                  {room.issues.some((x) => x.code === "no-ceiling") ? (
                    <CeilingAsk onApply={(v) => patch({ ceilingHeight: v / 10 })} label={T("apply")} />
                  ) : (
                    <button className="btn sm" onClick={() => {
                      setTool("sketch"); setView("2d"); setEdit("outline");
                      setPointName(null);
                    }}>{T("sketchTitle")}</button>
                  )}
                </div>
              )}

              {inSketch && (
                <div className="grp">
                  <h4>{T("linkTitle")}</h4>
                  <dl className="kv">
                    <dt>{T("linesDrawn")}</dt><dd>{room.segments.length}</dd>
                    <dt>{T("linkCount")}</dt><dd>{room.links.length}</dd>
                  </dl>
                  <p className="quiet">{T("linkNote")}</p>
                </div>
              )}

              {inSketch && lineSel && (
                <div className="grp">
                  <h4>{T("lineTitle")}</h4>
                  <dl className="kv">
                    <dt>{T("between")}</dt><dd>{lineSel[0]} · {lineSel[1]}</dd>
                    <dt>{T("length")}</dt><dd>{lineLength(room, lineSel)} cm</dd>
                  </dl>
                  <button className="btn q sm delrow" onClick={deleteLine}>
                    {T("deleteLine")}</button>
                </div>
              )}

              {inSketch ? (
                <div className="grp">
                  <h4>{T("point")}</h4>
                  {selectedPoint ? (
                    <>
                      <dl className="kv">
                        <dt>{T("point")}</dt><dd>{selectedPoint.name}</dd>
                        <dt>X · Y</dt>
                        <dd>{selectedPoint.x.toFixed(1)} · {selectedPoint.y.toFixed(1)}</dd>
                        <dt>Z</dt><dd>{selectedPoint.z.toFixed(1)} cm</dd>
                      </dl>
                      <label className="fldlabel">{T("layer")}</label>
                      <div className="roles">
                        {ROLES.map(({ role, key }) => (
                          <button key={role}
                                  className={"role" + (selectedPoint.role === role ? " on" : "")}
                                  onClick={() => setRole(selectedPoint.name, role)}>
                            <i style={{ background: ROLE_COLOR[role] }} />{T(key)}
                          </button>
                        ))}
                      </div>
                      {selectedPoint.moved && (
                        <p className="quiet moved">{T("pointIsMoved")}</p>
                      )}
                      {selectedPoint.moved && (
                        <button className="btn q sm"
                                onClick={() => void unmovePoint(selectedPoint.name)}>
                          {T("putItBack")}</button>
                      )}
                      <button className="btn q sm delrow" onClick={deletePoint}>
                        {T("deletePoint")}</button>
                    </>
                  ) : <p className="quiet">{T("pickPoint")}</p>}
                </div>
              ) : (
                <div className="grp">
                  <h4>{T("selection")}</h4>
                  {selectedFace ? (
                    <dl className="kv">
                      <dt>{T("type")}</dt>
                      {/* The face knows which element it belongs to now, so it
                          can say "Boiler" or "Wall 3 of 11" rather than
                          guessing from which way it points. */}
                      <dd>{selectedFace.label
                        || T(selectedFace.role === "floor" ? "floorFace"
                          : selectedFace.role === "ceiling" ? "ceilingFace" : "wallFace")}</dd>
                      <dt>{T("area")}</dt><dd>{selectedFace.area.toFixed(2)} m²</dd>
                    </dl>
                  ) : <p className="quiet">—</p>}

                  {/* A rectangle on a wall: the survey cannot tell a boiler
                      from a window, so this is where the operator says. */}
                  {selectedRect && (
                    <>
                      <label className="fldlabel">{T("whatIsThis")}</label>
                      <div className="roles">
                        {(room.openingKinds ?? []).map((k) => (
                          <button key={k.kind}
                                  className={"role" + (selectedRect.kind === k.kind ? " on" : "")}
                                  onClick={() => setOpeningKind(selectedRect.key, k.kind)}>
                            {k.label}
                          </button>
                        ))}
                      </div>
                    </>
                  )}

                  {/* Four corners on a wall look the same whether the thing
                      is round or square, so this is the operator's too. */}
                  {selectedRect && !selectedRect.cuts && (
                    <>
                      <label className="fldlabel">{T("shapeIs")}</label>
                      <div className="roles">
                        {(room.shapes ?? []).map((sh) => (
                          <button key={sh}
                                  className={"role" + (selectedRect.shape === sh ? " on" : "")}
                                  onClick={() => setOpeningShape(selectedRect.key, sh)}>
                            {T(sh === "round" ? "shapeRound" : "shapeBox")}
                          </button>
                        ))}
                      </div>
                    </>
                  )}

                  {selectedFace?.elementKind === "wall" && (
                    <>
                      <button className="btn sm delrow" onClick={doExportWall}
                              disabled={busy}>{T("exportWall")}</button>
                      <p className="quiet">{T("wallNote")}</p>
                    </>
                  )}
                </div>
              )}

              {/* A room with a pier or a narrow neck cannot carry the job's
                  thickness without the walls swallowing it, so that room gets
                  to differ. Blank means it follows the job. */}
              <div className="grp">
                <h4>{T("thisRoom")}</h4>
                <label className="fldlabel">{T("wallThickness")}</label>
                <Stepper value={room.wallThickness ?? project?.thickness ?? 0}
                         onChange={setRoomThickness} />
                {room.wallThickness != null && (
                  <button className="btn q sm delrow"
                          onClick={() => setRoomThickness(null)}>
                    {T("useJobDefault")}
                  </button>
                )}
              </div>

              {/* The trip out to Geomagic Design X and back, on the room it
                  belongs to rather than buried in the bar along the bottom.
                  The survey CSV is never touched by any of it. */}
              <div className="grp">
                <h4>{T("designX")}</h4>
                <p className="quiet">{T("designXHelp")}</p>
                <button className="btn q sm wide" onClick={doDesignX}>
                  {T("forDesignX")}</button>
                <button className="btn q sm wide" onClick={doImportDesignX}
                        title={T("fromDesignXHelp")}>
                  {T("fromDesignX")}</button>
                {room.outlineSource === "Design X" && (
                  <>
                    <p className="quiet moved">{T("sketchIsImported")}</p>
                    <button className="btn q sm wide delrow" onClick={doClearDesignX}>
                      {T("clearSketch")}</button>
                  </>
                )}
              </div>

              <div className="grp">
                <h4>{T("roomInfo")}</h4>
                <dl className="kv">
                  <dt>{T("area")}</dt><dd>{room.area.toFixed(2)} m²</dd>
                  <dt>{T("height")}</dt>
                  <dd>{result ? `${result.planes.height.toFixed(1)} cm` : "—"}</dd>
                  <dt>{T("ceilingPlane")}</dt>
                  <dd>{result ? `${result.planes.ceilingTilt.toFixed(3)}°` : "—"}</dd>
                  <dt>{T("volume")}</dt>
                  <dd>{result ? `${result.stats.volume_m3.toFixed(3)} m³` : "—"}</dd>
                  <dt>{T("faces")}</dt><dd>{result?.stats.faces ?? "—"}</dd>
                  <dt>{T("openings")}</dt><dd>{room.openings.length}</dd>
                  <dt>{T("sockets")}</dt>
                  <dd>{room.points.filter((p) => p.role === "socket").length}</dd>
                  <dt>{T("plumbing")}</dt>
                  <dd>{room.points.filter((p) => p.role === "plumbing").length}</dd>
                </dl>
              </div>

              {result && (
                <p className="hint">
                  {result.stats.solids} {T("solid")} · {result.stats.faces} {T("faces")} ·{" "}
                  <b>{T("watertight")}</b>
                </p>
              )}

              {/* The inspector runs out of content well before it runs out of
                  column. The rest of the flat lives in that space, so moving
                  between rooms does not mean walking back two screens. */}
              {siblings.length > 0 && (
                <div className="swrooms">
                  <button className="btn q sm wide" aria-expanded={switcher}
                          onClick={() => setSwitcher(!switcher)}>
                    {T("otherRooms")} <span className="num">{siblings.length}</span>
                  </button>
                  {switcher && (
                    <>
                      <div className="swback" onClick={() => setSwitcher(false)} />
                      <div className="swpop" role="dialog" aria-label={T("switchRoom")}>
                        <h4>{room.flat || project?.name} · {siblings.length} {T("inThisFlat")}</h4>
                        <div className="swlist">
                          {siblings.map((r) => (
                            <button key={r.name} className="swrow"
                                    onClick={() => void openRoom(r)}>
                              <b>{r.label}</b>
                              <StatusTag status={r.status} T={T} />
                            </button>
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </aside>
          </div>
        )}

        {/* ---------------- project settings ---------------- */}
        {screen === "project" && project && (
          <div className="page">
            <div className="page-head">
              <button className="btn q sm" onClick={() => setScreen("rooms")}>{T("back")}</button>
              <h2>{T("projectSettings")}</h2>
              <span className="num">{rooms.length} {T("rooms")}</span>
            </div>

            <div className="pset">
              <Row title={T("projectName")} help={T("projectNameHelp")}>
                <input className="textin" value={draftName}
                       onChange={(e) => setDraftName(e.target.value)}
                       onBlur={() => renameProject(draftName)}
                       onKeyDown={(e) => e.key === "Enter" &&
                         (e.target as HTMLInputElement).blur()} />
              </Row>

              <Row title={T("surveyFolder")}
                   help={`${rooms.length} ${T("roomsCounted")}`}>
                <div className="pathbox">
                  <code>{projects.find((p) => p.id === project.id)?.folder ?? ""}</code>
                  <button className="btn q sm" onClick={() => bridge?.reveal(
                    projects.find((p) => p.id === project.id)?.folder)}>
                    {T("showInExplorer")}</button>
                </div>
              </Row>

              <Row title={T("jobThickness")} help={T("jobThicknessHelp")}>
                <Stepper value={project.thickness} onChange={setJobThickness} />
              </Row>

              <Row title={T("exportProject")} help={T("exportProjectHelp")}>
                <button className="btn q sm" onClick={() => void exportProject(project)}>
                  {T("exportProject")}</button>
              </Row>

              <div className="danger">
                <Row title={T("removeProject")} help={T("removeProjectHelp")}>
                  {confirmRemove ? (
                    <div className="confirm">
                      <span>{T("removeSure")}</span>
                      <button className="btn q sm" onClick={() => setConfirmRemove(false)}>
                        {T("cancel")}</button>
                      <button className="btn danger-btn sm" onClick={removeProject}>
                        {T("removeIt")}</button>
                    </div>
                  ) : (
                    <button className="btn q sm" onClick={() => setConfirmRemove(true)}>
                      {T("removeProject")}</button>
                  )}
                </Row>
              </div>
            </div>
          </div>
        )}

        {/* ---------------- settings ---------------- */}
        {screen === "settings" && settings && (
          <div className="set">
            <nav className="snav">
              {(["build", "fixtures", "appearance", "export", "about"] as const).map((k) => (
                <button key={k} aria-current={tab === k} onClick={() => setTab(k)}>
                  {T(k === "build" ? "setBuild" : k === "fixtures" ? "setFixtures"
                    : k === "appearance" ? "setAppearance"
                    : k === "export" ? "setExport" : "setAbout")}
                </button>
              ))}
            </nav>
            <div className="sbody">
              {tab === "build" && (
                <>
                  <Row title={T("wallThickness")} help={T("wallThicknessHelp")}>
                    <Stepper value={settings.wall_thickness}
                             onChange={(v) => saveSetting("wall_thickness", v)} />
                  </Row>
                  <Row title={T("slabThickness")} help={T("slabThicknessHelp")}>
                    <Stepper value={settings.floor_thickness}
                             onChange={(v) => { saveSetting("floor_thickness", v);
                                                saveSetting("ceiling_thickness", v); }} />
                  </Row>
                  <Row title={T("fitCeiling")} help={T("fitCeilingHelp")}>
                    <Switch on={!!settings.fit_ceiling_plane}
                            onChange={(v) => saveSetting("fit_ceiling_plane", v)} />
                  </Row>
                  <Row title={T("cutOpenings")} help={T("cutOpeningsHelp")}>
                    <Switch on={!!settings.cut_openings}
                            onChange={(v) => saveSetting("cut_openings", v)} />
                  </Row>
                </>
              )}
              {tab === "fixtures" && (
                <>
                  <Row title={T("buildFixtures")} help={T("buildFixturesHelp")}>
                    <Switch on={!!settings.include_fixtures}
                            onChange={(v) => saveSetting("include_fixtures", v)} />
                  </Row>
                  <Row title={T("socketMode")} help={T("socketModeHelp")}>
                    <div className="seg">
                      {(["box", "hole"] as const).map((m) => (
                        <button key={m} aria-pressed={settings.socket_mode === m}
                                onClick={() => saveSetting("socket_mode", m)}>
                          {T(m === "box" ? "modeBox" : "modeHole")}</button>
                      ))}
                    </div>
                  </Row>
                  <Row title={T("socketSize")} help="">
                    <Stepper value={settings.socket_width}
                             onChange={(v) => { saveSetting("socket_width", v);
                                                saveSetting("socket_height", v); }} />
                  </Row>
                  <Row title={T("pipeMode")} help={T("pipeModeHelp")}>
                    <div className="seg">
                      {(["stub", "hole"] as const).map((m) => (
                        <button key={m} aria-pressed={settings.pipe_mode === m}
                                onClick={() => saveSetting("pipe_mode", m)}>
                          {T(m === "stub" ? "modeStub" : "modeHole")}</button>
                      ))}
                    </div>
                  </Row>
                  <Row title={T("pipeDia")} help="">
                    <Stepper value={settings.pipe_diameter} step={1}
                             onChange={(v) => saveSetting("pipe_diameter", v)} />
                  </Row>
                  <Row title={T("pipeLen")} help={T("pipeLenHelp")}>
                    <Stepper value={settings.pipe_length}
                             onChange={(v) => saveSetting("pipe_length", v)} />
                  </Row>
                </>
              )}
              {tab === "appearance" && (
                <Row title={T("setAppearance")} help="">
                  <div className="seg">
                    {(["light", "dark"] as Theme[]).map((th) => (
                      <button key={th} aria-pressed={theme === th}
                              onClick={() => setTheme(th)}>
                        {T(th === "light" ? "thLight" : "thDark")}</button>
                    ))}
                  </div>
                </Row>
              )}
              {tab === "export" && (
                <Row title={fmtLabel(fmt, schema)}
                     help="Millimetres, one file per room. STEP is the exact body to work from; STL is triangles, for viewing only.">
                  <span className="num" style={{ fontSize: 12 }}>
                    {EXPORT_FORMATS.find((f) => f.id === fmt)?.suffix}</span>
                </Row>
              )}
              {tab === "about" && (
                <Row title="Snapir Design X" help="Leica iCON room surveys to solid bodies.">
                  <span className="num" style={{ fontSize: 12 }}>1.2.1</span>
                </Row>
              )}
              <div style={{ marginTop: 18 }}>
                <button className="btn q sm" onClick={() => setScreen("home")}>{T("back")}</button>
              </div>
            </div>
          </div>
        )}
        </div>
      </div>

      {toast && <div className={"toast" + (toast.bad ? " bad" : "")}>{toast.msg}</div>}
    </div>
  );
}

/* ---------------- small pieces ---------------- */

/** Straight-line distance between the two ends of a drawn line. */
/** The one question a room still needs answered, in the operator's words. */
function needsReason(room: Room, T: (k: Key) => string): string {
  return room.issues.some((x) => x.code === "no-ceiling")
    ? T("askCeiling")
    : room.issues.find((x) => x.severity === "error")?.message ?? "";
}

/** Ready / needs you / built, over any set of rooms. */
function tally(rooms: Room[]) {
  const c = { ready: 0, needs: 0, built: 0 };
  for (const r of rooms) {
    if (r.status === "needs-you") c.needs++;
    else if (r.status === "built") c.built++;
    else c.ready++;
  }
  return c;
}

const STATUS_TAG: Record<Status, { cls: string; key: Key }> = {
  built: { cls: "t-done", key: "built" },
  "needs-you": { cls: "t-warn", key: "needsYou" },
  ready: { cls: "t-ok", key: "ready" },
};

function StatusTag({ status, T }: { status: Status; T: (k: Key) => string }) {
  const { cls, key } = STATUS_TAG[status];
  return <span className={"tag " + cls}><i />{T(key)}</span>;
}

/** A room as a card: the panorama the surveyor shot, and what it is. */
function RoomCard({ room, projectId, T, onOpen }: {
  room: Room; projectId: string; T: (k: Key) => string; onOpen: () => void;
}) {
  return (
    <button className="rcard" onClick={onOpen}>
      <div className="shot">
        {room.panoramas > 0 ? (
          // Loaded lazily and only for the open flat, so a 28-room survey never
          // has more than a handful of these decoded at once.
          <img src={panoramaUrl(projectId, room.name)} alt={T("panoramaOf")}
               loading="lazy" decoding="async" draggable={false} />
        ) : (
          <span className="noshot"><Mark /><small>{T("noPanorama")}</small></span>
        )}
      </div>
      <div className="rcard-b">
        <b>{room.label}</b>
        <div className="rcard-m">
          <StatusTag status={room.status} T={T} />
          <span className="num">{room.area.toFixed(2)} m²</span>
          {room.ceilingHeight != null && (
            <span className="num">{room.ceilingHeight.toFixed(0)} cm</span>
          )}
        </div>
        {room.status === "needs-you" && <small>{needsReason(room, T)}</small>}
      </div>
    </button>
  );
}

function lineLength(room: Room, seg: [string, string]): string {
  const a = room.points.find((p) => p.name === seg[0]);
  const b = room.points.find((p) => p.name === seg[1]);
  if (!a || !b) return "—";
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z).toFixed(1);
}

function Row({ title, help, children }:
  { title: string; help: string; children: React.ReactNode }) {
  return (
    <div className="srow">
      <div className="t"><b>{title}</b>{help && <p>{help}</p>}</div>
      {children}
    </div>
  );
}

function Stepper({ value, onChange, step = 5, unit = "mm" }:
  { value: number; onChange: (v: number) => void; step?: number; unit?: string }) {
  return (
    <div className="stepper">
      <button onClick={() => onChange(Math.max(0, +(value - step).toFixed(2)))}
              aria-label="Decrease">−</button>
      <input value={value} inputMode="decimal"
             onChange={(e) => {
               const v = parseFloat(e.target.value);
               if (!Number.isNaN(v)) onChange(v);
             }} />
      {/* Every measurement in the app is centimetres. Say so on the control
          rather than making anyone guess. */}
      {unit && <span className="unit">{unit}</span>}
      <button onClick={() => onChange(+(value + step).toFixed(2))}
              aria-label="Increase">+</button>
    </div>
  );
}

function Switch({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return <button className="sw" role="switch" aria-checked={on}
                 onClick={() => onChange(!on)} />;
}

function CeilingAsk({ onApply, label }: { onApply: (v: number) => void; label: string }) {
  const [v, setV] = useState(2600);
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <Stepper value={v} onChange={setV} />
      <button className="btn sm" onClick={() => onApply(v)}>{label}</button>
    </div>
  );
}
