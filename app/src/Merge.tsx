/**
 * Sketch merger: the rooms of one survey put into a single frame.
 *
 * Every room is measured from wherever the instrument stood, so a survey is a
 * dozen drawings each in its own coordinate system. Nothing in the file says
 * how they sit relative to each other, and nothing here guesses. You say which
 * corner in one room is which corner in another, and two of those fix a room:
 * the rotation and the shift that carry one onto the other.
 *
 * It is drawn in three dimensions because the case it exists for is a
 * stairwell, and a stairwell is the one thing a plan cannot show: its floors
 * sit on top of each other, so flat they land in the same place on the paper
 * and the corner you are reaching for is under three others. Stacked at their
 * own heights they are four separate things, and matching one to the next is a
 * matter of looking at it.
 *
 * A room already placed sits where it was solved to; a room not placed yet is
 * parked beside the work, out of the way but still clickable.
 */
import { useMemo, useState } from "react";
import { api, type MergeRoom, type MergeState } from "./api";
import MergeScene, { type MergeDraw } from "./MergeScene";
import { t, type Key, type Lang } from "./i18n";

/** One colour per room, so which drawing a corner came from is never in doubt
 *  while you are matching it to another. */
const ROOM_INK = ["#A87A26", "#3B7455", "#3D6D96", "#9A5BA8", "#B0653C", "#5A7A2A"];

interface Pick { room: string; point?: string; line?: [string, string] }

/** A room's own coordinates, carried into the project's frame. */
function place(r: MergeRoom, park: [number, number],
               x: number, y: number, z: number): [number, number, number] {
  if (!r.placed) return [x + park[0], y + park[1], z];
  const rad = ((r.rotationDeg ?? 0) * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  return [x * cos - y * sin + (r.dx ?? 0),
          x * sin + y * cos + (r.dy ?? 0),
          z + (r.dz ?? 0)];
}

export default function Merge({
  projectId, projectName, lang, dark, onClose, onSay,
}: {
  projectId: string; projectName: string; lang: Lang; dark: boolean;
  onClose: () => void; onSay: (m: string, bad?: boolean) => void;
}) {
  const T = (k: Key) => t(lang, k);
  const [state, setState] = useState<MergeState | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [busy, setBusy] = useState(false);
  const [fitKey, setFitKey] = useState(0);
  const [loaded, setLoaded] = useState(false);

  if (!loaded) {
    setLoaded(true);
    void api.merge(projectId)
      .then((s) => { setState(s); setFitKey((k) => k + 1); })
      .catch((e) => onSay((e as Error).message, true));
  }

  /* A room nobody has placed is parked in a row beside everything that has
     been, far enough out that it never sits on top of the work. Its own height
     is kept: a floor parked at its surveyed level still reads as that floor. */
  const parks = useMemo(() => {
    const out = new Map<string, [number, number]>();
    if (!state) return out;
    let right = -Infinity;
    for (const r of state.rooms) {
      if (!r.placed) continue;
      for (const p of r.points)
        right = Math.max(right, place(r, [0, 0], p.x, p.y, p.z)[0]);
    }
    if (right === -Infinity) right = 0;
    let cursor = right + 500;
    for (const r of state.rooms) {
      if (r.placed) continue;
      let minX = Infinity, maxX = -Infinity, midY = 0;
      for (const p of r.points) {
        minX = Math.min(minX, p.x);
        maxX = Math.max(maxX, p.x);
        midY += p.y;
      }
      if (!Number.isFinite(minX)) { minX = 0; maxX = 0; }
      midY = r.points.length ? midY / r.points.length : 0;
      out.set(r.name, [cursor - minX, -midY]);
      cursor += (maxX - minX) + 400;
    }
    return out;
  }, [state]);

  /* What the scene draws: every room, in the project's frame, with the pairs
     and the pick already worked out so the scene itself decides nothing. */
  const draw = useMemo<MergeDraw[]>(() => {
    if (!state) return [];
    return state.rooms.map((r, i) => {
      const park = parks.get(r.name) ?? [0, 0] as [number, number];
      const by = new Map(r.points.map((p) => [p.name, p]));
      const paired = new Set<string>();
      for (const p of state.pairs) {
        if (p.roomA === r.name) paired.add(p.pointA);
        if (p.roomB === r.name) paired.add(p.pointB);
      }
      return {
        room: r.name,
        colour: ROOM_INK[i % ROOM_INK.length],
        placed: r.placed,
        points: r.points.map((p) => ({
          name: p.name,
          at: place(r, park, p.x, p.y, p.z),
          role: p.role,
          paired: paired.has(p.name),
          picked: pick?.room === r.name && pick.point === p.name,
        })),
        lines: r.segments.flatMap(([a, b]) => {
          const p = by.get(a), q = by.get(b);
          if (!p || !q) return [];
          return [{
            a, b,
            from: place(r, park, p.x, p.y, p.z),
            to: place(r, park, q.x, q.y, q.z),
            picked: !!(pick?.room === r.name && pick.line &&
              ((pick.line[0] === a && pick.line[1] === b) ||
               (pick.line[0] === b && pick.line[1] === a))),
          }];
        }),
      };
    });
  }, [state, parks, pick]);

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
    // A second click in the same room is a change of mind, not a match.
    if (!pick || pick.room === room || !pick.point) { setPick({ room, point }); return; }
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

  /* Two matches on a short baseline fix a heading out of a couple of
     centimetres of difference between two readings, and a corner matched to
     the wrong corner fixes it out of nothing. Either way the room lands
     attached and facing the wrong way, and the solver cannot say so - by its
     own measure it is the best answer there is. So the operator says. */
  const turn = async (name: string, by: number) => {
    setBusy(true);
    try { setState(await api.patchMerge(projectId, { turn: { room: name, by } })); }
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

  if (!state) return <div className="page"><p className="quiet">…</p></div>;

  const ink = new Map(state.rooms.map((r, i) => [r.name, ROOM_INK[i % ROOM_INK.length]]));
  const placedCount = state.rooms.filter((r) => r.placed).length;

  return (
    <div className="mergescreen">
      <div className="mergehead">
        <button className="btn q sm" onClick={onClose}>{T("back")}</button>
        <h2>{T("mergeTitle")}</h2>
        <span className="quiet">{projectName}</span>
        <div className="mergeacts">
          <button className="btn q sm" onClick={() => setFitKey((k) => k + 1)}>
            {T("mergeFit")}</button>
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
        <MergeScene draw={draw} dark={dark} fitKey={fitKey}
                    onPickPoint={clickPoint} onPickLine={clickLine}
                    onClear={() => setPick(null)} />

        <aside className="mergeside">
          <h4>{T("rooms")}</h4>
          {state.rooms.map((r) => (
            <div key={r.name} className={"mroom" + (r.placed ? "" : " loose")}>
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
              <div className="mturn">
                {/* A quarter turn either way, about the match, so the room
                    swings round the corner it was pinned by. */}
                <button className="btn q sm" disabled={busy} title={T("mergeTurnHelp")}
                        onClick={() => turn(r.name, -1)}>↺</button>
                {r.turn > 0 && <span className="num">{r.turn * 90}°</span>}
                <button className="btn q sm" disabled={busy} title={T("mergeTurnHelp")}
                        onClick={() => turn(r.name, 1)}>↻</button>
                {r.name !== state.anchor && (
                  <button className="btn q sm" disabled={busy}
                          onClick={() => setAnchor(r.name)}>{T("mergeSetAnchor")}</button>
                )}
              </div>
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
