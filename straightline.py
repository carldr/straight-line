"""Load an OpenStreetMap area and its path network, and draw the result.

All geometry that this module returns is in the graph's UTM projection, in metres.
"""

import sys
import subprocess

import geopandas
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox
import requests
import shapely
from matplotlib.collections import LineCollection
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize

OVERPASS_URL = "https://overpass-planet.grn.haus/api"
WATER_POLYGONS_PATH = "water-polygons-split-4326/water_polygons.shp"

ox.settings.overpass_url = OVERPASS_URL
#  The private server has no per-client slots, so osmnx must not wait for one.
ox.settings.overpass_rate_limit = False
ox.settings.requests_timeout = 900
ox.settings.overpass_settings = "[out:json][timeout:{timeout}][maxsize:4000000000]"
ox.settings.use_cache = True
ox.settings.log_console = False


def largest_polygon(geometry):
    """Return the largest polygon of a Polygon or MultiPolygon."""
    if isinstance(geometry, MultiPolygon):
        return max(geometry.geoms, key=lambda polygon: polygon.area)
    return geometry


def fetch_relation_polygon(relation_id):
    """Fetch an OSM relation from Overpass and build its area, in longitude and latitude."""
    query = f"[out:json][timeout:300];rel({relation_id});out geom;"
    response = requests.post(f"{OVERPASS_URL}/interpreter", data={"data": query}, timeout=600)
    response.raise_for_status()
    elements = response.json()["elements"]
    if not elements:
        sys.exit(f"Relation {relation_id} does not exist.")

    outer_lines = []
    inner_lines = []
    for member in elements[0]["members"]:
        if member["type"] != "way" or "geometry" not in member:
            continue
        line = LineString([(point["lon"], point["lat"]) for point in member["geometry"]])
        if member["role"] == "inner":
            inner_lines.append(line)
        else:
            outer_lines.append(line)

    #  polygonize joins the member ways into closed rings, in any order and direction.
    outer = shapely.union_all(list(polygonize(outer_lines)))
    inner = shapely.union_all(list(polygonize(inner_lines)))
    return outer.difference(inner)


def load_area(relation_id):
    """Return the land area of a relation, in longitude and latitude.

    The area is the largest polygon of the relation, less the sea, less any islands that the sea cuts off.
    """
    relation_polygon = largest_polygon(fetch_relation_polygon(relation_id))
    water = geopandas.read_file(WATER_POLYGONS_PATH, bbox=relation_polygon.bounds)
    land = relation_polygon.difference(shapely.union_all(water.geometry.values))
    return largest_polygon(land)


def load_graph(area_lonlat, activity):
    """Fetch the path network for the activity inside the area, as an undirected graph in UTM metres.

    The graph is undirected, so every route can be walked or cycled in both directions.
    """
    graph = ox.graph_from_polygon(area_lonlat, network_type=activity, truncate_by_edge=True)
    graph = ox.project_graph(graph)
    return ox.convert.to_undirected(graph)


def project_to_graph(geometry_lonlat, graph):
    """Project a longitude and latitude geometry into the graph's CRS."""
    geometry, _ = ox.projection.project_geometry(geometry_lonlat, to_crs=graph.graph["crs"])
    return geometry


def edge_line(graph, u, v, data):
    """Return the geometry of an edge, as a line from u to v."""
    if "geometry" in data:
        line = data["geometry"]
    else:
        line = LineString([(graph.nodes[u]["x"], graph.nodes[u]["y"]), (graph.nodes[v]["x"], graph.nodes[v]["y"])])
    start_x, start_y = line.coords[0]
    distance_start_to_u = (start_x - graph.nodes[u]["x"]) ** 2 + (start_y - graph.nodes[u]["y"]) ** 2
    distance_start_to_v = (start_x - graph.nodes[v]["x"]) ** 2 + (start_y - graph.nodes[v]["y"]) ** 2
    if distance_start_to_v < distance_start_to_u:
        line = line.reverse()
    return line


def route_line(graph, route_nodes, corridor_edges):
    """Join the edges of a route into one line.

    Between two nodes, the route uses the shortest parallel edge in corridor_edges.
    """
    coords = []
    for u, v in zip(route_nodes[:-1], route_nodes[1:]):
        keys = [key for key in graph[u][v] if (u, v, key) in corridor_edges or (v, u, key) in corridor_edges]
        key = min(keys, key=lambda key: graph[u][v][key]["length"])
        line_coords = list(edge_line(graph, u, v, graph[u][v][key]).coords)
        coords.extend(line_coords if not coords else line_coords[1:])
    return LineString(coords)


def draw_result(graph, area, endpoint_xy, straight_line, max_deviation, route, filename):
    """Draw the area, the network, the corridor, the straight line and the route to a PNG."""
    west, south, east, north = area.bounds
    width = east - west
    height = north - south
    scale = 12 / max(width, height)
    fig, ax = plt.subplots(figsize=(max(width * scale, 4), max(height * scale, 4)), layout="constrained")
    ax.set_aspect("equal")
    ax.set_axis_off()

    edge_lines = [np.asarray(edge_line(graph, u, v, data).coords) for u, v, data in graph.edges(data=True)]
    ax.add_collection(LineCollection(edge_lines, colors="#999999", linewidths=0.15))

    for ring in [area.exterior, *area.interiors]:
        x, y = ring.xy
        ax.plot(x, y, color="black", linewidth=0.6)

    corridor = straight_line.buffer(max_deviation, cap_style="flat")
    x, y = corridor.exterior.xy
    ax.fill(x, y, color="#4c9be8", alpha=0.25, linewidth=0)

    ax.scatter(endpoint_xy[:, 0], endpoint_xy[:, 1], s=0.5, color="red", linewidths=0)

    x, y = straight_line.xy
    ax.plot(x, y, color="blue", linewidth=0.4)
    x, y = route.xy
    ax.plot(x, y, color="green", linewidth=1.0)

    ax.text(0.01, 0.01, f"Max deviation: {max_deviation:.1f} m", transform=ax.transAxes, fontsize=14, ha="left", va="bottom")

    ax.set_xlim(west - width * 0.02, east + width * 0.02)
    ax.set_ylim(south - height * 0.02, north + height * 0.02)
    fig.savefig(filename, dpi=300)
    plt.close(fig)

    if sys.platform == "darwin":
        subprocess.run(["open", filename], check=False)
