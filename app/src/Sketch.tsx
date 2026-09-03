/**
 * Flat plan of the survey, and where the drawing gets corrected.
 *
 * Every line in this view came from the survey file or from the operator.
 * Nothing is drawn that the room does not actually claim.
 *
 * Outline: click floor corners in order to lay the room outline.
 * Line:    click two points to connect them, click the same pair to unlink.
 * Layer:   click a point to select it and set what it is.
 */
import { useMemo, useRef, useState } from "react";
import type { Crossing, Point } from "./api";
import { ROLE_COLOR } from "./Viewport";

export type EditMode = "outline" | "line" | "layer";

interface Props {
  points: Point[];
  segments: [string, string][];
  outline: string[];
  draft: string[];
  selected: string | null;
  pending: string | null;          // first end of a line being drawn
  selectedLine: [string, string] | null;
  crossings: Crossing[];
  mode: EditMode;
  onPick: (name: string) => void;
  onPickLine: (seg: [string, string] | null) => void;
  /** Drag a selected line's end further along its own direction. */
  onExtend: (seg: [string, string], end: string, to: [number, number]) => void;
  /** Turn a place where two lines cross into a corner. */
  onAdoptCrossing: (c: Crossing) => void;
}

/** What a line is, judged only by what it joins. */
export function segmentKind(a: Point, b: Point): string {
  const r = new Set([a.role, b.role]);
  if (r.size === 1 && r.has("floor")) return "floor";
  if (r.size === 1 && r.has("ceiling")) return "ceiling";
  if (r.has("floor") && r.has("ceiling")) return "link";
  if (r.has("opening")) return "opening";
  return "other";
}

const LINE_STYLE: Record<string, { stroke: string; w: number; dash?: string }> = {
  floor: { stroke: "var(--gold)", w: 3 },
  ceiling: { stroke: "var(--ink-3)", w: 1.4 },
  link: { stroke: "var(--ink-3)", w: 1.2, dash: "5 5" },
  opening: { stroke: "var(--gold-ink)", w: 1.8 },
  other: { stroke: "var(--line-3)", w: 1.2 },
};

export default function Sketch({
  points, segments, outline, draft, selected, pending, selectedLine, crossings,
  mode, onPick, onPickLine, onExtend, onAdoptCrossing,
}: Props) {
  const key2 = (a: string, b: string) => [a, b].sort().join("|");
  const chosen = selectedLine ? key2(selectedLine[0], selectedLine[1]) : null;
  const svg = useRef<SVGSVGElement>(null);
  // While dragging, the moving end is drawn from here rather than from the
  // point, so the line follows the finger without a round trip to the backend.
  const [drag, setDrag] = useState<{ end: string; at: [number, number] } | null>(null);
  const box = useMemo(() => {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const pad = 45;
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    return `${minX - pad} ${-maxY - pad} ` +
           `${Math.max(maxX - minX, 1) + pad * 2} ${Math.max(maxY - minY, 1) + pad * 2}`;
  }, [points]);

  const byName = useMemo(() => new Map(points.map((p) => [p.name, p])), [points]);
  const ring = mode === "outline" ? draft : outline;

  /** Pointer position in survey centimetres. */
  const atCursor = (e: React.PointerEvent): [number, number] => {
    const m = svg.current?.getScreenCTM();
    if (!m) return [0, 0];
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return [pt.x, -pt.y];                 // the view draws y downward
  };

  /**
   * Where the dragged end lands: the foot of the cursor on the line's own
   * direction, never off it. A wall's direction was measured; only how far it
   * runs is in question, so dragging may lengthen or shorten a line and may
   * not swing it.
   */
  const alongLine = (fixed: Point, moving: Point, to: [number, number]): [number, number] => {
    const dx = moving.x - fixed.x, dy = moving.y - fixed.y;
    const len2 = dx * dx + dy * dy;
    if (len2 < 1e-9) return to;
    const t = ((to[0] - fixed.x) * dx + (to[1] - fixed.y) * dy) / len2;
    return [fixed.x + dx * t, fixed.y + dy * t];
  };

  const handles: { name: string; other: string; at: [number, number] }[] = [];
  if (selectedLine) {
    const [an, bn] = selectedLine;
    const a = byName.get(an), b = byName.get(bn);
    if (a && b) {
      handles.push({ name: an, other: bn, at: [a.x, a.y] });
      handles.push({ name: bn, other: an, at: [b.x, b.y] });
    }
  }

  const ringPath = ring
    .map((n) => byName.get(n))
    .filter(Boolean)
    .map((p, i) => `${i ? "L" : "M"}${p!.x} ${-p!.y}`)
    .join(" ");

  return (
    <div className="sketch">
      <svg ref={svg} viewBox={box} preserveAspectRatio="xMidYMid meet">
        {/* Every surveyed line, drawn for what it is. */}
        {segments.map(([an, bn], i) => {
          const a = byName.get(an), b = byName.get(bn);
          if (!a || !b) return null;
          // A line whose end is being dragged follows the finger straight
          // away, rather than waiting for the backend to agree.
          const pull = (p: Point): [number, number] =>
            drag && drag.end === p.name ? drag.at : [p.x, p.y];
          const [ax, ay] = pull(a), [bx, by] = pull(b);
          const st = LINE_STYLE[segmentKind(a, b)];
          const isSel = chosen === key2(an, bn);
          return (
            <g key={`${an}-${bn}-${i}`}>
              {/* A wide invisible line makes a 1px stroke easy to hit. */}
              <line x1={ax} y1={-ay} x2={bx} y2={-by}
                    stroke="transparent" strokeWidth={14}
                    vectorEffect="non-scaling-stroke"
                    style={{ cursor: "pointer" }}
                    onClick={() => onPickLine(isSel ? null : [an, bn])} />
              <line x1={ax} y1={-ay} x2={bx} y2={-by}
                    stroke={isSel ? "var(--ok)" : st.stroke}
                    strokeWidth={isSel ? st.w + 2.5 : st.w}
                    strokeDasharray={st.dash} strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                    style={{ pointerEvents: "none" }}
                    opacity={mode === "line" ? 1 : 0.85} />
            </g>
          );
        })}

        {/* Where two lines cross. Tap one to make it a corner. */}
        {crossings.map((c, i) => (
          <g key={`x-${i}`} style={{ cursor: "pointer" }}
             onClick={() => onAdoptCrossing(c)}>
            <circle cx={c.at[0]} cy={-c.at[1]} r={13} fill="transparent" />
            <circle cx={c.at[0]} cy={-c.at[1]} r={7} fill="none"
                    stroke="var(--ok)" strokeWidth={2.4} strokeDasharray="3 3"
                    vectorEffect="non-scaling-stroke" />
            <title>Two lines cross here - tap to make it a corner</title>
          </g>
        ))}

        {/* Grab either end of the selected line to run it further. */}
        {handles.map((h) => {
          const at = drag && drag.end === h.name ? drag.at : h.at;
          return (
            <circle key={`h-${h.name}`} cx={at[0]} cy={-at[1]} r={10}
                    fill="var(--ok)" stroke="var(--panel)" strokeWidth={2.5}
                    vectorEffect="non-scaling-stroke"
                    style={{ cursor: "grab", touchAction: "none" }}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      (e.target as Element).setPointerCapture(e.pointerId);
                      setDrag({ end: h.name, at: h.at });
                    }}
                    onPointerMove={(e) => {
                      if (!drag || drag.end !== h.name) return;
                      const fixed = byName.get(h.other), moving = byName.get(h.name);
                      if (!fixed || !moving) return;
                      setDrag({ end: h.name, at: alongLine(fixed, moving, atCursor(e)) });
                    }}
                    onPointerUp={(e) => {
                      if (drag && drag.end === h.name && selectedLine) {
                        const moved = Math.hypot(drag.at[0] - h.at[0], drag.at[1] - h.at[1]);
                        if (moved > 1) onExtend(selectedLine, h.name, drag.at);
                      }
                      (e.target as Element).releasePointerCapture(e.pointerId);
                      setDrag(null);
                    }} />
          );
        })}

        {/* The outline being drawn, over the top of everything. */}
        {ring.length > 1 && (
          <path d={ringPath + (ring.length > 2 ? " Z" : "")}
                fill={ring.length > 2
                  ? "color-mix(in srgb, var(--gold) 11%, transparent)" : "none"}
                stroke="var(--gold)" strokeWidth={3.4}
                strokeLinejoin="round" strokeLinecap="round"
                vectorEffect="non-scaling-stroke" />
        )}

        {points.map((p) => {
          const at = ring.indexOf(p.name);
          const onRing = at !== -1;
          const isSel = p.name === selected;
          const isPending = p.name === pending;
          const r = isSel || isPending ? 11 : onRing ? 9 : 6;
          return (
            <g key={p.name}>
              {(isSel || isPending) && (
                <circle cx={p.x} cy={-p.y} r={r + 6} fill="none"
                        stroke={isPending ? "var(--ok)" : "var(--gold)"}
                        strokeWidth={2} opacity={0.6}
                        vectorEffect="non-scaling-stroke" />
              )}
              <circle cx={p.x} cy={-p.y} r={r}
                      fill={onRing ? "var(--gold)" : ROLE_COLOR[p.role] ?? "#7C7B82"}
                      stroke={onRing ? "var(--gold-ink)" : "var(--panel)"}
                      strokeWidth={2} vectorEffect="non-scaling-stroke"
                      onClick={() => onPick(p.name)}>
                <title>{`${p.name} · ${p.role} · z ${p.z.toFixed(1)} cm`}</title>
              </circle>
              {onRing && mode === "outline" && (
                <text x={p.x} y={-p.y + 4} textAnchor="middle"
                      fontSize={11} fontWeight={700} fill="var(--on-gold)"
                      style={{ pointerEvents: "none" }}>{at + 1}</text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
