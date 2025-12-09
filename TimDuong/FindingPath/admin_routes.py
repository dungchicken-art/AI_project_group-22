from __future__ import annotations

import os
from functools import wraps
from typing import Any, Callable, Dict, List, Tuple

import networkx as nx
from flask import Blueprint, jsonify, render_template, request, session

from pathfinding import PathfindingDemo
from thuattoan import NodePath

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Dungdz0201")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "02012005")
ADMIN_SESSION_KEY = "is_admin_authenticated"
ADMIN_EDGE_PENALTIES: Dict[Tuple[str, str], Dict[str, Any]] = {}
ADMIN_FORBIDDEN_EDGES: set[Tuple[str, str]] = set()


def apply_admin_penalties(demo: PathfindingDemo) -> None:
    """Apply all admin configured node penalties to the provided demo instance."""

    for (u, v) in ADMIN_FORBIDDEN_EDGES:
        try:
            demo.block_edges_between(u, v)
        except Exception:
            continue

    if not ADMIN_EDGE_PENALTIES:
        return

    for (u, v), config in ADMIN_EDGE_PENALTIES.items():
        raw_multiplier = config.get("multiplier", 1.0)
        if not isinstance(raw_multiplier, (int, float, str)):
            continue
        try:
            multiplier = float(raw_multiplier)
        except (TypeError, ValueError):
            continue
        if multiplier <= 0:
            continue
        path_nodes = config.get("path")
        if isinstance(path_nodes, (list, tuple)) and len(path_nodes) >= 2:
            try:
                demo.penalize_node_path(path_nodes, multiplier=multiplier)
                continue
            except Exception:
                pass
        demo.penalize_edges_between(u, v, multiplier=multiplier)


def _serialize_admin_penalties() -> List[dict[str, object]]:
    return [
        {
            "id": f"{u}--{v}",
            "from": u,
            "to": v,
            "multiplier": float(config.get("multiplier", 1.0) or 1.0),
            "kind": str(config.get("kind", "flood")),
            "path_nodes": config.get("path") or [],
            "length_m": float(config.get("length_m", 0.0) or 0.0),
        }
        for (u, v), config in ADMIN_EDGE_PENALTIES.items()
    ]

def _serialize_forbidden_edges() -> List[dict[str, object]]:
    return [
        {
            "id": f"{u}--{v}",
            "from": u,
            "to": v,
            "kind": "forbidden",
        }
        for (u, v) in ADMIN_FORBIDDEN_EDGES
    ]

def init_admin(
    app,
    *,
    load_base_graph: Callable[[], nx.MultiDiGraph],
    load_focus_demo: Callable[[str], PathfindingDemo],
    default_network_type: str,
) -> None:
    """Register admin pages and APIs on the provided Flask app."""

    blueprint = Blueprint("admin_routes", __name__)

    def _is_admin_authenticated() -> bool:
        return session.get(ADMIN_SESSION_KEY) is True

    def _edge_key(raw_u: Any, raw_v: Any) -> Tuple[str, str]:
        u = str(raw_u).strip()
        v = str(raw_v).strip()
        if not u or not v:
            raise ValueError("Cạnh không hợp lệ.")
        # store undirected to avoid duplicates, but apply both directions
        return (u, v) if u <= v else (v, u)

    def _ensure_edge_exists(u: str, v: str) -> None:
        graph = load_base_graph()
        if not (graph.has_node(u) and graph.has_node(v)):
            raise ValueError(f"Không tìm thấy node {u} hoặc {v} trong khu vực Khương Đình.")
        if not (graph.has_edge(u, v) or graph.has_edge(v, u)):
            raise ValueError("Hai node không kề nhau trong khu vực Khương Đình.")

    def _ensure_nodes_exist(u: str, v: str) -> None:
        graph = load_base_graph()
        if not (graph.has_node(u) and graph.has_node(v)):
            raise ValueError(f"Khong tim thay node {u} hoac {v} trong khu vuc Khuong Dinh.")

    def _compute_shortest_path(u: str, v: str) -> Tuple[NodePath, List[Tuple[float, float]], float]:
        """Return node path, coordinates and length along the shortest route."""

        demo = load_focus_demo(default_network_type)
        apply_admin_penalties(demo)
        node_path = demo.shortest_path_nodes(u, v, weight="length")
        coords = demo.path_coordinates(node_path)
        length_m = demo.path_length(node_path)
        return node_path, coords, length_m

    def require_admin(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _is_admin_authenticated():
                return jsonify({"error": "Bạn cần đăng nhập admin trước khi thực hiện tác vụ này."}), 401
            return func(*args, **kwargs)

        return wrapper

    @blueprint.route("/admin")
    def admin_page() -> str:
        return render_template("admin.html")

    @blueprint.get("/api/admin/status")
    def api_admin_status():
        return jsonify(
            {
                "authenticated": _is_admin_authenticated(),
                "penalties": _serialize_admin_penalties() if _is_admin_authenticated() else [],
            }
        )

    @blueprint.post("/api/admin/login")
    def api_admin_login():
        payload = request.get_json(force=True, silent=True) or {}
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", "")).strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session[ADMIN_SESSION_KEY] = True
            return jsonify({"authenticated": True})

        session.pop(ADMIN_SESSION_KEY, None)
        return jsonify({"error": "Sai tài khoản hoặc mật khẩu, hãy thử lại"}), 401

    @blueprint.post("/api/admin/logout")
    def api_admin_logout():
        session.pop(ADMIN_SESSION_KEY, None)
        return jsonify({"authenticated": False})

    @blueprint.get("/api/admin/load")
    @require_admin
    def api_admin_load():
        network_type = default_network_type

        try:
            demo = load_focus_demo(network_type)
            apply_admin_penalties(demo)
        except Exception as exc:  # pragma: no cover - surface error to client
            return jsonify({"error": str(exc)}), 400

        (south, west), (north, east) = demo.bounds()
        centroid = demo.centroid()

        return jsonify(
            {
                "edges": demo.edge_features(),
                "nodes": demo.node_features(),
                "bounds": [[south, west], [north, east]],
                "centroid": [centroid[0], centroid[1]],
                "graph_stats": demo.graph_statistics(),
                "penalties": _serialize_admin_penalties(),
                "penalized_edges": demo.penalized_edge_features(),
                "forbidden_edges": list(ADMIN_FORBIDDEN_EDGES),
            }
        )

    @blueprint.get("/api/admin/penalties")
    @require_admin
    def api_admin_penalties():
        return jsonify({"penalties": _serialize_admin_penalties()})

    @blueprint.get("/api/admin/forbidden")
    @require_admin
    def api_admin_forbidden():
        return jsonify({"forbidden": _serialize_forbidden_edges()})

    @blueprint.get("/api/admin/preview")
    @require_admin
    def api_admin_preview():
        raw_from = request.args.get("from") or request.args.get("fromNode") or request.args.get("u") or ""
        raw_to = request.args.get("to") or request.args.get("toNode") or request.args.get("v") or ""

        try:
            edge_key = _edge_key(raw_from, raw_to)
            _ensure_nodes_exist(*edge_key)
            node_path, path_coords, length_m = _compute_shortest_path(*edge_key)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # pragma: no cover - surface error to client
            return jsonify({"error": str(exc)}), 400

        return jsonify(
            {
                "path_nodes": node_path,
                "path_coords": path_coords,
                "length_m": length_m,
            }
        )

    @blueprint.post("/api/admin/penalties")
    @require_admin
    def api_admin_set_penalty():
        payload = request.get_json(force=True, silent=True) or {}
        raw_from = payload.get("from") or payload.get("fromNode") or payload.get("u") or ""
        raw_to = payload.get("to") or payload.get("toNode") or payload.get("v") or ""
        raw_multiplier = payload.get("multiplier")
        kind = str(payload.get("kind", "flood")).strip() or "flood"

        if raw_multiplier is None:
            return jsonify({"error": "He so phai la mot so"}), 400

        try:
            multiplier = float(raw_multiplier)
        except (TypeError, ValueError):
            return jsonify({"error": "He so phai la mot so"}), 400

        if multiplier <= 0:
            return jsonify({"error": "He so phai lon hon 0"}), 400
        if multiplier > 20:
            return jsonify({"error": "He so khong nen vuot qua 20"}), 400

        try:
            edge_key = _edge_key(raw_from, raw_to)
            _ensure_nodes_exist(*edge_key)
            node_path, path_coords, length_m = _compute_shortest_path(*edge_key)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        ADMIN_EDGE_PENALTIES[edge_key] = {
            "multiplier": multiplier,
            "kind": kind,
            "path": node_path,
            "length_m": length_m,
        }
        return jsonify({"penalties": _serialize_admin_penalties(), "path_coords": path_coords})

    @blueprint.delete("/api/admin/penalties/<node_id>")
    @require_admin
    def api_admin_delete_penalty(node_id: str):
        node_key = str(node_id).strip()
        # support removing by either packed key "u--v" or single token "u-v"
        for key in list(ADMIN_EDGE_PENALTIES.keys()):
            if node_key in {"--".join(key), "-".join(key), key[0], key[1]}:
                ADMIN_EDGE_PENALTIES.pop(key, None)
        return jsonify({"penalties": _serialize_admin_penalties()})

    @blueprint.post("/api/admin/forbidden")
    @require_admin
    def api_admin_add_forbidden():
        payload = request.get_json(force=True, silent=True) or {}
        raw_from = payload.get("from") or payload.get("fromNode") or payload.get("u") or ""
        raw_to = payload.get("to") or payload.get("toNode") or payload.get("v") or ""
        try:
            edge_key = _edge_key(raw_from, raw_to)
            _ensure_nodes_exist(*edge_key)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        ADMIN_FORBIDDEN_EDGES.add(edge_key)
        return jsonify({"forbidden": _serialize_forbidden_edges()})

    @blueprint.delete("/api/admin/forbidden/<edge_id>")
    @require_admin
    def api_admin_delete_forbidden(edge_id: str):
        edge_key = str(edge_id).strip()
        for u, v in list(ADMIN_FORBIDDEN_EDGES):
            if edge_key in {"--".join((u, v)), "-".join((u, v)), u, v}:
                ADMIN_FORBIDDEN_EDGES.discard((u, v))
        return jsonify({"forbidden": _serialize_forbidden_edges()})

    app.register_blueprint(blueprint)
