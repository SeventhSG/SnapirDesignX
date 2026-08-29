import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api, type BuildResult, type Project, type Room } from "./api";
import { t, type Key, type Lang } from "./i18n";
import Sketch, { type EditMode } from "./Sketch";
import Viewport, { ROLE_COLOR } from "./Viewport";

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

type Screen = "launch" | "home" | "projects" | "rooms" | "work"
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

// Two formats, for two different jobs. STEP is the body to work from and comes
// back through the kernel exactly. STL is triangles, for opening the room in
// something that will not read a STEP file.
const EXPORT_FORMATS = [
  { id: "step", label: "STEP", suffix: ".step" },
  { id: "stl", label: "STL", suffix: ".stl" },
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
  const [room, setRoom] = useState<Room | null>(null);
  const [result, setResult] = useState<BuildResult | null>(null);
  const [busy, setBusy] = useState(false);

  const [face, setFace] = useState<number | null>(null);
  const [tool, setTool] = useState<"face" | "sketch">("face");
  const [view, setView] = useState<"2d" | "3d">("3d");
  const [edit, setEdit] = useState<EditMode>("outline");
  const [pending, setPending] = useState<string | null>(null);
  const [lineSel, setLineSel] = useState<[string, string] | null>(null);
  const [ring, setRing] = useState<string[]>([]);
  const [pointName, setPointName] = useState<string | null>(null);
  const [look, setLook] = useState<"orbit" | "inside">("orbit");
  const [ghost, setGhost] = useState(false);

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

  /* ---------------- projects and rooms ---------------- */
  const openProject = async (id: string) => {
    setBusy(true);
    try {
      const data = await api.rooms(id);
      setProject({ id: data.id, name: data.name, thickness: data.thickness });
      setRooms(data.rooms);
      setScreen("rooms");
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

  const openRoom = async (r: Room) => {
    setRoom(r);
    setRing(r.outline);
    setFace(null);
    setPointName(null);
    setPending(null);
    setLineSel(null);
    setAddedLines([]); setDroppedLines([]); setDroppedPoints([]);
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

  const counts = useMemo(() => {
    const c = { ready: 0, needs: 0, built: 0 };
    for (const r of rooms) {
      if (r.status === "needs-you") c.needs++;
      else if (r.status === "built") c.built++;
      else c.ready++;
    }
    return c;
  }, [rooms]);

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
    };
    // pickPoint closes over edit/pending, which are both in the list already.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inSketch, room, ring, edit, pointName, pending, lineSel]);

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
                <div className="cards">
                  {projects.slice(0, 3).map((p) => (
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
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ---------------- rooms ---------------- */}
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
            <table className="tbl">
              <thead><tr>
                <th>{T("room")}</th><th>{T("status")}</th>
                <th className="r">{T("area")}</th><th className="r">{T("ceiling")}</th>
                <th className="r">{T("openings")}</th><th className="r">{T("corners")}</th>
              </tr></thead>
              <tbody>
                {rooms.map((r, i) => (
                  <Fragment key={r.name}>
                    {(i === 0 || rooms[i - 1].flat !== r.flat) && (
                      <tr><td className="flat" colSpan={6}>{r.flat}</td></tr>
                    )}
                    <tr onClick={() => openRoom(r)}>
                      <td>
                        <b>{r.label}</b>
                        {r.status === "needs-you" && (
                          <small>{r.issues.some((x) => x.code === "no-ceiling")
                            ? T("askCeiling")
                            : r.issues.find((x) => x.severity === "error")?.message}</small>
                        )}
                      </td>
                      <td>
                        <span className={"tag " + (r.status === "built" ? "t-done"
                          : r.status === "needs-you" ? "t-warn" : "t-ok")}>
                          <i />{T(r.status === "built" ? "built"
                            : r.status === "needs-you" ? "needsYou" : "ready")}
                        </span>
                      </td>
                      <td className="r">{r.area.toFixed(2)} m²</td>
                      <td className="r">{r.ceilingHeight?.toFixed(1) ?? "—"}</td>
                      <td className="r">{r.openings.length}</td>
                      <td className="r">{r.outline.length}</td>
                    </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
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
                />
              )}
              {inSketch && view === "2d" && (
                <Sketch points={room.points}
                        segments={room.segments}
                        outline={room.outline} draft={ring}
                        selected={pointName} pending={pending}
                        selectedLine={lineSel}
                        mode={edit} onPick={pickPoint} onPickLine={setLineSel} />
              )}

              {inSketch && (
                <div className="rail" role="group">
                  {(["outline", "line", "layer"] as EditMode[]).map((m) => (
                    <button key={m} aria-pressed={edit === m}
                            onClick={() => { setEdit(m); setPending(null); }}>
                      {T(m === "outline" ? "editRing"
                        : m === "line" ? "editLine" : "editLayer")}
                    </button>
                  ))}
                </div>
              )}
              <div className="overlay">
                <span className="hud">
                  {inSketch
                    ? (edit === "outline" ? T("ringHelp")
                       : edit === "line" ? T("lineHelp") : T("layerHelp"))
                    : look === "inside" ? T("insideHint") : room.name}
                </span>
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
                      <div className="seg quiet">
                        <button aria-pressed={ghost}
                                onClick={() => setGhost(!ghost)}>{T("vGhost")}</button>
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
                  <button className="btn q sm" onClick={() => setScreen("rooms")}>{T("back")}</button>
                  <button className="btn q sm" onClick={doDesignX}>{T("forDesignX")}</button>
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

              {inSketch && edit === "outline" && (
                <div className="sketchbar">
                  <span className="num">{ring.length}</span>
                  <span>{T("sketchPoints")}</span>
                  <button className="btn q sm" disabled={ring.length === 0}
                          onClick={() => { setRing([]); setPending(null); say(T("outlineWiped")); }}>
                    {T("sketchWipe")}</button>
                  <button className="btn q sm" onClick={() => setRing(room.outline)}>
                    {T("sketchReset")}</button>
                  <button className="btn sm" disabled={ring.length < 3}
                          onClick={async () => {
                            await patch({ outlineOrder: ring }, true);
                            say(T("outlineApplied"));
                          }}>
                    {T("sketchApply")}</button>
                </div>
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
                      <dd>{T(selectedFace.role === "floor" ? "floorFace"
                        : selectedFace.role === "ceiling" ? "ceilingFace" : "wallFace")}</dd>
                      <dt>{T("area")}</dt><dd>{selectedFace.area.toFixed(2)} m²</dd>
                    </dl>
                  ) : <p className="quiet">—</p>}
                  {selectedFace?.role === "wall" && (
                    <>
                      <button className="btn sm delrow" onClick={doExportWall}
                              disabled={busy}>{T("exportWall")}</button>
                      <p className="quiet">{T("wallNote")}</p>
                    </>
                  )}
                </div>
              )}

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
