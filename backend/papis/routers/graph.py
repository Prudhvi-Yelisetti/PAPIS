# backend/papis/routers/graph.py
"""
Builds dependency graph data structures for the frontend visualiser.

Two modes:
  GET /api/graph/package/{name}   — ego-graph centred on one package
                                    (its deps + packages that depend on it)
  GET /api/graph/project/{id}     — full graph of all packages in a project
                                    and their inter-dependencies
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Package, Project

router = APIRouter()


# ── response models ───────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str                      # unique node id (package name)
    label: str
    version: str
    source: str
    install_type: str
    size_bytes: Optional[int]
    in_inbox: bool
    is_root: bool = False        # centre node for ego-graphs


class GraphEdge(BaseModel):
    source: str                  # package name (from)
    target: str                  # package name (to)
    label: str = "depends on"


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    root: Optional[str] = None   # id of the focal node, if any


# ── package ego-graph ─────────────────────────────────────────────────────────

@router.get("/package/{name}", response_model=GraphData)
def package_graph(
    name: str,
    depth: int = 2,
    db: Session = Depends(get_db),
):
    """
    Returns the ego-graph for a single package:
      - the package itself (root)
      - its direct + transitive dependencies up to `depth` hops
      - packages that directly depend on it (reverse edges)

    depth is capped at 4 to prevent runaway queries on large dep trees.
    """
    depth = min(depth, 4)
    root_pkg = db.query(Package).filter(Package.name.ilike(name)).first()
    if not root_pkg:
        raise HTTPException(404, f"Package '{name}' not found")

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    visited: set[str] = set()

    # Forward traversal — follow depends_on edges
    def traverse(pkg: Package, current_depth: int):
        if pkg.name in visited or current_depth > depth:
            return
        visited.add(pkg.name)
        nodes[pkg.name] = _pkg_to_node(pkg, is_root=(pkg.name == root_pkg.name))

        deps = json.loads(pkg.depends_on or "[]")
        for dep_name in deps:
            dep_name = dep_name.strip()
            if not dep_name:
                continue
            dep_pkg = db.query(Package).filter(Package.name.ilike(dep_name)).first()
            if dep_pkg:
                edges.append(GraphEdge(source=pkg.name, target=dep_pkg.name))
                traverse(dep_pkg, current_depth + 1)
            else:
                # Dep exists in metadata but not tracked — show as ghost node
                if dep_name not in nodes:
                    nodes[dep_name] = GraphNode(
                        id=dep_name, label=dep_name, version="?",
                        source="unknown", install_type="unknown",
                        size_bytes=None, in_inbox=False,
                    )
                edges.append(GraphEdge(source=pkg.name, target=dep_name))

    traverse(root_pkg, 0)

    # Reverse edges — who depends on root_pkg?
    required_by = json.loads(root_pkg.required_by or "[]")
    for rev_name in required_by:
        rev_name = rev_name.strip()
        if not rev_name:
            continue
        rev_pkg = db.query(Package).filter(Package.name.ilike(rev_name)).first()
        if rev_pkg and rev_pkg.name not in nodes:
            nodes[rev_pkg.name] = _pkg_to_node(rev_pkg)
        if rev_name not in nodes:
            nodes[rev_name] = GraphNode(
                id=rev_name, label=rev_name, version="?",
                source="unknown", install_type="unknown",
                size_bytes=None, in_inbox=False,
            )
        edges.append(GraphEdge(source=rev_name, target=root_pkg.name))

    return GraphData(nodes=list(nodes.values()), edges=edges, root=root_pkg.name)


# ── project graph ─────────────────────────────────────────────────────────────

@router.get("/project/{proj_id}", response_model=GraphData)
def project_graph(proj_id: int, db: Session = Depends(get_db)):
    """
    Returns the full dependency graph for all packages in a project.

    Edges are only drawn between packages that are also in the project
    (or are tracked in PAPIS) — untracked ghost deps are included as
    ghost nodes but marked with source="unknown".
    """
    proj = db.query(Project).get(proj_id)
    if not proj:
        raise HTTPException(404, "Project not found")

    project_pkg_names = {p.name.lower() for p in proj.packages}
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    visited: set[str] = set()

    for pkg in proj.packages:
        if pkg.name in visited:
            continue
        visited.add(pkg.name)
        nodes[pkg.name] = _pkg_to_node(pkg)

        deps = json.loads(pkg.depends_on or "[]")
        for dep_name in deps:
            dep_name = dep_name.strip()
            if not dep_name:
                continue

            # Only show edges to deps that are also in the project
            # OR are tracked elsewhere in PAPIS (to show cross-project deps)
            dep_pkg = db.query(Package).filter(Package.name.ilike(dep_name)).first()
            if dep_pkg:
                if dep_pkg.name not in nodes:
                    nodes[dep_pkg.name] = _pkg_to_node(dep_pkg)
                edges.append(GraphEdge(source=pkg.name, target=dep_pkg.name))
            elif dep_name.lower() in project_pkg_names:
                edges.append(GraphEdge(source=pkg.name, target=dep_name))

    return GraphData(nodes=list(nodes.values()), edges=edges)


# ── helpers ───────────────────────────────────────────────────────────────────

def _pkg_to_node(pkg: Package, is_root: bool = False) -> GraphNode:
    return GraphNode(
        id           = pkg.name,
        label        = pkg.name,
        version      = pkg.version,
        source       = pkg.source,
        install_type = pkg.install_type,
        size_bytes   = pkg.size_bytes,
        in_inbox     = pkg.in_inbox,
        is_root      = is_root,
    )