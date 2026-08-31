/**
 * Which way a panorama was pointing.
 *
 * The survey already pins five of the six degrees of freedom: the instrument
 * writes its own position into the room CSV, and it is levelled, so the only
 * unknown is the yaw. Nothing in the export carries it. Not the CSV, not the
 * FUKOKU field report, and not the JPEG, which arrives as bare JFIF with no
 * EXIF and no XMP. So it is recovered from the picture itself.
 *
 * Two independent things in the image say where the room is, and the answer is
 * only trusted when both say the same thing:
 *
 *   corners  A wall corner is a vertical line, at a column fixed by its
 *            azimuth. A handful of short marks.
 *   rings    Where the walls meet the floor and the ceiling is a long curve
 *            running the whole way round the picture, and its shape is fixed
 *            by the room. Far more evidence than the corners, and it is what
 *            separates the true heading from a plausible one.
 *
 * Both reduce to the same operation. Every candidate heading shifts the whole
 * prediction by the same amount, so scoring all of them is a circular
 * correlation over one scalar, and the peak is the heading.
 *
 * A room whose corners sit evenly around the station scores the same at
 * several headings -- a square with the instrument in the middle is the worst
 * case, and there is no answer there to find. That is what the confidence
 * measures, and an unconfident heading is refused rather than drawn wrong.
 */
import type { Room, Station } from "./api";

const TAU = Math.PI * 2;

/** Working size. The shots are 4000x2000; the browser box-filters on the way
 *  down, which is the smoothing the gradients want anyway. */
const W = 1024;
const H = 512;

/** Rows outside the middle half are the stretched poles, where the tripod and
 *  the ceiling light live and where a wall corner is not a straight line. */
const BAND = 0.25;

/** Two headings closer than this are the same answer, not rivals. */
const GUARD = (14 * Math.PI) / 180;

/** Samples along each wall. The rings are curves in an equirectangular frame,
 *  so they have to be walked rather than drawn corner to corner. */
const PER_WALL = 40;

/** A corner is not a line if the instrument was almost touching it. */
const MIN_RANGE_CM = 30;

/** How far the peak must stand above the rival headings, in standard
 *  deviations, before the panorama is allowed to claim it knows where it is
 *  looking. Set from the reference survey: see docs/PANORAMA.md. */
export const MIN_CONFIDENCE = 6.0;

export interface Pose {
  /** Index into room.stations: where this shot was taken from. */
  station: number;
  /** Index into the room's panorama folder. */
  panorama: number;
  /** Survey azimuth, in radians, that image column 0 faces. */
  heading: number;
  /** Peak height over the rival headings, in standard deviations. */
  confidence: number;
}

/* ---------------- the picture ---------------- */

/** What the image has to say, in the two forms the room can be matched to. */
export interface Field {
  /** Vertical-edge energy per column, normalised. */
  columns: Float32Array;
  /** Horizontal-edge energy per pixel, normalised. W * H. */
  rows: Float32Array;
}

function load(url: string): Promise<HTMLImageElement> {
  return new Promise((ok, fail) => {
    const img = new Image();
    // Both backends send Access-Control-Allow-Origin, so the canvas stays
    // readable. Without this the pixels come back as a security error.
    img.crossOrigin = "anonymous";
    img.onload = () => ok(img);
    img.onerror = () => fail(new Error("panorama would not load"));
    img.src = url;
  });
}

/** Centre and scale in place, so a bright room and a dim one score alike. */
function standardise(a: Float32Array): void {
  let mean = 0;
  for (let i = 0; i < a.length; i++) mean += a[i];
  mean /= a.length;
  let variance = 0;
  for (let i = 0; i < a.length; i++) variance += (a[i] - mean) ** 2;
  const sd = Math.sqrt(variance / a.length) || 1;
  for (let i = 0; i < a.length; i++) a[i] = (a[i] - mean) / sd;
}

/**
 * Read one panorama into the two gradient fields.
 *
 * A vertical line is a change across the image and a floor or ceiling line is
 * a change down it, so both gradients are taken and kept separately. The image
 * wraps, so the first and last columns are neighbours and are treated as such.
 */
export async function readPanorama(url: string): Promise<Field> {
  const img = await load(url);
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const g = canvas.getContext("2d", { willReadFrequently: true })!;
  g.drawImage(img, 0, 0, W, H);
  const { data } = g.getImageData(0, 0, W, H);

  const luma = new Float32Array(W * H);
  for (let i = 0; i < W * H; i++) {
    luma[i] = 0.2126 * data[i * 4] + 0.7152 * data[i * 4 + 1] + 0.0722 * data[i * 4 + 2];
  }

  const columns = new Float32Array(W);
  const y0 = Math.round(H * BAND);
  const y1 = H - y0;
  for (let y = y0; y < y1; y++) {
    const row = y * W;
    for (let x = 0; x < W; x++) {
      columns[x] += Math.abs(luma[row + ((x + 1) % W)] - luma[row + ((x + W - 1) % W)]);
    }
  }
  standardise(columns);

  const rows = new Float32Array(W * H);
  for (let y = 1; y < H - 1; y++) {
    for (let x = 0; x < W; x++) {
      rows[y * W + x] = Math.abs(luma[(y + 1) * W + x] - luma[(y - 1) * W + x]);
    }
  }
  standardise(rows);

  return { columns, rows };
}

/* ---------------- what the room predicts ---------------- */

/** A vertical the room predicts. */
interface Corner {
  azimuth: number;
  /** How much of the frame it fills, which is how much it should count. */
  weight: number;
}

/** A point on a floor or ceiling ring. Its row does not move with heading. */
interface Sample {
  azimuth: number;
  row: number;
}

/**
 * Where a survey azimuth lands, as a column.
 *
 * Azimuth runs the opposite way to the image: the camera writes its sphere
 * left-handed against the survey frame. That is a property of the instrument
 * rather than of any room, and it is the same on all 34 panoramas in the
 * reference survey, so it is fixed here rather than searched for. A camera
 * that did it the other way would fail to solve any room at all, which is the
 * safe way to be wrong about it.
 *
 * Everything that draws a panorama goes through this, so the convention is
 * stated once.
 */
export function columnOf(azimuth: number, heading: number): number {
  const phi = heading - azimuth;
  return ((((phi % TAU) + TAU) % TAU) / TAU) * W;
}

/** The width the columns are measured in, for anything drawing alongside. */
export const COLUMNS = W;

/** Where a height lands, as a row. This does not move with the heading. */
function rowAt(dz: number, range: number): number {
  return Math.round((0.5 - Math.atan2(dz, range) / Math.PI) * H);
}

/**
 * Every vertical the room should show from this station, weighted by how much
 * of the frame it fills. A corner two metres away runs floor to ceiling; the
 * same corner across a salon is a short mark, and should not outvote it.
 */
function cornersFrom(room: Room, st: Station): Corner[] {
  const out: Corner[] = [];
  const floorZ = room.floorZ ?? 0;
  const ceilZ = floorZ + (room.ceilingHeight ?? 250);

  const add = (x: number, y: number, top: number, bottom: number) => {
    const range = Math.hypot(x - st.x, y - st.y);
    if (range < MIN_RANGE_CM) return;
    const weight =
      Math.atan2(top - st.z, range) + Math.atan2(st.z - bottom, range);
    if (weight <= 0) return;
    out.push({ azimuth: Math.atan2(y - st.y, x - st.x), weight });
  };

  const named = new Map(room.points.map((p) => [p.name, p]));
  for (const name of room.outline) {
    const p = named.get(name);
    if (p) add(p.x, p.y, ceilZ, floorZ);
  }

  // Door and window jambs are the strongest verticals in a room: a frame is
  // built to contrast with the wall it sits in.
  for (const o of room.openings) {
    add(o.left[0], o.left[1], floorZ + o.head, floorZ + o.sill);
    add(o.right[0], o.right[1], floorZ + o.head, floorZ + o.sill);
  }
  return out;
}

/**
 * The floor and ceiling rings, walked wall by wall. In an equirectangular
 * frame a straight wall is a curve, so it is sampled rather than drawn.
 */
function ringFrom(room: Room, st: Station): Sample[] {
  const named = new Map(room.points.map((p) => [p.name, p]));
  const ring = room.outline
    .map((n) => named.get(n))
    .filter((p): p is NonNullable<typeof p> => !!p);
  if (ring.length < 3) return [];

  const floorZ = room.floorZ ?? 0;
  const ceilZ = floorZ + (room.ceilingHeight ?? 250);
  const out: Sample[] = [];

  for (const z of [floorZ, ceilZ]) {
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      for (let s = 0; s < PER_WALL; s++) {
        const t = s / PER_WALL;
        const x = a.x + (b.x - a.x) * t;
        const y = a.y + (b.y - a.y) * t;
        const range = Math.hypot(x - st.x, y - st.y);
        if (range < MIN_RANGE_CM) continue;
        const row = rowAt(z - st.z, range);
        if (row < 1 || row >= H - 1) continue;
        out.push({ azimuth: Math.atan2(y - st.y, x - st.x), row });
      }
    }
  }
  return out;
}

/* ---------------- the search ---------------- */

export interface Scored {
  heading: number;
  confidence: number;
}

/**
 * Score every heading in both senses and report the peak, and how far clear of
 * everything else it stands.
 *
 * The corner score and the ring score are standardised separately before they
 * are added, so neither can drown the other out: the rings carry more samples,
 * the corners carry sharper ones, and the heading that satisfies both at once
 * is the one worth trusting.
 */
export function solveHeading(
  field: Field,
  corners: Corner[],
  ring: Sample[],
): Scored | null {
  if (corners.length < 3 || ring.length < 3 * PER_WALL) return null;

  let cornerTotal = 0;
  for (const c of corners) cornerTotal += c.weight;
  if (!cornerTotal) return null;

  // Every candidate heading is the same prediction, shifted, so the columns
  // are worked out once and stepped round the picture.
  const cornerAt = corners.map((c) => columnOf(c.azimuth, 0) | 0);
  const ringAt = ring.map((s) => columnOf(s.azimuth, 0) | 0);

  const N = W;
  const cornerScore = new Float32Array(N);
  const ringScore = new Float32Array(N);

  for (let k = 0; k < W; k++) {
    let cs = 0;
    for (let i = 0; i < corners.length; i++) {
      cs += field.columns[(cornerAt[i] + k) % W] * corners[i].weight;
    }
    cornerScore[k] = cs / cornerTotal;

    let rs = 0;
    for (let i = 0; i < ring.length; i++) {
      rs += field.rows[ring[i].row * W + ((ringAt[i] + k) % W)];
    }
    ringScore[k] = rs / ring.length;
  }

  standardise(cornerScore);
  standardise(ringScore);
  const combined = new Float32Array(N);
  for (let i = 0; i < N; i++) combined[i] = cornerScore[i] + ringScore[i];

  let peak = 0;
  for (let i = 1; i < N; i++) if (combined[i] > combined[peak]) peak = i;

  // Everything that is not the peak or its own shoulder is a rival. A second
  // peak of similar height means the room is symmetric about the station and
  // the question has no answer.
  const guard = Math.round((GUARD / TAU) * W);
  const isRival = (i: number) => {
    const dk = Math.abs(i - peak);
    return Math.min(dk, W - dk) > guard;
  };

  let n = 0;
  let mean = 0;
  for (let i = 0; i < N; i++) {
    if (!isRival(i)) continue;
    mean += combined[i];
    n++;
  }
  if (!n) return null;
  mean /= n;

  let variance = 0;
  for (let i = 0; i < N; i++) {
    if (!isRival(i)) continue;
    variance += (combined[i] - mean) ** 2;
  }
  const sd = Math.sqrt(variance / n) || 1e-9;

  return {
    heading: (peak / W) * TAU,
    confidence: (combined[peak] - mean) / sd,
  };
}

/** Everything about a room that does not change between its panoramas. */
export function predictions(room: Room, st: Station) {
  return { corners: cornersFrom(room, st), ring: ringFrom(room, st) };
}

/* ---------------- putting the room together ---------------- */

/**
 * Solve every panorama in a room against every station it could have been shot
 * from, and let the scores do the pairing.
 *
 * Order would be the obvious way to pair them, and it is right in 24 of the 28
 * rooms in the reference survey -- but only 24, because an operator can shoot
 * two panoramas from one setup, or move the instrument without shooting at
 * all. Scoring every combination costs nothing once the picture has been read,
 * and it does not have to assume the operator was tidy.
 *
 * A panorama that matches nothing well enough comes back without a pose. It is
 * still a panorama; it just does not get to claim it knows where it is looking.
 */
export async function solveRoom(
  room: Room,
  urlFor: (index: number) => string,
): Promise<Pose[]> {
  if (!room.stations.length || !room.panoramas) return [];
  const predicted = room.stations.map((st) => predictions(room, st));

  const poses: Pose[] = [];
  for (let p = 0; p < room.panoramas; p++) {
    let field: Field;
    try {
      field = await readPanorama(urlFor(p));
    } catch {
      continue;                      // a shot we cannot read is not an error
    }
    let best: Pose | null = null;
    for (let s = 0; s < predicted.length; s++) {
      const hit = solveHeading(field, predicted[s].corners, predicted[s].ring);
      if (!hit) continue;
      if (!best || hit.confidence > best.confidence) {
        best = { station: s, panorama: p, ...hit };
      }
    }
    if (best && best.confidence >= MIN_CONFIDENCE) poses.push(best);
  }
  return poses;
}
