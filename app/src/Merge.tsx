/**
 * Sketch merger: the rooms of one survey put into a single frame.
 *
 * Every room is measured from wherever the instrument stood, so a survey is a
 * dozen drawings each in its own coordinate system. Nothing in the file says
 * how they sit relative to each other, and nothing here guesses. You say which
 * corner in one room is which corner in another, and two of those fix a room:
 * the rotation and the shift that carry one onto the other.
 *
 * Everything is drawn in one plan. A room already placed sits where it was
 * solved to; a room not placed yet is parked to the right, out of the way, so
 * its corners can still be clicked. Clicking a corner in one room and then a
 * corner in another makes the pair, and the whole thing re-solves.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type MergeRoom, type MergeState } from "./api";
import { t, type Key, type Lang } from "./i18n";

const ROLE_COLOR: Record<string, string> = {
  floor: "#26262A", ceiling: "#9E9D95", opening: "#A87A26",
  socket: "#0F8A4E", plumbing: "#3D7A96", control: "#7C7B82",
  station: "#7C7B82", stairs: "#8A5CC4", pervaz: "#B07A3C",
  depth: "#C0483C", unknown: "#CB4A2A",
};

/** One colour per placed room, so which drawing a corner came from is never
 *  in doubt while you are matching it to another. */
const ROOM_INK = ["#A87A26", "#3B7455", "#3D6D96", "#9A5BA8", "#B0653C", "#5A7A2A"];

interface Pick { room: string; point?: string; line?: [string, string] }

function place(p: [number, number], r: MergeRoom, park: [number, number]) {
  if (!r.placed) return [p[0] + park[0], p[1] + park[1]] as [number, number];
  const rad = ((r.rotationDeg ?? 0) * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  return [p[0] * cos - p[1] * sin + (r.dx ?? 0),
          p[0] * sin + p[1] * cos + (r.dy ?? 0)] as [number, number];
}

export default function Merge({
  projectId, projectName, lang, onClose, onSay,
}: {
  projectId: string; projectName: string; lang: Lang;
  onClose: () => void; onSay: (m: string, bad?: boolean) => void;
}) {
  const T = (k: Key) => t(lang, k);
  const [state, setState] = useState<MergeState | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState({ x: 0, y: 0, w: 1000, h: 1000 });
  const framed = useRef(false);
  const svg = useRef<SVGSVGElement>(null);

  const load = async () => {
    try { setState(await api.merge(projectId)); }
    catch (e) { onSay((e as Error).message, true); }
  };
  useEffect(() => { void load(); /* eslint-disable-next-line */ }, [projectId]);

  /* A room nobody has placed is parked in a column to the right of everything
     that has been, far enough out that it never sits on top of the work. */
  const parks = useMemo(() => {
    const out = new Map<string, [number, number]>();
    if (!state) return out;
    let right = -Infinity, top = 0;
    for (const r of state.rooms) {
      if (!r.placed) continue;
      for (const p of r.outline) {
        const [x, y] = place([p[0], p[1]], r, [0, 0]);
        right = Math.max(right, x);
        top = Math.max(top, y);
      }
    }
    if (right === -Infinity) { right = 0; top = 0; }
    let cursor = top;
    for (const r of state.rooms) {
      if (r.placed) continue;
      let minX = Infinity, minY = Infinity, maxY = -Infinity;
      for (const p of r.outline.length ? r.outline
                                      : r.points.map((q) => [q.x, q.y, q.z] as const)) {
        minX = Math.min(minX, p[0]);
        minY = Math.min(minY, p[1]);
        maxY = Math.max(maxY, p[1]);
      }
      if (!Number.isFinite(minX)) { minX = 0; minY = 0; maxY = 0; }
      out.set(r.name, [right + 400 - minX, cursor - maxY]);
      cursor -= (maxY - minY) + 300;
    }
    return out;
  }, [state]);

  const park = (name: string) => parks.get(name) ?? [0, 0] as [number, number];

  /** Everything on screen, in project centimetres. */
  const bounds = useMemo(() => {
    let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
    for (const r of state?.rooms ?? []) {
      for (const q of r.points) {
        const [x, y] = place([q.x, q.y], r, park(r.name));
        a = Math.min(a, x); b = Math.min(b, y);
        c = Math.max(c, x); d = Math.max(d, y);
      }
    }
    return Number.isFinite(a) ? { a, b, c, d } : { a: 0, b: 0, c: 100, d: 100 };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, parks]);

  useEffect(() => {
    if (!state || framed.current) return;
    framed.current = true;
    fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const fit = () => {
    const pad = Math.max((bounds.c - bounds.a) * 0.06, 60);
    setView({ x: bounds.a - pad, y: bounds.b - pad,
              w: (bounds.c - bounds.a) + pad * 2, h: (bounds.d - bounds.b) + pad * 2 });
  };

  /* ---------------- pairing ---------------- */

  const pair = async (body: Record<string, unknown>) => {
    setBusy(true);
    try {
      setState(await api.addMergePair(projectId, body));
      onSay(T("mergePaired"));
    } catch (e) { onSay((e as Error).message, true); }
    finally { setBusy(false); setPick(null); }
  };

  const clickPoint = (room: string, point: string) => {
    if (!pick) { setPick({ room, point }); return; }
    if (pick.room === room) { setPick({ room, point }); return; }
    if (!pick.point) { setPick({ room, point }); return; }
    void pair({ roomA: pick.room, pointA: pick.point, roomB: room, pointB: point });
  };

  const clickLine = (room: string, line: [string, string]) => {
    if (!pick || pick.room === room || !pick.line) { setPick({ room, line }); return; }
    void pair({ roomA: pick.room, lineA: pick.line, roomB: room, lineB: line });
  };

  const dropPair = async (index: number) => {
    setBusy(true);
    try { setState(await api.dropMergePair(projectId, index)); }
    catch (e) { onSay((e as Error).message, true); }
    finally { setBusy(false); }
  };

  const setAnchor = async (name: string) => {
    setBusy(true);
    try { setState(await api.patchMerge(projectId, { anchor: name })); }
    catch (e) { onSay((e as Error).message, true); }
    finally { setBusy(false); }
  };

  const clearAll = async () => {
    setBusy(true);
    try {
      setState(await api.patchMerge(projectId, { clear: true }));
      onSay(T("mergeCleared"));
    } catch (e) { onSay((e as Error).message, true); }
    finally { setBusy(false); setPick(null); }
  };

  const exportMerged = async () => {
    setBusy(true);
    try {
      const r = await api.exportMerge(projectId);
      onSay(`${T("merged")} · ${r.rooms} ${T("rooms")} · ${r.how === "fused"
        ? T("mergeFused") : T("mergeSideBySide")} · ${(r.bytes / 1024).toFixed(0)} KB`);
      (window as any).snapir?.reveal(r.path);
    } catch (e) { onSay((e as Error).message, true); }
    finally { setBusy(false); }
  };

  /* ---------------- view ---------------- */

  const wheel = (e: React.WheelEvent) => {
    const k = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    setView((v) => ({ x: v.x - (v.w * k - v.w) / 2, y: v.y - (v.h * k - v.h) / 2,
                      w: v.w * k, h: v.h * k }));
  };

  const drag = useRef<{ x: number; y: number } | null>(null);
  const down = (e: React.PointerEvent) => {
    if (e.target === svg.current) { drag.current = { x: e.clientX, y: e.clientY };
                                    setPick(null); }
  };
  const move = (e: React.PointerEvent) => {
    if (!drag.current || !svg.current) return;
    const box = svg.current.getBoundingClientRect();
    const per = view.w / box.width;
    const dx = (e.clientX - drag.current.x) * per;
    const dy = (e.clientY - drag.current.y) * per;
    drag.current = { x: e.clientX, y: e.clientY };
    setView((v) => ({ ...v, x: v.x - dx, y: v.y + dy }));
  };
  const up = () => { drag.current = null; };

  if (!state) return <div className="page"><p className="quiet">…</p></div>;

  const scale = view.w / 1000;
  const ink = new Map(state.rooms.map((r, i) => [r.name, ROOM_INK[i % ROOM_INK.length]]));
  const placedCount = state.rooms.filter((r) => r.placed).length;

  return (
    <div className="mergescreen">
      <div className="mergehead">
        <button className="btn q sm" onClick={onClose}>{T("back")}</button>
        <h2>{T("mergeTitle")}</h2>
        <span className="quiet">{projectName}</span>
        <div className="mergeacts">
          <button className="btn q sm" onClick={fit}>{T("mergeFit")}</button>
          <button className="btn q sm" disabled={busy || !state.pairs.length}
                  onClick={clearAll}>{T("mergeClear")}</button>
          <button className="btn sm" disabled={busy || placedCount < 2}
                  onClick={exportMerged}>{T("mergeExport")}</button>
        </div>
      </div>

      <p className="mergehint">
        {pick
          ? `${T("mergePickSecond")} — ${pick.room} · ${pick.point ?? pick.line?.join(" – ")}`
          : T("mergePickFirst")}
      </p>

      <div className="mergebody">
        <svg ref={svg} className="mergeplan"
             viewBox={`${view.x} ${-view.y - view.h} ${view.w} ${view.h}`}
             onWheel={wheel} onPointerDown={down} onPointerMove={move}
             onPointerUp={up} onPointerLeave={up}>
          {/* Y is flipped once, here, so every coordinate below is the survey's
              own and nothing downstream has to remember the difference. */}
          <g transform="scale(1,-1)">
            {state.rooms.map((r) => {
              const colour = ink.get(r.name)!;
              const at = (n: string) => {
                const q = r.points.find((p) => p.name === n);
                return q ? place([q.x, q.y], r, park(r.name)) : null;
              };
              return (
                <g key={r.name} opacity={r.placed ? 1 : 0.5}>
                  {r.segments.map(([a, b], i) => {
                    const p = at(a), q = at(b);
                    if (!p || !q) return null;
                    const on = pick?.room === r.name && pick.line &&
                      ((pick.line[0] === a && pick.line[1] === b) ||
                       (pick.line[0] === b && pick.line[1] === a));
                    return (
                      <line key={i} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]}
                            stroke={on ? "#C99B3F" : colour}
                            strokeWidth={(on ? 3.5 : 1.2) * scale}
                            strokeOpacity={on ? 1 : 0.55}
                            className="mline"
                            onClick={(e) => { e.stopPropagation();
                                              clickLine(r.name, [a, b]); }} />
                    );
                  })}
                  {r.outline.length > 2 && (
                    <polygon
                      points={r.outline.map((p) => place([p[0], p[1]], r, park(r.name))
                        .join(",")).join(" ")}
                      fill={colour} fillOpacity={0.08} stroke={colour}
                      strokeWidth={2.2 * scale} pointerEvents="none" />
                  )}
                  {r.points.map((q) => {
                    const [x, y] = place([q.x, q.y], r, park(r.name));
                    const on = pick?.room === r.name && pick.point === q.name;
                    const paired = state.pairs.some(
                      (p) => (p.roomA === r.name && p.pointA === q.name) ||
                             (p.roomB === r.name && p.pointB === q.name));
                    return (
                      <circle key={q.name} cx={x} cy={y}
                              r={(on ? 7 : paired ? 5.5 : 3.4) * scale}
                              fill={on ? "#C99B3F" : paired ? colour
                                    : ROLE_COLOR[q.role] ?? "#7C7B82"}
                              stroke={paired ? "#FFFFFF" : "none"}
                              strokeWidth={1.4 * scale}
                              className="mdot"
                              onClick={(e) => { e.stopPropagation();
                                                clickPoint(r.name, q.name); }}>
                        <title>{`${r.name} · ${q.name} · ${q.role}`}</title>
                      </circle>
                    );
                  })}
                </g>
              );
            })}
          </g>
        </svg>

        <aside className="mergeside">
          <h4>{T("rooms")}</h4>
          {state.rooms.map((r) => (
            <div key={r.name}
                 className={"mroom" + (r.placed ? "" : " loose")}>
              <i style={{ background: ink.get(r.name) }} />
              <div>
                <b>{r.name}</b>
                <span className="quiet">
                  {r.name === state.anchor ? T("mergeAnchor")
                    : r.placed
                      ? `${T("mergeVia")} ${r.via} · ${r.pairs} · ${r.residual} cm`
                      : T("mergeUnplaced")}
                </span>
              </div>
              {r.name !== state.anchor && (
                <button className="btn q sm" disabled={busy}
                        onClick={() => setAnchor(r.name)}>{T("mergeSetAnchor")}</button>
              )}
            </div>
          ))}

          <h4>{T("mergePairs")} <span className="num">{state.pairs.length}</span></h4>
          {state.pairs.length === 0 && <p className="quiet">{T("mergeNoPairs")}</p>}
          {state.pairs.map((p) => (
            <div className="mpair" key={p.index}>
              <span>{p.roomA} · {p.pointA}</span>
              <span className="quiet">=</span>
              <span>{p.roomB} · {p.pointB}</span>
              <button className="btn q sm" disabled={busy}
                      onClick={() => dropPair(p.index)}>×</button>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
}
