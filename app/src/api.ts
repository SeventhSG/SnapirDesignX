/** Thin client for the local geometry backend. */

const BASE = (window as any).snapir?.api ?? "http://127.0.0.1:8765";

export type Status = "ready" | "needs-you" | "built";

export interface Issue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  points: string[];
}

export interface Point {
  name: string; x: number; y: number; z: number; role: string; layer: string;
  /** Constructed by the operator, not measured by the instrument. */
  derived?: boolean;
  source?: string;
}

/** Where two drawn lines cross: a corner the operator can adopt. */
export interface Crossing {
  at: [number, number];
  lines: [[string, string], [string, string]];
}

/** One addressable piece of the built body, named after the points it came
 *  from. Unlike a face id, this survives a rebuild. */
export interface Element {
  kind: string; key: string; label: string;
  index: number | null; points: string[];
}

/** Where the instrument stood. One setup per panorama, so this is also
 *  where a panorama was shot from. */
export interface Station {
  name: string; x: number; y: number; z: number;
}

export interface Opening {
  index: number; kind: string; width: number; sill: number; head: number;
  left: [number, number]; right: [number, number];
  /** Stable name for this rectangle, so a choice about it survives a rebuild. */
  key: string;
  /** True when it is a hole. False when it is something mounted on the wall. */
  cuts: boolean;
}

/** What a rectangle on a wall is allowed to be. */
export interface OpeningKind {
  kind: string; label: string;
}

export interface Room {
  name: string; flat: string; label: string; outlineSource: string;
  panoramas: number; stations: Station[];
  area: number; ceilingHeight: number | null; floorZ: number | null;
  outline: string[]; points: Point[]; openings: Opening[]; issues: Issue[];
  openingKinds: OpeningKind[];
  segments: [string, string][]; links: [string, string][];
  crossings: Crossing[]; elements: Element[];
  /** Set when this room overrides the job's wall thickness. */
  wallThickness: number | null;
  status: Status; builtAt: string | null; stepPath: string | null;
}

export interface Project {
  id: string; name: string; folder: string; rooms: number;
  openedAt: string; missing: boolean; thickness: number;
}

/** One door hooked to another, so a walkthrough can cross between rooms.
 *  Each room keeps its own independent survey coordinates; dx/dy/rotationDeg
 *  place room B's origin in room A's local frame. */
export interface Connection {
  id: string; roomA: string; openingA: number; roomB: string; openingB: number;
  dx: number; dy: number; rotationDeg: number; enabled: boolean;
}

export interface FaceInfo {
  id: number; kind: string; area: number; role: string;
  normal: [number, number, number]; centroid: [number, number, number];
  /** Which element of the room this face belongs to. `id` is only good for
   *  one build; `element` outlives a rebuild. */
  element?: string;
  elementKind?: string;
  label?: string;
}

export interface Mesh {
  positions: number[]; normals: number[]; faceIds: number[];
  faces: FaceInfo[]; triangleCount: number;
}

export interface BuildResult {
  mesh: Mesh;
  stats: { solids: number; shells: number; faces: number; volume_m3: number };
  planes: {
    floorTilt: number; floorRms: number;
    ceilingTilt: number; ceilingRms: number; height: number;
  };
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep status */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/** Fill in anything an older backend did not send, so the UI never sees
 *  undefined where it expects a list. */
function fill(r: Room): Room {
  return {
    ...r,
    points: r.points ?? [],
    outline: r.outline ?? [],
    openings: r.openings ?? [],
    issues: r.issues ?? [],
    segments: r.segments ?? [],
    links: r.links ?? [],
    panoramas: r.panoramas ?? 0,
    stations: r.stations ?? [],
  };
}

/** Where a room's panorama lives. Straight into an <img src>, so the
 *  service streams it rather than the page holding it in memory twice. */
export const panoramaUrl = (id: string, name: string, index = 0) =>
  `${BASE}/projects/${id}/rooms/${encodeURIComponent(name)}/panorama/${index}`;

export const api = {
  health: () => call<{ ok: boolean; version: string }>("/health"),
  projects: () => call<Project[]>("/projects"),
  createProject: (folder: string, name = "") =>
    call<{ id: string }>("/projects", {
      method: "POST", body: JSON.stringify({ folder, name }),
    }),
  deleteProject: (id: string) =>
    call<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
  exportSdxp: (id: string) =>
    call<{ path: string; bytes: number }>(`/projects/${id}/export-sdxp`,
      { method: "POST" }),
  importSdxp: (path: string) =>
    call<{ id: string; name: string; folder: string }>("/projects/import-sdxp", {
      method: "POST", body: JSON.stringify({ path }),
    }),
  rooms: async (id: string) => {
    const d = await call<{ id: string; name: string; folder: string;
                          thickness: number; rooms: Room[] }>(`/projects/${id}/rooms`);
    return { ...d, rooms: d.rooms.map(fill) };
  },
  room: async (id: string, name: string) =>
    fill(await call<Room>(`/projects/${id}/rooms/${encodeURIComponent(name)}`)),
  patchRoom: async (id: string, name: string, body: Record<string, unknown>) =>
    fill(await call<Room>(`/projects/${id}/rooms/${encodeURIComponent(name)}`, {
      method: "PATCH", body: JSON.stringify(body),
    })),
  patchProject: (id: string, body: Record<string, unknown>) =>
    call<{ id: string; thickness: number }>(`/projects/${id}`, {
      method: "PATCH", body: JSON.stringify(body),
    }),
  build: (id: string, name: string) =>
    call<BuildResult>(`/projects/${id}/rooms/${encodeURIComponent(name)}/build`,
      { method: "POST" }),
  exportStep: (id: string, name: string, fmt = "step", schema = "AP214") =>
    call<{ path: string; bytes: number; format: string }>(
      `/projects/${id}/rooms/${encodeURIComponent(name)}/export` +
      `?fmt=${fmt}&schema=${schema}`, { method: "POST" }),
  exportWall: (id: string, name: string, faceId: number, fmt = "step",
               schema = "AP214") =>
    call<{ path: string; bytes: number; format: string; wall: number;
           length: number; pieces: number;
           stats: { faces: number; volume_m3: number } }>(
      `/projects/${id}/rooms/${encodeURIComponent(name)}/export-wall` +
      `?faceId=${faceId}&fmt=${fmt}&schema=${schema}`,
      { method: "POST" }),
  exportDesignX: (id: string, name: string, fmt = "iges") =>
    call<{ path: string; bytes: number; format: string }>(
      `/projects/${id}/rooms/${encodeURIComponent(name)}/export-designx?fmt=${fmt}`,
      { method: "POST" }),
  connections: (id: string) =>
    call<{ connections: Connection[] }>(`/projects/${id}/connections`),
  createConnection: (id: string, body: {
    roomA: string; openingA: number; roomB: string; openingB: number;
    dx: number; dy: number; rotationDeg: number;
  }) => call<Connection>(`/projects/${id}/connections`, {
    method: "POST", body: JSON.stringify(body),
  }),
  patchConnection: (id: string, cid: string, body: Record<string, unknown>) =>
    call<Connection>(`/projects/${id}/connections/${cid}`, {
      method: "PATCH", body: JSON.stringify(body),
    }),
  deleteConnection: (id: string, cid: string) =>
    call<{ ok: boolean }>(`/projects/${id}/connections/${cid}`, { method: "DELETE" }),
  settings: () => call<Record<string, unknown>>("/settings"),
  patchSettings: (body: Record<string, unknown>) =>
    call<Record<string, unknown>>("/settings", {
      method: "PATCH", body: JSON.stringify(body),
    }),
};
