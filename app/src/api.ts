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
}

export interface Opening {
  index: number; kind: string; width: number; sill: number; head: number;
  left: [number, number]; right: [number, number];
}

export interface Room {
  name: string; flat: string; label: string; outlineSource: string;
  area: number; ceilingHeight: number | null; floorZ: number | null;
  outline: string[]; points: Point[]; openings: Opening[]; issues: Issue[];
  segments: [string, string][]; links: [string, string][];
  status: Status; builtAt: string | null; stepPath: string | null;
}

export interface Project {
  id: string; name: string; folder: string; rooms: number;
  openedAt: string; missing: boolean; thickness: number;
}

export interface FaceInfo {
  id: number; kind: string; area: number; role: string;
  normal: [number, number, number]; centroid: [number, number, number];
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
  };
}

export const api = {
  health: () => call<{ ok: boolean; version: string }>("/health"),
  projects: () => call<Project[]>("/projects"),
  createProject: (folder: string, name = "") =>
    call<{ id: string }>("/projects", {
      method: "POST", body: JSON.stringify({ folder, name }),
    }),
  deleteProject: (id: string) =>
    call<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
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
  exportStep: (id: string, name: string) =>
    call<{ path: string; bytes: number }>(
      `/projects/${id}/rooms/${encodeURIComponent(name)}/export`, { method: "POST" }),
  exportWall: (id: string, name: string, faceId: number) =>
    call<{ path: string; bytes: number; wall: number; length: number;
           pieces: number; stats: { faces: number; volume_m3: number } }>(
      `/projects/${id}/rooms/${encodeURIComponent(name)}/export-wall?faceId=${faceId}`,
      { method: "POST" }),
  exportDesignX: (id: string, name: string, fmt = "iges") =>
    call<{ path: string; bytes: number }>(
      `/projects/${id}/rooms/${encodeURIComponent(name)}/export-designx?fmt=${fmt}`,
      { method: "POST" }),
  settings: () => call<Record<string, unknown>>("/settings"),
  patchSettings: (body: Record<string, unknown>) =>
    call<Record<string, unknown>>("/settings", {
      method: "PATCH", body: JSON.stringify(body),
    }),
};
