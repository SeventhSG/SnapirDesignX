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
import { useMemo } from "react";
import type { Point } from "./api";
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
  mode: EditMode;
  onPick: (name: string) => void;
  onPickLine: (seg: [string, string] | null) => void;
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
  points, segments, outline, draft, selected, pending, selectedLine,
  mode, onPick, onPickLine,
}: Props) {
  const key2 = (a: string, b: string) => [a, b].sort().join("|");
  const chosen = selectedLine ? key2(selectedLine[0], selectedLine[1]) : null;
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

  const ringPath = ring
    .map((n) => byName.get(n))
    .filter(Boolean)
    .map((p, i) => `${i ? "L" : "M"}${p!.x} ${-p!.y}`)
    .join(" ");

  return (
    <div className="sketch">
      <svg viewBox={box} preserveAspectRatio="xMidYMid meet">
        {/* Every surveyed line, drawn for what it is. */}
        {segments.map(([an, bn], i) => {
          const a = byName.get(an), b = byName.get(bn);
          if (!a || !b) return null;
          const st = LINE_STYLE[segmentKind(a, b)];
          const isSel = chosen === key2(an, bn);
          return (
            <g key={`${an}-${bn}-${i}`}>
              {/* A wide invisible line makes a 1px stroke easy to hit. */}
              <line x1={a.x} y1={-a.y} x2={b.x} y2={-b.y}
                    stroke="transparent" strokeWidth={14}
                    vectorEffect="non-scaling-stroke"
                    style={{ cursor: "pointer" }}
                    onClick={() => onPickLine(isSel ? null : [an, bn])} />
              <line x1={a.x} y1={-a.y} x2={b.x} y2={-b.y}
                    stroke={isSel ? "var(--ok)" : st.stroke}
                    strokeWidth={isSel ? st.w + 2.5 : st.w}
                    strokeDasharray={st.dash} strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                    style={{ pointerEvents: "none" }}
                    opacity={mode === "line" ? 1 : 0.85} />
            </g>
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
