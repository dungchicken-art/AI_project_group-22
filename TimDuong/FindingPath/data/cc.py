from pathlib import Path

import osmnx as ox

# Center of Khương Đình ward (approx)
center = (20.9945, 105.8155)
# Radius in meters to cover the whole ward
dist = 1200

# Fetch all street types (not just driveable)
G = ox.graph_from_point(
    center_point=center,
    dist=dist,
    network_type="all",
    retain_all=True,
)

graphml_path = Path(__file__).resolve().parent / "khuong_dinh.graphml"
ox.save_graphml(G, graphml_path)
print(f"Saved GraphML to {graphml_path}")
