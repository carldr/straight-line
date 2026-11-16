"""Load an OpenStreetMap area and its path network, and draw the result.

All geometry that this module returns is in the graph's UTM projection, in metres.
"""

import logging
import re
import subprocess
import sys
import xml.sax.saxutils

import geopandas
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import osmnx as ox
import requests
import shapely
from matplotlib.collections import LineCollection
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize

OVERPASS_URL = "https://overpass-planet.grn.haus/api"
WATER_POLYGONS_PATH = "water-polygons-split-4326/water_polygons.shp"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
#  The Nominatim usage policy requires a User-Agent that names the application.
NOMINATIM_USER_AGENT = "straight-line-route-finder/0.1"
#  The largest number of results that Nominatim gives for one search.
NOMINATIM_RESULT_LIMIT = 40

ox.settings.overpass_url = OVERPASS_URL
#  The private server has no per-client slots, so osmnx must not wait for one.
ox.settings.overpass_rate_limit = False
ox.settings.requests_timeout = 900
ox.settings.overpass_settings = "[out:json][timeout:{timeout}][maxsize:4000000000]"
ox.settings.use_cache = True
ox.settings.log_console = False
#  osmnx sends its messages to the logging module only when log_file is on. download_graph reads them for progress.
ox.settings.log_file = True
ox.settings.logs_folder = "cache/logs"
#  apply_bicycle_one_way reads these tags.
ox.settings.useful_tags_way = [*ox.settings.useful_tags_way, "oneway:bicycle", "cycleway"]

#  These tags let a bicycle go against a one-way street.
BICYCLE_CONTRAFLOW_CYCLEWAY_VALUES = {"opposite", "opposite_lane", "opposite_track"}


def largest_polygon(geometry):
    """Return the largest polygon of a Polygon or MultiPolygon."""
    if isinstance(geometry, MultiPolygon):
        return max(geometry.geoms, key=lambda polygon: polygon.area)
    return geometry


def search_boundaries(query):
    """Search Nominatim for boundary relations that match a place name.

    Nominatim often finds a town as a place node, with its boundary in a relation of another name,
    such as Whitchurch and "Whitchurch Urban". For each place node, the result lists the boundaries that the node belongs to.

    Returns a list of (relation id, display name, kind of place), in Nominatim's order of relevance.
    """
    response = requests.get(
        NOMINATIM_SEARCH_URL,
        params={"q": query, "format": "jsonv2", "limit": NOMINATIM_RESULT_LIMIT},
        headers={"User-Agent": NOMINATIM_USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    results = response.json()
    place_node_ids = [
        result["osm_id"] for result in results if result["osm_type"] == "node" and result["category"] == "place"
    ]
    boundaries_of_place_nodes = fetch_boundaries_of_nodes(place_node_ids)

    matches = []
    for result in results:
        if result["osm_type"] == "relation" and result["category"] == "boundary":
            matches.append((result["osm_id"], result["display_name"], result["addresstype"]))
        elif result["osm_type"] == "node" and result["category"] == "place":
            for relation_id, tags in boundaries_of_place_nodes.get(result["osm_id"], []):
                kind = (tags.get("designation") or f"admin level {tags.get('admin_level', '?')}").replace("_", " ")
                matches.append((relation_id, f"{tags.get('name', relation_id)}, for {result['display_name']}", kind))

    unique_matches = []
    seen_relation_ids = set()
    for match in matches:
        if match[0] not in seen_relation_ids:
            seen_relation_ids.add(match[0])
            unique_matches.append(match)
    return unique_matches


def fetch_boundaries_of_nodes(node_ids):
    """Return, for each node id, the (relation id, tags) of the boundary relations that have the node as a member."""
    if not node_ids:
        return {}
    query = f"[out:json][timeout:60];node(id:{','.join(map(str, node_ids))});foreach{{out ids;rel(bn)[boundary];out tags;}}"
    response = requests.post(f"{OVERPASS_URL}/interpreter", data={"data": query}, timeout=120)
    response.raise_for_status()

    #  foreach writes each node, then the relations of that node.
    boundaries = {}
    current_node_id = None
    for element in response.json()["elements"]:
        if element["type"] == "node":
            current_node_id = element["id"]
            boundaries[current_node_id] = []
        else:
            boundaries[current_node_id].append((element["id"], element.get("tags", {})))
    return boundaries


def fetch_relation_name(relation_id):
    """Return the name tag of an OSM relation, from Overpass."""
    query = f"[out:json][timeout:60];rel({relation_id});out tags;"
    response = requests.post(f"{OVERPASS_URL}/interpreter", data={"data": query}, timeout=120)
    response.raise_for_status()
    elements = response.json()["elements"]
    if not elements:
        sys.exit(f"Relation {relation_id} does not exist.")
    return elements[0]["tags"].get("name", str(relation_id))


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


def remove_sea(polygon_lonlat):
    """Return the largest piece of land in a polygon, in longitude and latitude.

    The sea, and any islands that the sea cuts off, are not part of the result.
    """
    water = geopandas.read_file(WATER_POLYGONS_PATH, bbox=polygon_lonlat.bounds)
    land = polygon_lonlat.difference(shapely.union_all(water.geometry.values))
    return largest_polygon(land)


class OverpassDownloadProgress(logging.Handler):
    """Turn the osmnx log messages about Overpass requests into a progress text, and give it to report."""

    def __init__(self, report):
        super().__init__()
        self.report = report
        self.request_count = 1
        self.requests_done = 0
        self.requests_from_cache = 0
        self.megabytes = 0.0

    def emit(self, record):
        message = record.getMessage()
        if match := re.match(r"Requesting data from API in (\d+) request", message):
            self.request_count = int(match[1])
        elif match := re.match(r"Downloaded ([\d,.]+)kB", message):
            self.requests_done += 1
            self.megabytes += float(match[1].replace(",", "")) / 1000
        elif message.startswith("Retrieved response from cache"):
            self.requests_done += 1
            self.requests_from_cache += 1
        else:
            return
        cache_text = f", {self.requests_from_cache} from cache" if self.requests_from_cache else ""
        if self.requests_done < self.request_count:
            self.report(
                f"request {self.requests_done + 1}/{self.request_count}, {self.megabytes:.1f} MB downloaded{cache_text}"
            )
        else:
            self.report(f"building the graph from {self.request_count} responses, {self.megabytes:.1f} MB downloaded{cache_text}")


def download_graph(area_lonlat, activity, report):
    """Download the unsimplified path network for the activity inside the area.

    report receives a progress text after each Overpass request.
    """
    handler = OverpassDownloadProgress(report)
    osmnx_logger = logging.getLogger(ox.settings.log_name)
    #  osmnx sets the logger level only when the logger has no handler yet, so a handler added first gets no INFO messages.
    osmnx_logger.setLevel(min(osmnx_logger.level or logging.INFO, logging.INFO))
    osmnx_logger.addHandler(handler)
    try:
        return ox.graph_from_polygon(area_lonlat, network_type=activity, truncate_by_edge=True, simplify=False)
    finally:
        osmnx_logger.removeHandler(handler)


def apply_bicycle_one_way(graph):
    """Change the directions of an unsimplified bike graph to the directions that a bicycle may legally use.

    osmnx makes every one-way street one-way, and ignores the tags that change the direction for bicycles only.
    """
    for u, v, key, data in list(graph.edges(keys=True, data=True)):
        oneway_bicycle = data.get("oneway:bicycle")
        if data["oneway"]:
            if oneway_bicycle == "no" or data.get("cycleway") in BICYCLE_CONTRAFLOW_CYCLEWAY_VALUES:
                graph.add_edge(v, u, **{**data, "reversed": True})
        elif oneway_bicycle in ("yes", "true", "1") and data["reversed"]:
            graph.remove_edge(u, v, key)
        elif oneway_bicycle in ("-1", "reverse") and not data["reversed"]:
            graph.remove_edge(u, v, key)


def prepare_graph(graph, activity):
    """Simplify a downloaded graph and project it to UTM metres.

    The walk graph becomes undirected. The bike graph stays directed, and is cut so that every node can reach every other node.
    """
    if activity == "walk":
        return ox.convert.to_undirected(ox.project_graph(ox.simplify_graph(graph)))

    apply_bicycle_one_way(graph)
    graph = ox.simplify_graph(graph)
    graph = ox.truncate.largest_component(graph, strongly=True)
    return ox.project_graph(graph)


def clip_graph_to_area(graph, area):
    """Return the part of a projected graph inside the area.

    Where an edge crosses the area boundary, a new node at the crossing point ends the edge.
    These nodes have the attribute boundary_crossing. The result keeps only its largest connected part.
    """
    shapely.prepare(area)
    clipped = graph.__class__()
    clipped.graph = dict(graph.graph)
    crossing_node_ids = {}

    def node_at(point, u, v):
        """Return the node at point: u or v if the point is at one of them, else a crossing node."""
        for node in (u, v):
            if abs(graph.nodes[node]["x"] - point[0]) < 0.01 and abs(graph.nodes[node]["y"] - point[1]) < 0.01:
                clipped.add_node(node, **graph.nodes[node])
                return node
        key = (round(point[0], 2), round(point[1], 2))
        if key not in crossing_node_ids:
            crossing_node_ids[key] = -1 - len(crossing_node_ids)
            clipped.add_node(crossing_node_ids[key], x=point[0], y=point[1], boundary_crossing=True)
        return crossing_node_ids[key]

    for u, v, data in graph.edges(data=True):
        line = edge_line(graph, u, v, data)
        if area.covers(line):
            clipped.add_node(u, **graph.nodes[u])
            clipped.add_node(v, **graph.nodes[v])
            clipped.add_edge(u, v, **data)
            continue
        inside = line.intersection(area)
        for piece in getattr(inside, "geoms", [inside]):
            if not isinstance(piece, LineString) or piece.length == 0:
                continue
            #  The intersection can reverse a piece, so put each piece back in the direction of the edge.
            if line.project(shapely.Point(piece.coords[0])) > line.project(shapely.Point(piece.coords[-1])):
                piece = piece.reverse()
            piece_start = node_at(piece.coords[0], u, v)
            piece_end = node_at(piece.coords[-1], u, v)
            if piece_start != piece_end:
                clipped.add_edge(piece_start, piece_end, **{**data, "geometry": piece, "length": piece.length})

    components = nx.weakly_connected_components(clipped) if clipped.is_directed() else nx.connected_components(clipped)
    return clipped.subgraph(max(components, key=len)).copy()


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


def route_line(graph, route_nodes):
    """Join the edges of a route into one line.

    Between two nodes, the route uses the shortest of the parallel edges in graph.
    """
    coords = []
    for u, v in zip(route_nodes[:-1], route_nodes[1:]):
        key = min(graph[u][v], key=lambda key: graph[u][v][key]["length"])
        line_coords = list(edge_line(graph, u, v, graph[u][v][key]).coords)
        coords.extend(line_coords if not coords else line_coords[1:])
    return LineString(coords)


def write_gpx(graph, route, name, filename):
    """Write the route to a GPX 1.1 file, as one track."""
    route_lonlat, _ = ox.projection.project_geometry(route, crs=graph.graph["crs"], to_latlong=True)
    points = "\n".join(f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}"/>' for lon, lat in route_lonlat.coords)
    with open(filename, "w", encoding="utf-8") as gpx_file:
        gpx_file.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="straight-line" xmlns="http://www.topografix.com/GPX/1/1">\n'
            f"  <trk>\n    <name>{xml.sax.saxutils.escape(name)}</name>\n    <trkseg>\n{points}\n    </trkseg>\n  </trk>\n"
            "</gpx>\n"
        )


def draw_result(graph, area, area_name, endpoint_xy, straight_line, max_deviation, route, filename):
    """Draw the area, the network, the corridor, the straight line and the route to a PNG.

    The bottom left corner shows the area name and the max deviation.
    """
    west, south, east, north = area.bounds
    width = east - west
    height = north - south
    scale = 12 / max(width, height)
    fig, ax = plt.subplots(figsize=(max(width * scale, 4), max(height * scale, 4)), layout="constrained")
    ax.set_aspect("equal")
    ax.set_axis_off()

    #  A directed graph has one edge per direction of a two-way street. Draw each street once,
    #  because two anti-aliased copies of a line look thicker than one.
    edge_lines = []
    drawn_streets = set()
    for u, v, data in graph.edges(data=True):
        street = (frozenset((u, v)), round(data["length"], 1))
        if street not in drawn_streets:
            drawn_streets.add(street)
            edge_lines.append(np.asarray(edge_line(graph, u, v, data).coords))
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

    ax.text(
        0.01,
        0.01,
        f"{area_name}\nMax deviation: {max_deviation:.1f} m",
        transform=ax.transAxes,
        fontsize=14,
        ha="left",
        va="bottom",
    )

    ax.set_xlim(west - width * 0.02, east + width * 0.02)
    ax.set_ylim(south - height * 0.02, north + height * 0.02)
    fig.savefig(filename, dpi=300)
    plt.close(fig)

    if sys.platform == "darwin":
        subprocess.run(["open", filename], check=False)
