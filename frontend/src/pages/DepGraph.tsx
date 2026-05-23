/**
 * Interactive dependency graph.
 *
 * Uses a pure-CSS/SVG force-directed layout implemented from scratch
 * (no external graph library needed) — keeps the bundle small and
 * avoids Tauri compatibility issues with WebGL-heavy libraries.
 *
 * Features:
 *   - Search by package name or browse by project
 *   - Drag nodes to rearrange
 *   - Zoom + pan via SVG viewBox manipulation
 *   - Click a node to see its metadata in a side panel
 *   - Colour-coded by source (matches source-pill colours)
 *   - Size of node circle proportional to package size on disk
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { projectsApi, sourceColor, fmtBytes, type Project } from "../api";

const API = "http://127.0.0.1:8765";

// ── types ─────────────────────────────────────────────────────────────────────

interface GNode {
  id: string; label: string; version: string;
  source: string; install_type: string;
  size_bytes: number | null; in_inbox: boolean; is_root: boolean;
  // layout state
  x: number; y: number; vx: number; vy: number;
}

interface GEdge { source: string; target: string; label: string; }
interface GraphData { nodes: GNode[]; edges: GEdge[]; root: string | null; }


// ── force simulation (simple Euler integration) ───────────────────────────────

const REPULSION  = 4000;
const ATTRACTION = 0.04;
const DAMPING    = 0.85;
const CENTRE_K   = 0.015;

function tick(nodes: GNode[], edges: GEdge[], cx: number, cy: number) {
  const idx = Object.fromEntries(nodes.map(n => [n.id, n]));

  // Repulsion between all node pairs
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const dx = b.x - a.x || 0.1;
      const dy = b.y - a.y || 0.1;
      const dist2 = dx * dx + dy * dy;
      const force = REPULSION / dist2;
      const fx = (dx / Math.sqrt(dist2)) * force;
      const fy = (dy / Math.sqrt(dist2)) * force;
      a.vx -= fx; a.vy -= fy;
      b.vx += fx; b.vy += fy;
    }
  }

  // Spring attraction along edges
  for (const edge of edges) {
    const a = idx[edge.source], b = idx[edge.target];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    a.vx += dx * ATTRACTION; a.vy += dy * ATTRACTION;
    b.vx -= dx * ATTRACTION; b.vy -= dy * ATTRACTION;
  }

  // Gravity toward centre
  for (const n of nodes) {
    n.vx += (cx - n.x) * CENTRE_K;
    n.vy += (cy - n.y) * CENTRE_K;
    n.vx *= DAMPING; n.vy *= DAMPING;
    n.x  += n.vx;   n.y  += n.vy;
  }
}


// ── component ─────────────────────────────────────────────────────────────────

export default function DepGraph() {
  const [projects, setProjects]       = useState<Project[]>([]);
  const [search, setSearch]           = useState("");
  const [mode, setMode]               = useState<"package" | "project">("package");
  const [selProject, setSelProject]   = useState<number | null>(null);
  const [graph, setGraph]             = useState<GraphData | null>(null);
  const [nodes, setNodes]             = useState<GNode[]>([]);
  const [loading, setLoading]         = useState(false);
  const [selected, setSelected]       = useState<GNode | null>(null);
  const [dragging, setDragging]       = useState<string | null>(null);
  const [viewBox, setViewBox]         = useState({ x: 0, y: 0, w: 800, h: 560 });
  const [panning, setPanning]         = useState(false);
  const panStart                      = useRef({ x: 0, y: 0, vbx: 0, vby: 0 });
  const simRef                        = useRef<number | null>(null);
  const svgRef                        = useRef<SVGSVGElement>(null);

  useEffect(() => { projectsApi.list().then(setProjects); }, []);

  // ── load graph data ─────────────────────────────────────────────────────────
  const loadGraph = useCallback(async () => {
    if (mode === "package" && !search.trim()) return;
    if (mode === "project" && !selProject) return;
    setLoading(true);
    setSelected(null);
    try {
      const url = mode === "package"
        ? `${API}/api/graph/package/${encodeURIComponent(search.trim())}?depth=2`
        : `${API}/api/graph/project/${selProject}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const data: GraphData = await res.json();
      setGraph(data);

      // Seed node positions randomly around centre
      const cx = viewBox.w / 2, cy = viewBox.h / 2;
      const seeded: GNode[] = data.nodes.map(n => ({
        ...n,
        x : cx + (Math.random() - 0.5) * 300,
        y : cy + (Math.random() - 0.5) * 300,
        vx: 0, vy: 0,
      }));
      setNodes(seeded);

      // Start simulation
      if (simRef.current) cancelAnimationFrame(simRef.current);
      let iter = 0;
      const simulate = () => {
        if (iter++ < 300) {
          setNodes(prev => {
            const next = prev.map(n => ({ ...n }));
            tick(next, data.edges, cx, cy);
            return next;
          });
          simRef.current = requestAnimationFrame(simulate);
        }
      };
      simulate();
    } catch (e: any) {
      alert(`Graph error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [mode, search, selProject, viewBox.w, viewBox.h]);

  useEffect(() => () => { if (simRef.current) cancelAnimationFrame(simRef.current); }, []);

  // ── drag a node ─────────────────────────────────────────────────────────────
  const onNodeMouseDown = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setDragging(id);
    setSelected(nodes.find(n => n.id === id) ?? null);
  };

  const onSvgMouseMove = (e: React.MouseEvent) => {
    if (dragging) {
      const svg = svgRef.current!;
      const rect = svg.getBoundingClientRect();
      const scaleX = viewBox.w / rect.width;
      const scaleY = viewBox.h / rect.height;
      const x = viewBox.x + (e.clientX - rect.left) * scaleX;
      const y = viewBox.y + (e.clientY - rect.top)  * scaleY;
      setNodes(prev => prev.map(n => n.id === dragging ? { ...n, x, y, vx: 0, vy: 0 } : n));
    } else if (panning) {
      const dx = (e.clientX - panStart.current.x) * (viewBox.w / svgRef.current!.getBoundingClientRect().width);
      const dy = (e.clientY - panStart.current.y) * (viewBox.h / svgRef.current!.getBoundingClientRect().height);
      setViewBox(vb => ({ ...vb, x: panStart.current.vbx - dx, y: panStart.current.vby - dy }));
    }
  };

  const onSvgMouseDown = (e: React.MouseEvent) => {
    setPanning(true);
    panStart.current = { x: e.clientX, y: e.clientY, vbx: viewBox.x, vby: viewBox.y };
  };

  const onMouseUp = () => { setDragging(null); setPanning(false); };

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.1 : 0.9;
    setViewBox(vb => ({
      x: vb.x + vb.w * (1 - factor) / 2,
      y: vb.y + vb.h * (1 - factor) / 2,
      w: vb.w * factor,
      h: vb.h * factor,
    }));
  };

  // ── node radius: base 14, +log(size) bonus ──────────────────────────────────
  const nodeRadius = (n: GNode) =>
    14 + (n.size_bytes ? Math.min(12, Math.log10(n.size_bytes + 1) * 2) : 0);

  const nodeIdx = Object.fromEntries(nodes.map(n => [n.id, n]));

  return (
    <div className="graph-page">
      {/* ── controls ─────────────────────────────────────────────────────── */}
      <div className="graph-controls card">
        <div className="tab-bar" style={{ borderBottom: "none", marginBottom: 10 }}>
          <button className={`tab ${mode === "package" ? "tab--active" : ""}`}
            onClick={() => setMode("package")}>By package</button>
          <button className={`tab ${mode === "project" ? "tab--active" : ""}`}
            onClick={() => setMode("project")}>By project</button>
        </div>

        {mode === "package" ? (
          <div style={{ display: "flex", gap: 8 }}>
            <input className="input" style={{ flex: 1 }}
              placeholder="Package name (e.g. requests, ruff)"
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => e.key === "Enter" && loadGraph()}
            />
            <button className="btn btn-primary" onClick={loadGraph} disabled={loading || !search.trim()}>
              {loading ? "Loading…" : "Show graph"}
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <select className="input" style={{ flex: 1 }}
              value={selProject ?? ""}
              onChange={e => setSelProject(Number(e.target.value) || null)}
            >
              <option value="">Select a project…</option>
              {projects.map(p => (
                <option key={p.id} value={p.id}>{p.name} ({p.package_count} pkgs)</option>
              ))}
            </select>
            <button className="btn btn-primary" onClick={loadGraph} disabled={loading || !selProject}>
              {loading ? "Loading…" : "Show graph"}
            </button>
          </div>
        )}

        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          Scroll to zoom · Drag nodes to rearrange · Drag background to pan
        </p>
      </div>

      <div className="graph-body">
        {/* ── SVG canvas ───────────────────────────────────────────────────── */}
        <svg
          ref={svgRef}
          className="graph-svg"
          viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
          onMouseMove={onSvgMouseMove}
          onMouseDown={onSvgMouseDown}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
          onWheel={onWheel}
          style={{ cursor: panning ? "grabbing" : "grab" }}
        >
          <defs>
            <marker id="arrow" viewBox="0 0 10 6" refX="10" refY="3"
              markerWidth="8" markerHeight="6" orient="auto">
              <path d="M0,0 L10,3 L0,6 Z" fill="rgba(255,255,255,0.2)" />
            </marker>
          </defs>

          {/* Edges */}
          {graph?.edges.map((edge, i) => {
            const a = nodeIdx[edge.source], b = nodeIdx[edge.target];
            if (!a || !b) return null;
            const rB = nodeRadius(b);
            const dx = b.x - a.x, dy = b.y - a.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const tx = b.x - (dx / dist) * rB;
            const ty = b.y - (dy / dist) * rB;
            return (
              <line key={i}
                x1={a.x} y1={a.y} x2={tx} y2={ty}
                stroke="rgba(255,255,255,0.12)"
                strokeWidth={1.5}
                markerEnd="url(#arrow)"
              />
            );
          })}

          {/* Nodes */}
          {nodes.map(n => {
            const r    = nodeRadius(n);
            const fill = sourceColor(n.source);
            const isSelected = selected?.id === n.id;
            return (
              <g key={n.id}
                transform={`translate(${n.x},${n.y})`}
                onMouseDown={e => onNodeMouseDown(e, n.id)}
                style={{ cursor: "pointer" }}
              >
                {/* Glow ring for root or selected */}
                {(n.is_root || isSelected) && (
                  <circle r={r + 6} fill="none"
                    stroke={isSelected ? "white" : fill}
                    strokeWidth={isSelected ? 2 : 1.5}
                    strokeOpacity={0.5}
                  />
                )}
                <circle r={r}
                  fill={fill}
                  fillOpacity={n.source === "unknown" ? 0.3 : 0.85}
                  stroke={isSelected ? "white" : "rgba(0,0,0,0.4)"}
                  strokeWidth={isSelected ? 2 : 1}
                />
                {/* Ghost node indicator */}
                {n.source === "unknown" && (
                  <text textAnchor="middle" dominantBaseline="middle"
                    fontSize={r * 0.9} fill="rgba(255,255,255,0.5)">?</text>
                )}
                {/* Label below node */}
                <text y={r + 13} textAnchor="middle"
                  fontSize={11} fill="rgba(255,255,255,0.8)"
                  style={{ pointerEvents: "none", userSelect: "none" }}
                >
                  {n.label.length > 18 ? n.label.slice(0, 16) + "…" : n.label}
                </text>
              </g>
            );
          })}
        </svg>

        {/* ── side panel ───────────────────────────────────────────────────── */}
        {selected && (
          <aside className="graph-detail card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <h2 style={{ margin: 0 }}>{selected.label}</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>×</button>
            </div>

            <div className="graph-detail__row">
              <span className="muted">Version</span>
              <span className="mono">{selected.version}</span>
            </div>
            <div className="graph-detail__row">
              <span className="muted">Source</span>
              <span className="source-pill" style={{ background: sourceColor(selected.source) }}>
                {selected.source}
              </span>
            </div>
            <div className="graph-detail__row">
              <span className="muted">Type</span>
              <span>{selected.install_type}</span>
            </div>
            <div className="graph-detail__row">
              <span className="muted">Size</span>
              <span>{fmtBytes(selected.size_bytes)}</span>
            </div>
            <div className="graph-detail__row">
              <span className="muted">Inbox</span>
              <span>{selected.in_inbox ? "Yes — unassigned" : "Assigned"}</span>
            </div>

            {/* Show direct deps and required-by from graph data */}
            {graph && (() => {
              const deps    = graph.edges.filter(e => e.source === selected.id).map(e => e.target);
              const reqBy   = graph.edges.filter(e => e.target === selected.id).map(e => e.source);
              return (
                <>
                  {deps.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <p className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                        Depends on ({deps.length}):
                      </p>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {deps.slice(0, 12).map(d => (
                          <button key={d} className="btn btn-ghost btn-sm mono"
                            style={{ fontSize: 11 }}
                            onClick={() => {
                              const n = nodes.find(n => n.id === d);
                              if (n) setSelected(n);
                            }}>{d}</button>
                        ))}
                        {deps.length > 12 && <span className="muted" style={{ fontSize: 11 }}>+{deps.length - 12} more</span>}
                      </div>
                    </div>
                  )}
                  {reqBy.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <p className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                        Required by ({reqBy.length}):
                      </p>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {reqBy.slice(0, 12).map(d => (
                          <button key={d} className="btn btn-ghost btn-sm mono"
                            style={{ fontSize: 11 }}
                            onClick={() => {
                              const n = nodes.find(n => n.id === d);
                              if (n) setSelected(n);
                            }}>{d}</button>
                        ))}
                        {reqBy.length > 12 && <span className="muted" style={{ fontSize: 11 }}>+{reqBy.length - 12} more</span>}
                      </div>
                    </div>
                  )}
                </>
              );
            })()}
          </aside>
        )}
      </div>

      {/* Empty state */}
      {!graph && !loading && (
        <div className="graph-empty">
          <p>Search for a package or select a project to visualise its dependency graph.</p>
        </div>
      )}
    </div>
  );
}