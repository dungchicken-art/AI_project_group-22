"""Interactive pathfinding demo on top of OpenStreetMap data.

This module downloads a small road network, converts it into a graph and
provides multiple search algorithms (BFS, DFS, Dijkstra, UCS, Greedy Best-First, A*) to find a route
between two points.  The resulting path together with any blocked roads or
flooded zones can be rendered onto an interactive HTML map using Folium.

The implementation is structured around the :class:`PathfindingDemo` helper
which exposes high level methods for configuring constraints and computing
routes.  The main entry point of the module exposes a CLI so the script can be
used directly from the command line, for example::

    python pathfinding.py \
        --place "Hanoi, Vietnam" \
        --start "Đại học Bách Khoa Hà Nội" \
        --goal "Hồ Gươm" \
        --algorithm astar \
        --block-street "Trần Nhân Tông" \
        --output map.html

The generated HTML can be opened in a browser to visualise the road network,
start and goal markers, blocked segments and the path selected by the chosen
algorithm.
"""
from __future__ import annotations

import argparse
import io
import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Hashable, Iterable, List, Optional, Sequence, Tuple, Union, cast

import folium
import networkx as nx
import osmnx as ox
from shapely import wkt
from shapely.geometry import LineString, Polygon

from thuattoan import (
    NodeId,
    NodePath,
    run_astar,
    run_bfs,
    run_dfs,
    run_dijkstra,
    run_greedy_best_first,
    run_ucs,
)

def _resolve_module_attribute(modules: Sequence[object], names: Sequence[str]):
    """Return the first available attribute from the provided modules."""

    for module in modules:
        if module is None:
            continue
        for name in names:
            attr = getattr(module, name, None)
            if attr is not None:
                return attr
    return None


_GRAPH_MODULE = getattr(ox, "graph", None)
try:  # pragma: no cover - optional import for OSMnx 2.x compatibility
    from osmnx import graph as _graph_import  # type: ignore
except Exception:  # pragma: no cover - import is optional
    _graph_import = None
if _GRAPH_MODULE is None and _graph_import is not None:
    _GRAPH_MODULE = _graph_import

_UTILS_GRAPH_MODULE = getattr(ox, "utils_graph", None)
try:  # pragma: no cover - optional import for OSMnx 2.x compatibility
    from osmnx import utils_graph as _utils_graph_import  # type: ignore
except Exception:  # pragma: no cover - import is optional
    _utils_graph_import = None
if _UTILS_GRAPH_MODULE is None and _utils_graph_import is not None:
    _UTILS_GRAPH_MODULE = _utils_graph_import

_SIMPLIFICATION_MODULE = getattr(ox, "simplification", None)
try:  # pragma: no cover - optional import for OSMnx 2.x compatibility
    from osmnx import simplification as _simplification_import  # type: ignore
except Exception:  # pragma: no cover - import is optional
    _simplification_import = None
if _SIMPLIFICATION_MODULE is None and _simplification_import is not None:
    _SIMPLIFICATION_MODULE = _simplification_import

_DISTANCE_MODULE = getattr(ox, "distance", None)
try:  # pragma: no cover - optional import for OSMnx 2.x compatibility
    from osmnx import distance as _distance_import  # type: ignore
except Exception:  # pragma: no cover - import is optional
    _distance_import = None
if _DISTANCE_MODULE is None and _distance_import is not None:
    _DISTANCE_MODULE = _distance_import

_GEOCODER_MODULE = getattr(ox, "geocoder", None)
try:  # pragma: no cover - optional import for OSMnx 2.x compatibility
    from osmnx import geocoder as _geocoder_import  # type: ignore
except Exception:  # pragma: no cover - import is optional
    _geocoder_import = None
if _GEOCODER_MODULE is None and _geocoder_import is not None:
    _GEOCODER_MODULE = _geocoder_import

_FOLIUM_MODULE = getattr(ox, "folium", None)
try:  # pragma: no cover - optional import for OSMnx 2.x compatibility
    from osmnx import folium as _folium_import  # type: ignore
except Exception:  # pragma: no cover - import is optional
    _folium_import = None
if _FOLIUM_MODULE is None and _folium_import is not None:
    _FOLIUM_MODULE = _folium_import


def _graph_from_place(*, place: str, network_type: str):
    graph_func = _resolve_module_attribute(
        [_GRAPH_MODULE, ox], ["graph_from_place"]
    )
    if graph_func is None:  # pragma: no cover - depends on external package
        raise RuntimeError("Installed OSMnx does not provide graph_from_place")
    return graph_func(place=place, network_type=network_type)


def _graph_from_point(*, center: Coordinate, dist: int, network_type: str):
    graph_func = _resolve_module_attribute(
        [_GRAPH_MODULE, ox], ["graph_from_point"]
    )
    if graph_func is None:  # pragma: no cover - depends on external package
        raise RuntimeError("Installed OSMnx does not provide graph_from_point")
    return graph_func(center=center, dist=dist, network_type=network_type)


def _simplify_graph(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    # OSMnx GraphML exports are often already simplified; avoid re-simplifying.
    simplified_flag = graph.graph.get("simplified")
    if isinstance(simplified_flag, str):
        simplified_flag = simplified_flag.lower() == "true"
    if simplified_flag:
        return graph
    simplifier = _resolve_module_attribute(
        [_SIMPLIFICATION_MODULE, _GRAPH_MODULE, ox], ["simplify_graph"]
    )
    if simplifier is not None:
        return simplifier(graph)
    return graph


def _euclidean_dist_vec(uy: float, ux: float, vy: float, vx: float) -> float:
    return ((uy - vy) ** 2 + (ux - vx) ** 2) ** 0.5


def _nearest_node(graph: nx.MultiDiGraph, x: float, y: float):
    if _DISTANCE_MODULE is not None:
        nearest_func = getattr(_DISTANCE_MODULE, "nearest_nodes", None)
        if nearest_func is not None:
            node_id = nearest_func(graph, x, y)
            if hasattr(node_id, "item"):
                try:
                    node_id = node_id.item()
                except Exception:
                    pass
            if isinstance(node_id, (list, tuple)):
                node_id = node_id[0]
            if not graph.has_node(node_id):
                alt = str(node_id)
                if graph.has_node(alt):
                    node_id = alt
            return node_id  # type: ignore[return-value]
    # Fallback: brute force search (adequate for small demo graphs)
    best_node = None
    best_dist = float("inf")
    for node_id, data in graph.nodes(data=True):
        dist = (float(data.get("x", 0.0)) - x) ** 2 + (float(data.get("y", 0.0)) - y) ** 2
        if dist < best_dist:
            best_node = node_id
            best_dist = dist
    if best_node is None:  # pragma: no cover - graph should contain nodes
        raise ValueError("Graph contains no nodes")
    if best_node is not None and not graph.has_node(best_node):
        alt = str(best_node)
        if graph.has_node(alt):
            best_node = alt
    return best_node  # type: ignore[return-value]


def _plot_graph_folium(graph: nx.MultiDiGraph, **kwargs):
    plot_func = _resolve_module_attribute(
        [_FOLIUM_MODULE, ox], ["plot_graph_folium"]
    )
    if plot_func is not None:
        return plot_func(graph, **kwargs)
    # Minimal fallback: create an empty folium map centred on the graph bounds
    nodes = list(graph.nodes(data=True))
    if not nodes:  # pragma: no cover - graph should contain nodes
        return folium.Map()
    lats = [data.get("y", 0.0) for _, data in nodes]
    lons = [data.get("x", 0.0) for _, data in nodes]
    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)
    fmap = folium.Map(location=[center_lat, center_lon])
    for _, data in nodes:
        folium.CircleMarker(
            location=[data.get("y", center_lat), data.get("x", center_lon)],
            radius=2,
            color="blue",
            fill=True,
            fill_opacity=0.6,
        ).add_to(fmap)
    return fmap


def _geocode(value: str) -> Coordinate:
    geocode_func = _resolve_module_attribute(
        [_GEOCODER_MODULE, ox], ["geocode"]
    )
    if geocode_func is None:  # pragma: no cover - depends on external package
        raise RuntimeError("Installed OSMnx does not provide geocode")
    result = geocode_func(value)
    if isinstance(result, tuple) and len(result) == 2:
        return float(result[0]), float(result[1])
    if isinstance(result, Mapping):
        lat = result.get("lat") if "lat" in result else result.get("y")
        lon = result.get("lon") if "lon" in result else result.get("x")
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    if isinstance(result, list) and len(result) >= 2:
        return float(result[0]), float(result[1])
    raise ValueError(f"Could not geocode value '{value}'")

Coordinate = Tuple[float, float]
@dataclass
class RouteResult:
    """Represents the outcome of a pathfinding run."""

    algorithm: str
    node_path: NodePath
    total_length_m: float
    total_cost_m: float
    segment_details: List[Dict[str, object]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "algorithm": self.algorithm,
                "total_length_m": self.total_length_m,
                "total_cost_m": self.total_cost_m,
                "segments": self.segment_details,
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass(frozen=True)
class StreetPenaltySpec:
    name: str
    multiplier: float


@dataclass(frozen=True)
class OsmidPenaltySpec:
    osmid: int
    multiplier: float


class PathfindingDemo:
    """Utility to prepare a graph, block segments and execute algorithms."""

    def __init__(
        self,
        *,
        place: Optional[str] = None,
        center: Optional[Coordinate] = None,
        dist: int = 750,
        network_type: str = "drive",
        graph: Optional[nx.MultiDiGraph] = None,
    ) -> None:
        if graph is None and place is None and center is None:
            raise ValueError("Either `graph` or (`place`/`center`) must be provided")

        if graph is not None:
            # Work on a copy so per-request mutations do not leak between users.
            base_graph = graph.copy()
        elif place:
            base_graph = _graph_from_place(place=place, network_type=network_type)
        else:
            assert center is not None
            base_graph = _graph_from_point(
                center=center, dist=dist, network_type=network_type
            )

        # Keep the graph directed to preserve one-way constraints from OSM.
        if not isinstance(base_graph, nx.MultiDiGraph):
            base_graph = nx.MultiDiGraph(base_graph)
        self.graph = _simplify_graph(base_graph)
        self._coerce_node_coordinates()

        # Maintain sets of blocked edges and flooded polygons.
        self._blocked_edges: set[Tuple[NodeId, NodeId, Hashable]] = set()
        self._flood_zones: List[Polygon] = []
        self._edge_penalties: Dict[Tuple[NodeId, NodeId, Hashable], float] = {}

    def _coerce_node_coordinates(self) -> None:
        """Ensure x/y coordinates are floats to satisfy distance functions."""

        for _, data in self.graph.nodes(data=True):
            if "x" in data:
                try:
                    data["x"] = float(data["x"])
                except Exception:
                    data["x"] = float(data.get("lon", 0.0))
            if "y" in data:
                try:
                    data["y"] = float(data["y"])
                except Exception:
                    data["y"] = float(data.get("lat", 0.0))

    # ------------------------------------------------------------------
    # Helpers for configuring road closures / flood zones
    # ------------------------------------------------------------------
    def block_edges_by_name(self, names: Sequence[str]) -> None:
        """Block all edges whose `name` matches any provided street name."""

        normalized = {name.strip().lower() for name in names}
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            name = data.get("name")
            if not name:
                continue

            if isinstance(name, list):
                street_names = {n.lower() for n in name}
            else:
                street_names = {str(name).lower()}

            if street_names & normalized:
                self._blocked_edges.add((u, v, key))

    def block_edges_by_osmid(self, osmids: Iterable[int]) -> None:
        osmid_set = set(osmids)
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            if data.get("osmid") in osmid_set:
                self._blocked_edges.add((u, v, key))

    def _edge_identifier(self, u: NodeId, v: NodeId, key: Hashable) -> Tuple[NodeId, NodeId, Hashable]:
        return (u, v, key)

    def _set_edge_penalty(self, u: NodeId, v: NodeId, key: Hashable, multiplier: float) -> None:
        self._edge_penalties[self._edge_identifier(u, v, key)] = multiplier

    def _best_edge_between(
        self, u: NodeId, v: NodeId
    ) -> Tuple[NodeId, NodeId, Hashable, Dict[str, object], bool]:
        """Return the shortest edge connecting two nodes, preferring the given direction u->v.

        Returns (src, dst, key, data, reversed_dir) where reversed_dir is True
        if the best edge was found in the opposite direction (v->u).
        """

        # Prefer the forward direction first
        edge_dict = self.graph.get_edge_data(u, v)
        reversed_dir = False
        candidates: list[Tuple[NodeId, NodeId, Hashable, Dict[str, object], float, bool]] = []

        if edge_dict:
            for key, data in edge_dict.items():
                length = float(data.get("length", 1.0))
                candidates.append((u, v, key, data, length, False))

        edge_dict_rev = self.graph.get_edge_data(v, u)
        if edge_dict_rev:
            for key, data in edge_dict_rev.items():
                length = float(data.get("length", 1.0))
                candidates.append((v, u, key, data, length, True))

        if not candidates:
            raise ValueError(f"Khong tim thay duong noi {u} va {v}")

        src, dst, key, data, _, reversed_dir = min(candidates, key=lambda item: item[4])
        return src, dst, key, data, reversed_dir

    def penalize_edges_by_name(self, names: Sequence[str], *, multiplier: float) -> None:
        """Increase traversal cost on all edges with matching street names."""

        if multiplier <= 0:
            raise ValueError("Multiplier must be positive")

        normalized = {name.strip().lower() for name in names if name.strip()}
        if not normalized:
            return

        for u, v, key, data in self.graph.edges(keys=True, data=True):
            name = data.get("name")
            if not name:
                continue

            if isinstance(name, list):
                street_names = {n.lower() for n in name}
            else:
                street_names = {str(name).lower()}

            if street_names & normalized:
                self._set_edge_penalty(u, v, key, multiplier)

    def penalize_edges_by_osmid(self, osmids: Iterable[int], *, multiplier: float) -> None:
        """Increase traversal cost for edges whose OSM id matches."""

        if multiplier <= 0:
            raise ValueError("Multiplier must be positive")

        osmid_set = {int(osmid) for osmid in osmids}
        if not osmid_set:
            return

        for u, v, key, data in self.graph.edges(keys=True, data=True):
            osmid = data.get("osmid")
            if isinstance(osmid, list):
                osmid_values = {int(value) for value in osmid}
            elif osmid is not None:
                osmid_values = {int(osmid)}
            else:
                osmid_values = set()

            if osmid_values & osmid_set:
                self._set_edge_penalty(u, v, key, multiplier)

    def penalize_edges_by_node(self, node_ids: Iterable[NodeId], *, multiplier: float) -> None:
        """Increase traversal cost on all edges touching any of the provided nodes."""

        if multiplier <= 0:
            raise ValueError("Multiplier must be positive")

        normalized = {str(node_id) for node_id in node_ids if str(node_id).strip()}
        if not normalized:
            return

        for u, v, key in self.graph.edges(keys=True):
            if str(u) in normalized or str(v) in normalized:
                self._set_edge_penalty(u, v, key, multiplier)

    def penalize_edges_between(self, u: NodeId, v: NodeId, *, multiplier: float) -> None:
        """Increase cost for every edge between two nodes (both directions)."""

        if multiplier <= 0:
            raise ValueError("Multiplier must be positive")

        u_key = str(u)
        v_key = str(v)
        for src, dst in ((u_key, v_key), (v_key, u_key)):
            edge_dict = self.graph.get_edge_data(src, dst) or {}
            for key in edge_dict.keys():
                self._set_edge_penalty(src, dst, key, multiplier)

    def block_edges_between(self, u: NodeId, v: NodeId) -> None:
        """Block every edge between two nodes (both directions)."""

        u_key = str(u)
        v_key = str(v)
        for src, dst in ((u_key, v_key), (v_key, u_key)):
            edge_dict = self.graph.get_edge_data(src, dst) or {}
            for key in edge_dict.keys():
                self._blocked_edges.add((src, dst, key))

    def penalize_node_path(self, node_path: NodePath, *, multiplier: float) -> None:
        """Increase cost for every edge along a node path (both directions)."""

        if multiplier <= 0:
            raise ValueError("Multiplier must be positive")
        if len(node_path) < 2:
            return

        for u, v in zip(node_path[:-1], node_path[1:]):
            for src, dst in ((u, v), (v, u)):
                edge_dict = self.graph.get_edge_data(src, dst) or {}
                for key in edge_dict.keys():
                    self._set_edge_penalty(src, dst, key, multiplier)

    def shortest_path_nodes(self, source: NodeId, target: NodeId, *, weight: str = "length") -> NodePath:
        """Return the shortest node path (undirected) between two nodes."""

        graph = self.graph.copy()
        self._coerce_edge_lengths(graph)
        if weight == "cost":
            self._apply_penalties(graph)
        view = graph.to_undirected(as_view=True) if graph.is_directed() else graph
        try:
            path = nx.shortest_path(view, source=source, target=target, weight=weight)
        except nx.NetworkXNoPath as exc:
            raise ValueError(f"Khong tim thay duong noi {source} va {target}") from exc
        return cast(NodePath, path)

    def path_coordinates(self, node_path: NodePath) -> List[Coordinate]:
        """Expand a node path into full coordinates following edge geometries."""

        coords: List[Coordinate] = []
        if len(node_path) < 2:
            return coords

        for u, v in zip(node_path[:-1], node_path[1:]):
            src, dst, _, data, reversed_dir = self._best_edge_between(u, v)
            line = self._edge_linestring(src, dst, data)
            raw_coords = list(line.coords)
            if reversed_dir:
                raw_coords = list(reversed(raw_coords))
            edge_coords = [(float(lat), float(lon)) for lon, lat in raw_coords]
            if coords and edge_coords:
                edge_coords = edge_coords[1:]
            coords.extend(edge_coords)
        return coords

    def path_length(self, node_path: NodePath) -> float:
        """Compute total length following the shortest edges between nodes."""

        length = 0.0
        for u, v in zip(node_path[:-1], node_path[1:]):
            _, __, ___, data, ____ = self._best_edge_between(u, v)
            raw_length = data.get("length", 0.0)
            length += float(cast(Union[int, float, str], raw_length))
        return length

    def add_flood_zone(self, polygon_coords: Sequence[Coordinate]) -> None:
        """Mark a polygon as flooded; edges intersecting it are blocked."""

        polygon = Polygon(polygon_coords)
        self._flood_zones.append(polygon)

        for u, v, key, data in self.graph.edges(keys=True, data=True):
            geometry = data.get("geometry")
            if geometry is None:
                geometry = LineString(
                    [
                        (self.graph.nodes[u]["x"], self.graph.nodes[u]["y"]),
                        (self.graph.nodes[v]["x"], self.graph.nodes[v]["y"]),
                    ]
                )

            if geometry.intersects(polygon):
                self._blocked_edges.add((u, v, key))

    def _build_active_graph(self) -> nx.MultiDiGraph:
        """Return a copy of the graph with blocked segments removed."""

        active = self.graph.copy()
        self._apply_penalties(active)

        for u, v, key in list(self._blocked_edges):
            if active.has_edge(u, v, key):
                active.remove_edge(u, v, key)
        return active

    def export_graphml(self, output: Path, *, active_only: bool = False) -> None:
        """Persist the graph to GraphML with penalty and blockage metadata."""

        nx.write_graphml(
            self._weighted_graph(active_only=active_only, include_blocked=True),
            str(output),
        )

    def graphml_text(self, *, active_only: bool = False) -> str:
        """Return the graph in GraphML format as a text string."""

        buffer = io.BytesIO()
        try:
            nx.write_graphml(
                self._weighted_graph(active_only=active_only, include_blocked=True), buffer
            )
            return buffer.getvalue().decode("utf-8")
        except Exception:
            return ""

    def _apply_penalties(self, graph: nx.MultiDiGraph) -> None:
        for u, v, key, data in graph.edges(keys=True, data=True):
            penalty = float(
                self._edge_penalties.get(self._edge_identifier(u, v, key), 1.0)
            )
            length = float(data.get("length", 1.0))
            data["penalty_multiplier"] = penalty
            data["cost"] = length * penalty

    def _coerce_edge_lengths(self, graph: nx.MultiDiGraph) -> None:
        """Ensure all edge lengths are numeric floats for path computations."""

        for _, __, data in graph.edges(data=True):
            try:
                data["length"] = float(data.get("length", 1.0))
            except Exception:
                data["length"] = 1.0

    def _weighted_graph(
        self, *, active_only: bool = False, include_blocked: bool = False
    ) -> nx.MultiDiGraph:
        """Create a simple weighted graph for visualisation and export."""

        if active_only:
            source = self._build_active_graph()
        else:
            source = self.graph.copy()
            self._apply_penalties(source)

        weighted: nx.MultiDiGraph = nx.MultiDiGraph()

        for node, data in source.nodes(data=True):
            weighted.add_node(
                node,
                lat=float(data.get("y", 0.0)),
                lon=float(data.get("x", 0.0)),
            )

        for u, v, key, data in source.edges(keys=True, data=True):
            length = float(data.get("length", 1.0))
            cost = float(data.get("cost", length))
            penalty = float(data.get("penalty_multiplier", 1.0))
            attrs = {"length": length, "cost": cost, "penalty_multiplier": penalty}
            if include_blocked:
                attrs["blocked"] = (u, v, key) in self._blocked_edges
            weighted.add_edge(u, v, key=key, **attrs)

        return weighted

    def node_features(self) -> List[Dict[str, object]]:
        """Return GeoJSON-like point features for each node in the graph."""

        features: List[Dict[str, object]] = []
        degree_view = cast(Mapping[int, int], self.graph.degree)  # DegreeView lacks precise typing
        for node, data in self.graph.nodes(data=True):
            lat = float(data.get("y", 0.0))
            lon = float(data.get("x", 0.0))
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "id": node,
                        "degree": degree_view[node],
                    },
                }
            )
        return features

    def graph_statistics(self) -> Dict[str, float]:
        """Return basic statistics about the weighted graph."""

        graph = self._weighted_graph(active_only=False)
        node_count = graph.number_of_nodes()
        edge_count = graph.number_of_edges()
        total_length = sum(
            float(data.get("length", 0.0)) for _, _, data in graph.edges(data=True)
        )
        degree_view = cast(Iterable[Tuple[int, float]], graph.degree)  # DegreeView is iterable over (node, degree)
        degree_dict = {node: float(deg) for node, deg in degree_view}
        avg_degree = (sum(degree_dict.values()) / node_count) if node_count else 0.0
        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "total_length_m": total_length,
            "average_degree": avg_degree,
            "is_directed": graph.is_directed(),
        }

    def edge_features(self) -> List[Dict[str, object]]:
        """Return GeoJSON-like features representing the road network."""

        features: List[Dict[str, object]] = []
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            line = self._edge_linestring(u, v, data)
            coords = [[lon, lat] for lon, lat in line.coords]
            raw_length = data.get("length")
            length = float(raw_length) if raw_length is not None else None
            name = data.get("name")
            if isinstance(name, list):
                name = ", ".join(map(str, name))
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "from": u,
                        "to": v,
                        "key": key,
                        "name": name,
                        "length_m": length,
                    },
                }
            )
        return features

    def node_path_to_coordinates(self, path: NodePath) -> List[Coordinate]:
        return [
            (self.graph.nodes[node]["y"], self.graph.nodes[node]["x"]) for node in path
        ]

    def blocked_edge_features(self) -> List[Dict[str, object]]:
        features: List[Dict[str, object]] = []
        for u, v, key in self._blocked_edges:
            if not self.graph.has_edge(u, v, key):
                continue
            edge_data = self.graph.get_edge_data(u, v, key)
            if edge_data is None:
                continue
            line = self._edge_linestring(u, v, edge_data)
            coords = [[lon, lat] for lon, lat in line.coords]
            name = edge_data.get("name")
            if isinstance(name, list):
                name = ", ".join(map(str, name))
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {"name": name},
                }
            )
        return features

    def flood_zone_features(self) -> List[Dict[str, object]]:
        zones: List[Dict[str, object]] = []
        for polygon in self._flood_zones:
            coords = [[lon, lat] for lon, lat in polygon.exterior.coords]
            zones.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                }
            )
        return zones

    def penalized_edge_features(self) -> List[Dict[str, object]]:
        """Return features for edges whose cost multiplier was adjusted."""

        if not self._edge_penalties:
            return []

        # Sync penalty/cost fields before exporting.
        self._apply_penalties(self.graph)

        features: List[Dict[str, object]] = []
        for (u, v, key), penalty in self._edge_penalties.items():
            if not self.graph.has_edge(u, v, key):
                continue
            edge_data = self.graph.get_edge_data(u, v, key) or {}
            line = self._edge_linestring(u, v, edge_data)
            coords = [[lon, lat] for lon, lat in line.coords]
            name = edge_data.get("name")
            if isinstance(name, list):
                name = ", ".join(map(str, name))
            length = float(edge_data.get("length", 0.0))
            cost = float(edge_data.get("cost", length * float(penalty)))
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "from": u,
                        "to": v,
                        "key": key,
                        "name": name,
                        "length_m": length,
                        "cost_m": cost,
                        "penalty_multiplier": float(penalty),
                    },
                }
            )
        return features

    def bounds(self) -> Tuple[Coordinate, Coordinate]:
        lats = [float(data.get("y", 0.0)) for _, data in self.graph.nodes(data=True)]
        lons = [float(data.get("x", 0.0)) for _, data in self.graph.nodes(data=True)]
        south, north = min(lats), max(lats)
        west, east = min(lons), max(lons)
        return (south, west), (north, east)

    def centroid(self) -> Coordinate:
        (south, west), (north, east) = self.bounds()
        return ((south + north) / 2.0, (west + east) / 2.0)

    # ------------------------------------------------------------------
    # Pathfinding algorithms
    # ------------------------------------------------------------------
    def find_path(self, *, algorithm: str, start: Coordinate, goal: Coordinate) -> RouteResult:
        """Compute a path between the two coordinates using the chosen algorithm."""

        active_graph = self._build_active_graph()
        start_node = cast(NodeId, _nearest_node(active_graph, start[1], start[0]))
        goal_node = cast(NodeId, _nearest_node(active_graph, goal[1], goal[0]))

        algorithm = algorithm.lower()
        strategies: Dict[str, Callable[[nx.MultiDiGraph, NodeId, NodeId], NodePath]] = {
            "bfs": run_bfs,
            "dfs": run_dfs,
            "dijkstra": run_dijkstra,
            "ucs": run_ucs,
            "uniform_cost": run_ucs,
            "astar": lambda g, s, t: run_astar(g, s, t, dist_func=_euclidean_dist_vec),
            "a*": lambda g, s, t: run_astar(g, s, t, dist_func=_euclidean_dist_vec),
            "greedy": lambda g, s, t: run_greedy_best_first(g, s, t, dist_func=_euclidean_dist_vec),
            "greedy_best_first": lambda g, s, t: run_greedy_best_first(g, s, t, dist_func=_euclidean_dist_vec),
            "best_first": lambda g, s, t: run_greedy_best_first(g, s, t, dist_func=_euclidean_dist_vec),
            "gbfs": lambda g, s, t: run_greedy_best_first(g, s, t, dist_func=_euclidean_dist_vec),
        }

        if algorithm not in strategies:
            raise ValueError(f"Unsupported algorithm '{algorithm}'")

        node_path = strategies[algorithm](active_graph, start_node, goal_node)
        total_length, total_cost, segments = self._summarise_path(active_graph, node_path)
        return RouteResult(
            algorithm=algorithm,
            node_path=node_path,
            total_length_m=total_length,
            total_cost_m=total_cost,
            segment_details=segments,
        )

    # ------------------------------------------------------------------
    def render_map(
        self,
        result: RouteResult,
        *,
        output: Path,
        show_blocked: bool = True,
    ) -> None:
        """Create a folium map highlighting start, goal, blocked edges and the path."""

        fmap = _plot_graph_folium(
            self.graph, tiles="cartodbpositron", weight=2, opacity=0.6
        )

        # Start/goal markers
        start_node, goal_node = result.node_path[0], result.node_path[-1]
        start_coords = (self.graph.nodes[start_node]["y"], self.graph.nodes[start_node]["x"])
        goal_coords = (self.graph.nodes[goal_node]["y"], self.graph.nodes[goal_node]["x"])

        folium.Marker(start_coords, tooltip="Start", icon=folium.Icon(color="green", icon="play")).add_to(fmap)
        folium.Marker(goal_coords, tooltip="Goal", icon=folium.Icon(color="red", icon="stop")).add_to(fmap)

        if show_blocked and self._blocked_edges:
            for u, v, key in self._blocked_edges:
                if not self.graph.has_edge(u, v, key):
                    continue
                edge_data = self.graph.get_edge_data(u, v, key)
                line = self._edge_linestring(u, v, edge_data)
                folium.PolyLine(
                    [(lat, lon) for lon, lat in line.coords],
                    color="#444444",
                    weight=5,
                    opacity=0.7,
                    dash_array="5,7",
                    tooltip=f"Blocked: {edge_data.get('name', 'Unnamed road')}",
                ).add_to(fmap)

        for polygon in self._flood_zones:
            folium.Polygon(
                [(lat, lon) for lon, lat in polygon.exterior.coords],
                color="#EF6C00",
                fill=True,
                fill_opacity=0.35,
                weight=2,
                tooltip="Flooded zone",
            ).add_to(fmap)

        # Path polyline
        path_coords = [
            (self.graph.nodes[node]["y"], self.graph.nodes[node]["x"]) for node in result.node_path
        ]
        folium.PolyLine(path_coords, color="#1976D2", weight=6, opacity=0.9, tooltip=f"Path via {result.algorithm.upper()}").add_to(fmap)

        fmap.save(str(output))

    # ------------------------------------------------------------------
    def _summarise_path(
        self, graph: nx.MultiDiGraph, path: NodePath
    ) -> Tuple[float, float, List[Dict[str, object]]]:
        total_length = 0.0
        total_cost = 0.0
        segments: List[Dict[str, object]] = []
        for u, v in zip(path[:-1], path[1:]):
            edge_data_dict = graph.get_edge_data(u, v)
            if not edge_data_dict:
                edge_data_dict = graph.get_edge_data(v, u) or {}
            if not edge_data_dict:
                continue
            edge_data = min(edge_data_dict.values(), key=lambda d: d.get("length", 1.0))
            length = float(edge_data.get("length", 1.0))
            penalty = float(edge_data.get("penalty_multiplier", 1.0))
            cost = float(edge_data.get("cost", length * penalty))
            total_length += length
            total_cost += cost
            segments.append(
                {
                    "from": u,
                    "to": v,
                    "name": edge_data.get("name"),
                    "length_m": length,
                    "penalty_multiplier": penalty,
                    "cost_m": cost,
                }
            )
        return total_length, total_cost, segments

    def _edge_linestring(self, u: NodeId, v: NodeId, data: Dict[str, object]) -> LineString:
        geometry = data.get("geometry")
        if geometry is not None:
            if isinstance(geometry, str):
                try:
                    parsed = wkt.loads(geometry)
                    if isinstance(parsed, LineString):
                        return parsed
                    if hasattr(parsed, "coords"):
                        return LineString(parsed.coords)  # type: ignore[arg-type]
                except Exception:
                    # Fall back to manual reconstruction below
                    pass
            else:
                if isinstance(geometry, LineString):
                    return geometry
                if hasattr(geometry, "coords"):
                    return LineString(geometry.coords)  # type: ignore[arg-type]
        return LineString(
            [
                (self.graph.nodes[u]["x"], self.graph.nodes[u]["y"]),
                (self.graph.nodes[v]["x"], self.graph.nodes[v]["y"]),
            ]
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--place", help="Place name to download from OpenStreetMap")
    location.add_argument(
        "--center",
        nargs=2,
        type=float,
        metavar=("LAT", "LON"),
        help="Center coordinates to create a bounding box around",
    )
    parser.add_argument(
        "--dist",
        type=int,
        default=750,
        help="Radius in meters when using --center (default: 750)",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Address or 'lat,lon' pair for the start location",
    )
    parser.add_argument(
        "--goal",
        required=True,
        help="Address or 'lat,lon' pair for the goal location",
    )
    parser.add_argument(
        "--algorithm",
        choices=["bfs", "dfs", "dijkstra", "ucs", "astar", "greedy"],
        default="astar",
        help="Pathfinding algorithm to use",
    )
    parser.add_argument(
        "--block-street",
        action="append",
        default=[],
        help="Street name to block (can be used multiple times)",
    )
    parser.add_argument(
        "--flood-zone",
        action="append",
        default=[],
        metavar="LAT1,LON1;LAT2,LON2;...",
        help="Polygon describing a flooded zone (semicolon separated coordinates)",
    )
    parser.add_argument(
        "--penalize-street",
        action="append",
        default=[],
        metavar="NAME:MULTIPLIER",
        help="Increase traversal cost for a street (e.g. 'Nguyen Trai:1.5')",
    )
    parser.add_argument(
        "--penalize-osmid",
        action="append",
        default=[],
        metavar="OSMID:MULTIPLIER",
        help="Increase traversal cost by OpenStreetMap way id",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("path_result.html"),
        help="Where to save the rendered HTML map",
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Optional path to store the route summary as JSON",
    )
    parser.add_argument(
        "--graphml-output",
        type=Path,
        help="Optional path to export the graph as GraphML",
    )
    parser.add_argument(
        "--graphml-active",
        action="store_true",
        help="When exporting GraphML, omit blocked edges",
    )

    return parser.parse_args()


def parse_location(value: str) -> Coordinate:
    if "," in value:
        lat_str, lon_str = value.split(",", maxsplit=1)
        return float(lat_str.strip()), float(lon_str.strip())
    lat, lon = _geocode(value)
    return float(lat), float(lon)


def parse_polygon(raw: str) -> List[Coordinate]:
    coords: List[Coordinate] = []
    for pair in raw.split(";"):
        lat_str, lon_str = pair.split(",", maxsplit=1)
        coords.append((float(lat_str.strip()), float(lon_str.strip())))
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def parse_street_penalties(raw_specs: Sequence[str]) -> List[StreetPenaltySpec]:
    specs: List[StreetPenaltySpec] = []
    for raw in raw_specs:
        if not raw:
            continue
        if ":" not in raw:
            raise ValueError(f"Street penalty must be NAME:MULTIPLIER, got '{raw}'")
        name_part, multiplier_part = raw.split(":", maxsplit=1)
        name = name_part.strip()
        if not name:
            raise ValueError("Street penalty requires a non-empty name")
        multiplier = float(multiplier_part.strip())
        specs.append(StreetPenaltySpec(name=name, multiplier=multiplier))
    return specs


def parse_osmid_penalties(raw_specs: Sequence[str]) -> List[OsmidPenaltySpec]:
    specs: List[OsmidPenaltySpec] = []
    for raw in raw_specs:
        if not raw:
            continue
        if ":" not in raw:
            raise ValueError(f"OSM id penalty must be OSMID:MULTIPLIER, got '{raw}'")
        osmid_part, multiplier_part = raw.split(":", maxsplit=1)
        osmid = int(osmid_part.strip())
        multiplier = float(multiplier_part.strip())
        specs.append(OsmidPenaltySpec(osmid=osmid, multiplier=multiplier))
    return specs


def main() -> None:
    args = _parse_args()

    if args.center:
        center = (args.center[0], args.center[1])
        demo = PathfindingDemo(center=center, dist=args.dist)
    else:
        demo = PathfindingDemo(place=args.place)

    try:
        street_penalties = parse_street_penalties(args.penalize_street)
        osmid_penalties = parse_osmid_penalties(args.penalize_osmid)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.block_street:
        demo.block_edges_by_name(args.block_street)

    for spec in street_penalties:
        demo.penalize_edges_by_name([spec.name], multiplier=spec.multiplier)

    for spec in osmid_penalties:
        demo.penalize_edges_by_osmid([spec.osmid], multiplier=spec.multiplier)

    for raw_polygon in args.flood_zone:
        demo.add_flood_zone(parse_polygon(raw_polygon))

    start = parse_location(args.start)
    goal = parse_location(args.goal)

    result = demo.find_path(algorithm=args.algorithm, start=start, goal=goal)
    demo.render_map(result, output=args.output)

    if args.graphml_output:
        demo.export_graphml(args.graphml_output, active_only=args.graphml_active)

    print(result.to_json())
    print(f"Map saved to {args.output.resolve()}")

    if args.result_json:
        args.result_json.write_text(result.to_json(), encoding="utf-8")
        print(f"Route summary saved to {args.result_json.resolve()}")


if __name__ == "__main__":
    main()
