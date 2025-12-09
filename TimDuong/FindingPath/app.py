from __future__ import annotations

import os
import json
from collections.abc import Mapping as MappingABC
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, Optional, Tuple, Union, cast
from uuid import uuid4

import networkx as nx
from flask import Flask, jsonify, render_template, request

from admin_routes import apply_admin_penalties, init_admin

from pathfinding import Coordinate, PathfindingDemo, parse_location, parse_polygon

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-admin-secret")

DEFAULT_DIST = 750
# Use all street types (not just driveable) to match "full street" requirement.
DEFAULT_NETWORK_TYPE = "all"
FOCUS_CENTER: Coordinate = (20.9945, 105.8155)
# Resolve the GraphML path relative to this file, so it works regardless of the cwd.
GRAPHML_PATH = (Path(__file__).resolve().parent / "data" / "khuong_dinh.graphml")
CREATED_NODES_PATH = (Path(__file__).resolve().parent / "data" / "created_nodes.json")
FOCUS_CENTER: Coordinate = (20.9945, 105.8155)


def _normalize_center(value: Optional[Union[Mapping[str, float], Iterable[float]]]) -> Optional[Coordinate]:
    if value is None:
        return None
    if isinstance(value, MappingABC):
        mapping_value = cast(Mapping[str, float], value)
        return float(mapping_value["lat"]), float(mapping_value["lon"])
    seq = list(value)
    if len(seq) != 2:
        raise ValueError("Center must have two values: lat and lon")
    return float(seq[0]), float(seq[1])


def _normalize_coordinate(value: Union[str, Mapping[str, float], Iterable[float]]) -> Coordinate:
    if isinstance(value, str):
        return parse_location(value)
    if isinstance(value, MappingABC):
        mapping_value = cast(Mapping[str, float], value)
        return float(mapping_value["lat"]), float(mapping_value["lon"])
    seq = list(value)
    if len(seq) != 2:
        raise ValueError("Coordinate must contain two values")
    return float(seq[0]), float(seq[1])


def _normalize_blocked_streets(value: Optional[Union[str, Iterable[str]]]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        lines = value.splitlines()
        return [line.strip() for line in lines if line.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_flood_zones(value: Optional[Iterable[Union[str, Iterable[Iterable[float]]]]]) -> List[List[Coordinate]]:
    if not value:
        return []
    zones: List[List[Coordinate]] = []
    for entry in value:
        if isinstance(entry, str):
            zones.append(parse_polygon(entry))
        else:
            coords: List[Coordinate] = []
            for coord in entry:
                coord_seq = list(coord)
                if len(coord_seq) != 2:
                    raise ValueError("Flood zone coordinates must be [lat, lon]")
                coords.append((float(coord_seq[0]), float(coord_seq[1])))
            if coords and coords[0] != coords[-1]:
                coords.append(coords[0])
            zones.append(coords)
    return zones


@lru_cache(maxsize=8)
def _get_cached_graph(
    place: Optional[str], center: Optional[Coordinate], dist: int, network_type: str
):
    return PathfindingDemo(place=place, center=center, dist=dist, network_type=network_type).graph


def _create_demo(
    *, place: Optional[str], center: Optional[Coordinate], dist: int, network_type: str
) -> PathfindingDemo:
    graph = _get_cached_graph(place, center, dist, network_type)
    return PathfindingDemo(graph=graph, network_type=network_type)

@lru_cache(maxsize=1)
def _load_base_graph() -> nx.MultiDiGraph:
    """Load the static Khuong Dinh graph once from disk."""

    if not GRAPHML_PATH.exists():
        raise RuntimeError(
            f"Offline graph not found at {GRAPHML_PATH}. Please place the Khuong Dinh GraphML there."
        )
    graph = nx.read_graphml(GRAPHML_PATH)
    if not isinstance(graph, nx.MultiDiGraph):
        graph = nx.MultiDiGraph(graph)
    return graph


def _load_focus_demo(network_type: str = DEFAULT_NETWORK_TYPE) -> PathfindingDemo:
    """
    Always build the fixed Khuong Dinh graph from a local GraphML only.
    Network downloads are disabled; ensure GRAPHML_PATH exists.
    """
    return PathfindingDemo(graph=_load_base_graph(), network_type=network_type)


# Narrow the callable type for admin wiring to keep Pylance happy.
LoadFocusDemo = Callable[[str], PathfindingDemo]

init_admin(
    app,
    load_base_graph=_load_base_graph,
    load_focus_demo=cast(LoadFocusDemo, _load_focus_demo),
    default_network_type=DEFAULT_NETWORK_TYPE,
)


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.post("/api/load")
def api_load():
    payload = request.get_json(force=True, silent=True) or {}
    # Lock the app to the Khuong Dinh area to keep the dataset consistent.
    network_type = DEFAULT_NETWORK_TYPE

    try:
        demo = _load_focus_demo(network_type=network_type)
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
            "graphml": demo.graphml_text(),
            "created_nodes": _load_created_nodes(),
        }
    )


def _load_created_nodes() -> List[dict]:
    if not CREATED_NODES_PATH.exists():
        return []
    try:
        data = json.loads(CREATED_NODES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _persist_created_nodes(nodes: List[dict]) -> None:
    CREATED_NODES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREATED_NODES_PATH.write_text(json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")


@app.post("/api/nodes")
def api_create_node():
    payload = request.get_json(force=True, silent=True) or {}
    raw_lat = payload.get("lat") or payload.get("latitude")
    raw_lon = payload.get("lon") or payload.get("lng") or payload.get("longitude")
    place = str(payload.get("place") or "").strip() or None

    if raw_lat is None or raw_lon is None:
        return jsonify({"error": "Thieu toa do lat/lon"}), 400

    try:
        lat = float(raw_lat)
        lon = float(raw_lon)
    except (TypeError, ValueError):
        return jsonify({"error": "Toa do khong hop le"}), 400

    existing = _load_created_nodes()
    node_id = f"user-node-{len(existing) + 1:04d}-{uuid4().hex[:6]}"
    record = {
        "id": node_id,
        "lat": lat,
        "lon": lon,
        "place": place,
        "source": "web",
    }
    existing.append(record)
    try:
        _persist_created_nodes(existing)
    except Exception as exc:
        return jsonify({"error": f"Khong luu duoc node moi: {exc}"}), 500

    return jsonify(
        {
            "node_id": node_id,
            "lat": lat,
            "lon": lon,
            "place": place,
        }
    )


@app.get("/api/nodes")
def api_list_nodes():
    return jsonify({"nodes": _load_created_nodes()})


@app.delete("/api/nodes/<node_id>")
def api_delete_node(node_id: str):
    target = str(node_id).strip()
    if not target:
        return jsonify({"error": "Thieu id node"}), 400
    nodes = _load_created_nodes()
    filtered = [node for node in nodes if str(node.get("id")) != target]
    if len(filtered) == len(nodes):
        return jsonify({"error": "Khong tim thay node"}), 404
    try:
        _persist_created_nodes(filtered)
    except Exception as exc:
        return jsonify({"error": f"Khong xoa duoc: {exc}"}), 500
    return jsonify({"nodes": filtered})


@app.post("/api/path")
def api_path():
    payload = request.get_json(force=True, silent=True) or {}

    # Always use the fixed Khuong Dinh graph.
    network_type = DEFAULT_NETWORK_TYPE

    algorithm = payload.get("algorithm", "astar")

    if "start" not in payload or "goal" not in payload:
        return jsonify({"error": "Thieu diem xuat phat hoac dich"}), 400

    created_nodes = _load_created_nodes()
    created_lookup = {str(node.get("id")): node for node in created_nodes}

    def _resolve_created_node(node_id_key: str, coord_key: str) -> Coordinate:
        node_id = str(payload.get(node_id_key) or "").strip()
        if node_id and node_id in created_lookup:
            node = created_lookup[node_id]
            try:
                return float(node["lat"]), float(node["lon"])
            except Exception:
                pass
        if coord_key not in payload:
            raise ValueError("Thieu toa do")
        return _normalize_coordinate(payload[coord_key])

    try:
        start = _resolve_created_node("startNodeId", "start")
        goal = _resolve_created_node("goalNodeId", "goal")
        blocked_streets = _normalize_blocked_streets(payload.get("blockedStreets"))
        flood_zones = _normalize_flood_zones(payload.get("floodZones"))
        demo = _load_focus_demo(network_type=network_type)
        apply_admin_penalties(demo)

        if blocked_streets:
            demo.block_edges_by_name(blocked_streets)
        for zone in flood_zones:
            demo.add_flood_zone(zone)

        result = demo.find_path(algorithm=algorithm, start=start, goal=goal)
    except ValueError as exc:
        message = str(exc)
        if "not reachable" in message.lower() or "no path" in message.lower() or "khong tim thay duong" in message.lower():
            message = "Khong tim duoc duong di hop le"
        return jsonify({"error": message}), 400
    except Exception as exc:  # pragma: no cover - expose friendly message
        return jsonify({"error": "Khong tim duoc duong di hop le"}), 400

    return jsonify(
        {
            "algorithm": result.algorithm,
            "total_length_m": result.total_length_m,
            "total_cost_m": result.total_cost_m,
            "path": demo.node_path_to_coordinates(result.node_path),
            "path_coords": demo.path_coordinates(result.node_path),
            "segments": result.segment_details,
            "blocked": demo.blocked_edge_features(),
            "flood_zones": demo.flood_zone_features(),
        }
    )

if __name__ == "__main__":
    app.run(debug=True)
