const BASE = "http://127.0.0.1:8765";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${method} ${path} → ${res.status}: ${err}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const get  = <T>(path: string)              => req<T>("GET",    path);
const post = <T>(path: string, body: unknown) => req<T>("POST",   path, body);
const patch= <T>(path: string, body: unknown) => req<T>("PATCH",  path, body);
const del  = <T>(path: string)              => req<T>("DELETE", path);


// ── Types ─────────────────────────────────────────────────────────────────────

export interface Package {
  id: number;
  name: string;
  version: string;
  source: string;
  uv_mode: "tool" | "pip" | "add" | null;   // ← new
  install_type: string;
  install_date: string | null;
  size_bytes: number | null;
  description: string | null;
  is_orphan: boolean;
  in_inbox: boolean;
  project_ids: number[];
}

export interface Project {
  id: number;
  name: string;
  description: string | null;
  directory: string | null;
  is_archived: boolean;
  package_count: number;
}

export interface SystemSummary {
  total_packages: number;
  inbox_count: number;
  orphan_count: number;
  project_count: number;
  total_size_bytes: number;
  sources: Record<string, number>;
}

export interface StorageBreakdown {
  source: string;
  package_count: number;
  total_bytes: number;
}

export interface TimelineEvent {
  event_id: number;
  event_type: string;
  package: string;
  version_old: string | null;
  version_new: string | null;
  triggered_by: string | null;
  occurred_at: string;
}

export interface ScanResult {
  path: string;
  manifest: string | null;
  detected_count: number;
  matched_package_ids: number[];
  unmatched_deps: string[];
  auto_assigned: boolean;
}


// ── Package API ───────────────────────────────────────────────────────────────

export const packagesApi = {
  list: (params?: { inbox_only?: boolean; source?: string; search?: string }) => {
    const qs = new URLSearchParams();
    if (params?.inbox_only) qs.set("inbox_only", "true");
    if (params?.source)     qs.set("source", params.source);
    if (params?.search)     qs.set("search", params.search);
    const q = qs.toString();
    return get<Package[]>(`/api/packages/${q ? "?" + q : ""}`);
  },
  get:   (id: number)              => get<Package>(`/api/packages/${id}`),
  sync:  ()                        => post<{ added: number; updated: number; total: number }>("/api/packages/sync", {}),
  event: (payload: object)         => post<void>("/api/packages/event", payload),
};


// ── Project API ───────────────────────────────────────────────────────────────

export interface ProjectCreate {
  name: string;
  description?: string;
  directory?: string;
  tags?: string[];
}

export const projectsApi = {
  list:           ()                               => get<Project[]>("/api/projects/"),
  create:         (body: ProjectCreate)            => post<Project>("/api/projects/", body),
  update:         (id: number, body: ProjectCreate)=> patch<Project>(`/api/projects/${id}`, body),
  delete:         (id: number, removeOrphans=false)=> del<void>(`/api/projects/${id}?remove_orphaned_packages=${removeOrphans}`),
  packages:       (id: number)                     => get<Package[]>(`/api/projects/${id}/packages`),
  assignPackage:  (projId: number, pkgId: number)  => post<void>(`/api/projects/${projId}/packages/${pkgId}`, {}),
  unassignPackage:(projId: number, pkgId: number)  => del<void>(`/api/projects/${projId}/packages/${pkgId}`),
};


// ── Analytics API ─────────────────────────────────────────────────────────────

export const analyticsApi = {
  summary:        ()                => get<SystemSummary>("/api/analytics/summary"),
  orphans:        ()                => get<Package[]>("/api/analytics/orphans"),
  storage:        ()                => get<StorageBreakdown[]>("/api/analytics/storage"),
  storageByProject: ()              => get<any[]>("/api/analytics/storage/by-project"),
  bloat:          (minSizeMb = 50)  => get<any[]>(`/api/analytics/bloat?min_size_mb=${minSizeMb}`),
  timeline:       (limit = 50)      => get<TimelineEvent[]>(`/api/analytics/timeline?limit=${limit}`),
  missingDeps:    ()                => get<any[]>("/api/analytics/missing-deps"),
};


// ── Exports API ───────────────────────────────────────────────────────────────

export const exportsApi = {
  requirements: (projId: number) => fetch(`${BASE}/api/exports/${projId}/requirements.txt`).then(r => r.text()),
  pacmanList:   (projId: number) => fetch(`${BASE}/api/exports/${projId}/pacman-list`).then(r => r.text()),
  reinstallSh:  (projId: number) => fetch(`${BASE}/api/exports/${projId}/reinstall.sh`).then(r => r.text()),
  snapshot:     (projId: number) => get<any>(`/api/exports/${projId}/snapshot`),
  dockerfile:   (projId: number) => fetch(`${BASE}/api/exports/${projId}/dockerfile`).then(r => r.text()),
};


// ── Duplicate check API ───────────────────────────────────────────────────────

export interface ProjectRef {
  id: number;
  name: string;
  directory: string | null;
}

export interface CheckResult {
  found: boolean;
  package_id: number | null;
  name: string;
  version: string | null;
  source: string | null;
  install_type: string | null;
  in_inbox: boolean;
  projects: ProjectRef[];
  suggestion: string;
}

export interface BatchCheckResult {
  results: CheckResult[];
  duplicate_count: number;
  new_count: number;
}

export const duplicatesApi = {
  check: (name: string, source?: string) => {
    const qs = new URLSearchParams({ name });
    if (source) qs.set("source", source);
    return get<CheckResult>(`/api/packages/check?${qs}`);
  },
  checkMany: (items: { name: string; source?: string }[]) =>
    post<BatchCheckResult>("/api/packages/check-many", items),
  logDuplicate: (body: {
    name: string;
    source: string;
    attempted_version?: string;
    resolved_action: string;
    target_project_id?: number;
  }) => post<void>("/api/packages/duplicate", body),
};


// ── Scan API ──────────────────────────────────────────────────────────────────

export interface BulkScanLink {
  project_id: number;
  project_name: string;
  package_id: number;
  package_name: string;
  manifest_type: string;
}

export interface BulkScanResult {
  projects_scanned: number;
  manifests_found: number;
  new_links_count: number;
  new_links: BulkScanLink[];
  already_linked_count: number;
  unmatched_deps: Record<string, string[]>;
}

export const scanApi = {
  scan: (directory: string, project_id?: number, auto_assign = false) =>
    post<ScanResult>("/api/scan/", { directory, project_id, auto_assign }),
  scanAll: () => post<BulkScanResult>("/api/scan/bulk", {}),
};


// ── Helpers ───────────────────────────────────────────────────────────────────

export function fmtBytes(bytes: number | null): string {
  if (!bytes) return "–";
  if (bytes < 1024)        return `${bytes} B`;
  if (bytes < 1024 ** 2)   return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3)   return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function sourceColor(source: string): string {
  const map: Record<string, string> = {
    pacman : "#1793D1",
    aur    : "#6B8DE3",
    pip    : "#3776AB",
    npm    : "#CB3837",
    cargo  : "#CE422B",
    flatpak: "#4A86CF",
    uv     : "#DE5F32",
    docker : "#2496ED",
    podman : "#892CA0",   // ← Podman purple
    conda  : "#44A833",
  };
  return map[source] ?? "#888";
}

/** Returns a human-readable label for a package's source + uv_mode combo. */
export function sourceLabel(pkg: Package): string {
  if (pkg.source === "uv") {
    const labels: Record<string, string> = {
      tool: "uv tool",
      pip : "uv pip",
      add : "uv add",
    };
    return labels[pkg.uv_mode ?? ""] ?? "uv";
  }
  if (pkg.source === "cargo") {
    // Distinguish global tool vs project dep from the description prefix
    if (pkg.description?.includes("global tool")) return "cargo (global)";
    if (pkg.description?.includes("project:"))    return "cargo (project)";
    return "cargo";
  }
  if (pkg.source === "docker" || pkg.source === "podman") {
    if (pkg.install_type === "dependency") return `${pkg.source} (container)`;
    return `${pkg.source} (image)`;
  }
  return pkg.source;
}