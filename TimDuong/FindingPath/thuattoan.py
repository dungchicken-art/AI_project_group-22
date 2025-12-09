from __future__ import annotations

import heapq
from collections import deque
from typing import Dict, Hashable, List, Optional, Protocol

import networkx as nx

NodeId = Hashable
NodePath = List[NodeId]


class Heuristic(Protocol):
    def __call__(self, uy: float, ux: float, vy: float, vx: float) -> float:
        ...


def run_bfs(graph: nx.MultiDiGraph, start: NodeId, goal: NodeId) -> NodePath:
    queue: deque[NodeId] = deque([start])
    parents: Dict[NodeId, Optional[NodeId]] = {start: None}

    while queue:
        node = queue.popleft()
        if node == goal:
            break
        for neighbor in graph.neighbors(node):
            if neighbor not in parents:
                parents[neighbor] = node
                queue.append(neighbor)

    if goal not in parents:
        raise nx.NetworkXNoPath(f"No path found between {start} and {goal}")

    return _reconstruct_path(parents, goal)


def run_dfs(graph: nx.MultiDiGraph, start: NodeId, goal: NodeId) -> NodePath:
    stack: List[NodeId] = [start]
    parents: Dict[NodeId, Optional[NodeId]] = {start: None}
    visited: set[NodeId] = set()

    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)

        if node == goal:
            break

        neighbors = list(graph.neighbors(node))
        for neighbor in reversed(neighbors):
            if neighbor not in parents:
                parents[neighbor] = node
                stack.append(neighbor)

    if goal not in parents:
        raise nx.NetworkXNoPath(f"No path found between {start} and {goal}")

    return _reconstruct_path(parents, goal)


def run_dijkstra(graph: nx.MultiDiGraph, start: NodeId, goal: NodeId) -> NodePath:
    frontier: list[tuple[float, NodeId]] = [(0.0, start)]
    best_costs: Dict[NodeId, float] = {start: 0.0}
    parents: Dict[NodeId, Optional[NodeId]] = {start: None}

    while frontier:
        cost, node = heapq.heappop(frontier)
        if cost > best_costs.get(node, float("inf")):
            continue
        if node == goal:
            break

        for neighbor in graph.neighbors(node):
            step_cost = _edge_travel_cost(graph, node, neighbor)
            if step_cost == float("inf"):
                continue
            new_cost = cost + step_cost
            if new_cost < best_costs.get(neighbor, float("inf")):
                best_costs[neighbor] = new_cost
                parents[neighbor] = node
                heapq.heappush(frontier, (new_cost, neighbor))

    if goal not in parents:
        raise nx.NetworkXNoPath(f"No path found between {start} and {goal}")

    return _reconstruct_path(parents, goal)


def run_ucs(graph: nx.MultiDiGraph, start: NodeId, goal: NodeId) -> NodePath:
    """Uniform Cost Search (equivalent to Dijkstra on positive edge costs)."""

    frontier: list[tuple[float, NodeId]] = [(0.0, start)]
    best_costs: Dict[NodeId, float] = {start: 0.0}
    parents: Dict[NodeId, Optional[NodeId]] = {start: None}

    while frontier:
        cost, node = heapq.heappop(frontier)
        if cost > best_costs.get(node, float("inf")):
            continue
        if node == goal:
            break

        for neighbor in graph.neighbors(node):
            step_cost = _edge_travel_cost(graph, node, neighbor)
            if step_cost == float("inf"):
                continue
            new_cost = cost + step_cost
            if new_cost < best_costs.get(neighbor, float("inf")):
                best_costs[neighbor] = new_cost
                parents[neighbor] = node
                heapq.heappush(frontier, (new_cost, neighbor))

    if goal not in parents:
        raise nx.NetworkXNoPath(f"No path found between {start} and {goal}")

    return _reconstruct_path(parents, goal)


def run_astar(
    graph: nx.MultiDiGraph,
    start: NodeId,
    goal: NodeId,
    dist_func: Heuristic,
) -> NodePath:
    def heuristic(node: NodeId) -> float:
        ux, uy = graph.nodes[node]["x"], graph.nodes[node]["y"]
        vx, vy = graph.nodes[goal]["x"], graph.nodes[goal]["y"]
        return dist_func(uy, ux, vy, vx)

    frontier: list[tuple[float, float, NodeId]] = [(heuristic(start), 0.0, start)]
    g_scores: Dict[NodeId, float] = {start: 0.0}
    parents: Dict[NodeId, Optional[NodeId]] = {start: None}
    visited: set[NodeId] = set()

    while frontier:
        f_cost, g_cost, node = heapq.heappop(frontier)
        if node in visited:
            continue
        if node == goal:
            break
        visited.add(node)

        for neighbor in graph.neighbors(node):
            if neighbor in visited:
                continue
            step_cost = _edge_travel_cost(graph, node, neighbor)
            if step_cost == float("inf"):
                continue
            tentative_g = g_cost + step_cost
            if tentative_g < g_scores.get(neighbor, float("inf")):
                g_scores[neighbor] = tentative_g
                parents[neighbor] = node
                f_score = tentative_g + heuristic(neighbor)
                heapq.heappush(frontier, (f_score, tentative_g, neighbor))

    if goal not in parents:
        raise nx.NetworkXNoPath(f"No path found between {start} and {goal}")

    return _reconstruct_path(parents, goal)


def run_greedy_best_first(
    graph: nx.MultiDiGraph,
    start: NodeId,
    goal: NodeId,
    dist_func: Heuristic,
) -> NodePath:
    """
    Greedy Best-First Search using the provided heuristic to choose expansions.
    The heuristic guides the order; path costs are not accumulated.
    """

    def heuristic(node: NodeId) -> float:
        nx_val, ny_val = graph.nodes[node]["x"], graph.nodes[node]["y"]
        gx, gy = graph.nodes[goal]["x"], graph.nodes[goal]["y"]
        return dist_func(ny_val, nx_val, gy, gx)

    frontier: list[tuple[float, NodeId]] = [(heuristic(start), start)]
    parents: Dict[NodeId, Optional[NodeId]] = {start: None}
    best_scores: Dict[NodeId, float] = {start: frontier[0][0]}
    visited: set[NodeId] = set()

    while frontier:
        _, node = heapq.heappop(frontier)
        if node in visited:
            continue
        visited.add(node)
        if node == goal:
            break

        for neighbor in graph.neighbors(node):
            if neighbor in visited:
                continue
            score = heuristic(neighbor)
            if score < best_scores.get(neighbor, float("inf")):
                best_scores[neighbor] = score
                parents[neighbor] = node
                heapq.heappush(frontier, (score, neighbor))

    if goal not in parents:
        raise nx.NetworkXNoPath(f"No path found between {start} and {goal}")

    return _reconstruct_path(parents, goal)


def _reconstruct_path(
    parents: Dict[NodeId, Optional[NodeId]], goal: NodeId
) -> NodePath:
    path: NodePath = []
    current: Optional[NodeId] = goal
    while current is not None:
        path.append(current)
        current = parents.get(current)
    path.reverse()
    return path


def _edge_travel_cost(graph: nx.MultiDiGraph, u: NodeId, v: NodeId) -> float:
    """Return the minimum traversal cost between two connected nodes."""

    edge_data = graph.get_edge_data(u, v)
    if not edge_data:
        return float("inf")
    best = float("inf")
    for data in edge_data.values():
        try:
            cost = float(data.get("cost", data.get("length", 1.0)))  # type: ignore[arg-type]
        except Exception:
            cost = 1.0
        if cost < best:
            best = cost
    return best
