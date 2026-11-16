"""Find the straightest route across an OpenStreetMap area.

A route's deviation is the largest distance between the route and the straight line between its two ends.
The search finds the pair of boundary points, and the route between them, with the smallest deviation.
A pair is valid only if its straight line stays inside the area and cuts off at least min_split of the area.
"""

import argparse
import math
import multiprocessing
import os
import random
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass

import networkx as nx
import numpy as np
import shapely
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import breadth_first_order
from shapely.geometry import LineString

import straightline

#  Endpoint candidates are the nodes where a path crosses the area boundary,
#  and the nodes within this distance of the boundary, such as the ends and junctions of paths at the coast.
ENDPOINT_BOUNDARY_TOLERANCE_METRES = 10.0
#  The search keeps one endpoint candidate per this length of boundary.
FINE_ENDPOINT_SPACING_METRES = 25.0
#  The first pass uses at most this many endpoints, so that it checks at most about 2 million pairs.
MAX_COARSE_ENDPOINTS = 2000
#  A pair with no known deviation bound starts its corridor at this width, and doubles it until the ends connect.
INITIAL_CORRIDOR_WIDTH_METRES = 25.0

console = Console()


@dataclass
class SearchNetwork:
    """The path network and endpoint candidates, as arrays that the worker processes share."""

    node_xy: np.ndarray
    #  Edge e goes from node edge_u[e] to node edge_v[e], and back if edge_two_way[e].
    #  Its vertices are vertex_xy[vertex_offsets[e]:vertex_offsets[e + 1]].
    edge_u: np.ndarray
    edge_v: np.ndarray
    edge_two_way: np.ndarray
    vertex_xy: np.ndarray
    vertex_offsets: np.ndarray
    #  Endpoint candidates, in order along the area boundary.
    endpoint_nodes: np.ndarray
    endpoint_boundary_position: np.ndarray
    #  For each endpoint: its nearest point on the boundary, and the shoelace sum of the boundary up to that point.
    #  Both are relative to boundary_origin, which keeps the shoelace sums small enough for float precision.
    endpoint_boundary_xy: np.ndarray
    endpoint_shoelace_prefix: np.ndarray
    boundary_shoelace_total: float
    #  The area, enlarged by ENDPOINT_BOUNDARY_TOLERANCE_METRES so that a line can start at a node just off the boundary.
    area_buffered: shapely.Geometry
    min_split: float
    #  True if some edges are one-way, so that a pair must be checked in both directions.
    directed: bool
    #  A route that deviates further than this leaves the area, so the search stops widening the corridor.
    max_corridor_width: float


_network: SearchNetwork
_edge_tree: shapely.STRtree
_best_deviation: multiprocessing.Value


def init_worker(network, best_deviation):
    global _network, _edge_tree, _best_deviation
    _network = network
    _best_deviation = best_deviation
    shapely.prepare(network.area_buffered)
    vertex_counts = np.diff(network.vertex_offsets)
    edge_lines = shapely.linestrings(network.vertex_xy, indices=np.repeat(np.arange(len(vertex_counts)), vertex_counts))
    _edge_tree = shapely.STRtree(edge_lines)


def edge_max_deviations(edge_ids, line_start, line_end):
    """Return, for each edge, the largest distance of its vertices from the segment line_start to line_end.

    A polyline is furthest from a segment at one of its vertices, so the vertices give the exact value.
    """
    offsets = _network.vertex_offsets
    vertex_counts = offsets[edge_ids + 1] - offsets[edge_ids]
    output_starts = np.concatenate(([0], np.cumsum(vertex_counts)[:-1]))
    vertex_index = np.repeat(offsets[edge_ids] - output_starts, vertex_counts) + np.arange(vertex_counts.sum())
    points = _network.vertex_xy[vertex_index]

    direction = line_end - line_start
    t = np.clip(((points - line_start) @ direction) / (direction @ direction), 0.0, 1.0)
    nearest = line_start + t[:, None] * direction
    distances = np.hypot(points[:, 0] - nearest[:, 0], points[:, 1] - nearest[:, 1])
    return np.maximum.reduceat(distances, output_starts)


def edges_connect(edge_ids, start_node, end_node):
    """Return True if the edges give a route from start_node to end_node."""
    if len(edge_ids) == 0:
        return False
    edge_u = _network.edge_u[edge_ids]
    edge_v = _network.edge_v[edge_ids]
    two_way = _network.edge_two_way[edge_ids]
    sources = np.concatenate((edge_u, edge_v[two_way]))
    targets = np.concatenate((edge_v, edge_u[two_way]))
    nodes, local_index = np.unique(np.concatenate((sources, targets)), return_inverse=True)
    start_position = np.searchsorted(nodes, start_node)
    end_position = np.searchsorted(nodes, end_node)
    if start_position >= len(nodes) or nodes[start_position] != start_node:
        return False
    if end_position >= len(nodes) or nodes[end_position] != end_node:
        return False
    arc_count = len(sources)
    adjacency = coo_matrix(
        (np.ones(arc_count), (local_index[:arc_count], local_index[arc_count:])), shape=(len(nodes), len(nodes))
    ).tocsr()
    reached = breadth_first_order(adjacency, start_position, directed=True, return_predecessors=False)
    return bool(np.any(reached == end_position))


def corridor_edges(start_node, end_node, width):
    """Return the edges with every vertex within width of the straight line, and each edge's deviation."""
    line_start = _network.node_xy[start_node]
    line_end = _network.node_xy[end_node]
    line = shapely.linestrings([line_start, line_end])
    edge_ids = _edge_tree.query(line, predicate="dwithin", distance=width)
    if len(edge_ids) == 0:
        return edge_ids, np.empty(0)
    deviations = edge_max_deviations(edge_ids, line_start, line_end)
    inside = deviations <= width
    return edge_ids[inside], deviations[inside]


def pair_deviation(start_node, end_node, bound):
    """Return the smallest deviation of any route from start_node to end_node, or None if it is not below bound.

    The smallest deviation is the deviation of the edge that first joins the two ends,
    when the edges join in order of deviation.
    """
    if math.isinf(bound):
        width = INITIAL_CORRIDOR_WIDTH_METRES
        while True:
            edge_ids, deviations = corridor_edges(start_node, end_node, width)
            if edges_connect(edge_ids, start_node, end_node):
                break
            if width > _network.max_corridor_width:
                return None
            width *= 2
    else:
        edge_ids, deviations = corridor_edges(start_node, end_node, bound)
        below_bound = deviations < bound
        edge_ids = edge_ids[below_bound]
        deviations = deviations[below_bound]
        if not edges_connect(edge_ids, start_node, end_node):
            return None

    order = np.argsort(deviations, kind="stable")
    edge_ids = edge_ids[order]
    deviations = deviations[order]
    #  Find the smallest edge count that joins the two ends.
    low, high = 1, len(edge_ids)
    while low < high:
        middle = (low + high) // 2
        if edges_connect(edge_ids[:middle], start_node, end_node):
            high = middle
        else:
            low = middle + 1
    return float(deviations[low - 1])


def area_split(start_endpoint, end_endpoints):
    """Return, for each pair, the fraction of the area on the smaller side of the line between the two endpoints.

    The value is exact when the line stays inside the area. It ignores holes in the area.
    """
    boundary_xy = _network.endpoint_boundary_xy
    prefix = _network.endpoint_shoelace_prefix
    closing_term = (
        boundary_xy[end_endpoints, 0] * boundary_xy[start_endpoint, 1]
        - boundary_xy[end_endpoints, 1] * boundary_xy[start_endpoint, 0]
    )
    twice_area = prefix[end_endpoints] - prefix[start_endpoint] + closing_term
    fraction = np.abs(twice_area) / abs(_network.boundary_shoelace_total)
    return np.minimum(fraction, 1.0 - fraction)


def search_from_endpoint(task):
    """Check every valid pair of one start endpoint with a list of end endpoints, in both directions if directed.

    Returns the best (deviation, from endpoint, to endpoint) that improved the shared best, or None.
    """
    start_endpoint, end_endpoints = task
    end_endpoints = end_endpoints[end_endpoints != start_endpoint]
    end_endpoints = end_endpoints[area_split(start_endpoint, end_endpoints) >= _network.min_split]
    if len(end_endpoints) == 0:
        return None

    start_node = _network.endpoint_nodes[start_endpoint]
    end_nodes = _network.endpoint_nodes[end_endpoints]
    line_coords = np.stack(
        (np.broadcast_to(_network.node_xy[start_node], (len(end_nodes), 2)), _network.node_xy[end_nodes]), axis=1
    )
    lines_inside = shapely.contains(_network.area_buffered, shapely.linestrings(line_coords))

    best = None
    for end_endpoint, end_node in zip(end_endpoints[lines_inside], end_nodes[lines_inside]):
        directions = [(start_endpoint, int(end_endpoint), start_node, end_node)]
        if _network.directed:
            directions.append((int(end_endpoint), start_endpoint, end_node, start_node))
        for from_endpoint, to_endpoint, from_node, to_node in directions:
            deviation = pair_deviation(from_node, to_node, _best_deviation.value)
            if deviation is None:
                continue
            with _best_deviation.get_lock():
                if deviation < _best_deviation.value:
                    _best_deviation.value = deviation
            if best is None or deviation < best[0]:
                best = (deviation, from_endpoint, to_endpoint)
    return best


def build_search_network(graph, area, min_split):
    """Convert the graph and area into the arrays that the search uses."""
    nodes = list(graph.nodes)
    node_index = {node: index for index, node in enumerate(nodes)}
    node_xy = np.array([(graph.nodes[node]["x"], graph.nodes[node]["y"]) for node in nodes])

    edges = list(graph.edges(keys=True, data=True))
    edge_u = np.array([node_index[u] for u, _, _, _ in edges])
    edge_v = np.array([node_index[v] for _, v, _, _ in edges])
    edge_coords = [np.asarray(straightline.edge_line(graph, u, v, data).coords) for u, v, _, data in edges]
    vertex_offsets = np.concatenate(([0], np.cumsum([len(coords) for coords in edge_coords])))
    vertex_xy = np.concatenate(edge_coords)

    boundary = area.exterior
    boundary_origin = np.asarray(boundary.coords).mean(axis=0)
    boundary_xy = np.asarray(boundary.coords) - boundary_origin
    segment_cross = boundary_xy[:-1, 0] * boundary_xy[1:, 1] - boundary_xy[1:, 0] * boundary_xy[:-1, 1]
    shoelace_prefix = np.concatenate(([0.0], np.cumsum(segment_cross)))
    segment_ends = np.cumsum(np.hypot(*np.diff(boundary_xy, axis=0).T))

    #  Keep the node nearest the boundary in each FINE_ENDPOINT_SPACING_METRES of boundary.
    #  A crossing node lies on the boundary, so the distance test also keeps every crossing node.
    candidates = np.flatnonzero(shapely.distance(boundary, shapely.points(node_xy)) <= ENDPOINT_BOUNDARY_TOLERANCE_METRES)
    candidate_points = shapely.points(node_xy[candidates])
    position = shapely.line_locate_point(boundary, candidate_points)
    distance = shapely.distance(boundary, candidate_points)
    bucket = np.floor(position / FINE_ENDPOINT_SPACING_METRES).astype(int)
    order = np.lexsort((distance, bucket))
    _, first_in_bucket = np.unique(bucket[order], return_index=True)
    chosen = order[first_in_bucket]
    chosen = chosen[np.argsort(position[chosen])]

    endpoint_nodes = candidates[chosen]
    endpoint_position = position[chosen]
    endpoint_boundary_xy = (
        shapely.get_coordinates(shapely.line_interpolate_point(boundary, endpoint_position)) - boundary_origin
    )
    segment = np.clip(np.searchsorted(segment_ends, endpoint_position), 0, len(segment_cross) - 1)
    endpoint_shoelace_prefix = shoelace_prefix[segment] + (
        boundary_xy[segment, 0] * endpoint_boundary_xy[:, 1] - endpoint_boundary_xy[:, 0] * boundary_xy[segment, 1]
    )

    network = SearchNetwork(
        node_xy=node_xy,
        edge_u=edge_u,
        edge_v=edge_v,
        edge_two_way=np.full(len(edges), not graph.is_directed()),
        vertex_xy=vertex_xy,
        vertex_offsets=vertex_offsets,
        endpoint_nodes=endpoint_nodes,
        endpoint_boundary_position=endpoint_position,
        endpoint_boundary_xy=endpoint_boundary_xy,
        endpoint_shoelace_prefix=endpoint_shoelace_prefix,
        boundary_shoelace_total=float(shoelace_prefix[-1]),
        area_buffered=area.buffer(ENDPOINT_BOUNDARY_TOLERANCE_METRES),
        min_split=min_split,
        directed=graph.is_directed(),
        max_corridor_width=math.hypot(area.bounds[2] - area.bounds[0], area.bounds[3] - area.bounds[1]),
    )
    return network, nodes, edges


def coarse_endpoints(network, spacing):
    """Return one endpoint index per spacing of boundary, as a subset of the fine endpoints."""
    bucket = np.floor(network.endpoint_boundary_position / spacing).astype(int)
    _, first_in_bucket = np.unique(bucket, return_index=True)
    return first_in_bucket


def endpoints_near(network, endpoint, distance, boundary_length):
    """Return the endpoints within distance of an endpoint, measured along the boundary."""
    separation = np.abs(network.endpoint_boundary_position - network.endpoint_boundary_position[endpoint])
    separation = np.minimum(separation, boundary_length - separation)
    return np.flatnonzero(separation <= distance)


@contextmanager
def stage(running_text, done_text):
    """Show running_text with a spinner and the elapsed time while the block runs, then done_text with the time it took.

    The block receives a function that adds a detail text to the spinner line.
    On a console that is not a terminal, only the done_text line appears.
    """
    started = time.monotonic()
    if console.is_terminal:
        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console, transient=True
        ) as progress:
            task = progress.add_task(running_text, total=None)
            yield lambda detail: progress.update(task, description=f"{running_text}: {detail}")
    else:
        yield lambda detail: None
    console.print(f"[green]✓[/green] {done_text} [dim]{time.monotonic() - started:.1f} s[/dim]")


def run_search(pool, best_deviation, tasks, description):
    """Run the tasks in the pool with a progress bar, and return the best (deviation, start, end)."""
    random.Random(0).shuffle(tasks)
    best = None
    with Progress(
        TextColumn(description),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("start endpoints, best {task.fields[best]}"),
        TimeElapsedColumn(),
        TextColumn("<"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(description, total=len(tasks), best="-")
        for result in pool.imap_unordered(search_from_endpoint, tasks):
            if result is not None and (best is None or result[0] < best[0]):
                best = result
            best_text = "-" if math.isinf(best_deviation.value) else f"{best_deviation.value:.1f} m"
            progress.update(task, advance=1, best=best_text)
    return best


def choose_area(area_argument):
    """Return the (relation id, display name) for a place name or an OSM relation id."""
    if re.fullmatch(r"[Rr]?\d+", area_argument):
        relation_id = int(area_argument.upper().removeprefix("R"))
        with stage(f"Finding the name of relation {relation_id}", f"Found the name of relation {relation_id}"):
            return relation_id, straightline.fetch_relation_name(relation_id)

    with stage(f"Searching Nominatim for '{area_argument}'", f"Searched Nominatim for '{area_argument}'"):
        matches = straightline.search_boundaries(area_argument)
    if not matches:
        raise SystemExit(f"Nominatim found no boundary for '{area_argument}'.")
    if len(matches) == 1:
        return matches[0][0], matches[0][1]

    for number, (relation_id, display_name, kind) in enumerate(matches, start=1):
        console.print(f"{number}. {display_name}  [dim]({kind}, relation {relation_id})[/dim]", highlight=False)
    if not sys.stdin.isatty():
        raise SystemExit("Several boundaries match. Run again with the relation id of the one you want.")
    while True:
        try:
            answer = input("Choose an area [1]: ").strip() or "1"
        except EOFError:
            raise SystemExit("No area chosen.") from None
        if answer.isdigit() and 1 <= int(answer) <= len(matches):
            relation_id, display_name, _ = matches[int(answer) - 1]
            return relation_id, display_name


class HelpFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    """Keep the line breaks of the description, and show each option's default."""

    def _get_help_string(self, action):
        #  An option with no default value describes its default in its own help text.
        if action.default is None:
            return action.help
        return super()._get_help_string(action)


def file_name_part(text):
    """Return text in lower case, with each run of other characters than letters and digits changed to one hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=HelpFormatter)
    parser.add_argument("area", help="place name to search for, such as liverpool, or an OSM relation id, such as 172987")
    parser.add_argument("activity", choices=["walk", "bike"], help="walk uses every path both ways; bike obeys one-way streets")
    parser.add_argument(
        "--name", help="output name; the files are <activity>-<name>.png and .gpx (default: the first part of the area's name)"
    )
    parser.add_argument("--min-split", type=float, default=0.35, help="smallest fraction of the area on each side of the line")
    parser.add_argument("--processes", type=int, default=os.cpu_count(), help="number of search processes")
    args = parser.parse_args()
    relation_id, display_name = choose_area(args.area)
    name = args.name or file_name_part(display_name.split(",")[0])

    with stage(f"Loading the boundary of {display_name}", f"Loaded the boundary of {display_name}, relation {relation_id}"):
        relation_polygon = straightline.largest_polygon(straightline.fetch_relation_polygon(relation_id))
    with stage("Removing the sea", "Removed the sea"):
        area_lonlat = straightline.remove_sea(relation_polygon)
    with stage(f"Downloading the {args.activity} network", f"Downloaded the {args.activity} network") as report:
        graph = straightline.download_graph(area_lonlat, args.activity, report)
    with stage(f"Simplifying and projecting the {args.activity} network", f"Simplified and projected the {args.activity} network"):
        graph = straightline.prepare_graph(graph, args.activity)
        area = straightline.project_to_graph(area_lonlat, graph)
    with stage("Clipping the network to the boundary", "Clipped the network to the boundary"):
        graph = straightline.clip_graph_to_area(graph, area)
    console.print(f"  [dim]{len(graph.nodes)} nodes, {len(graph.edges)} edges, area {area.area / 1e6:.1f} km²[/dim]")

    with stage("Preparing the search", "Prepared the search"):
        network, nodes, edges = build_search_network(graph, area, args.min_split)
    endpoint_count = len(network.endpoint_nodes)
    boundary_length = area.exterior.length
    coarse_spacing = boundary_length / MAX_COARSE_ENDPOINTS
    console.print(f"  [dim]{endpoint_count} endpoint candidates on {boundary_length / 1000:.1f} km of boundary[/dim]")

    context = multiprocessing.get_context("spawn")
    best_deviation = context.Value("d", math.inf)
    with context.Pool(args.processes, initializer=init_worker, initargs=(network, best_deviation)) as pool:
        if endpoint_count > MAX_COARSE_ENDPOINTS:
            #  For a large area, check every pair of coarse endpoints, then every pair of fine endpoints near the best pair.
            coarse = coarse_endpoints(network, coarse_spacing)
            console.print(f"  [dim]First pass: {len(coarse)} endpoints, one per {coarse_spacing:.0f} m[/dim]")
            tasks = [(start, coarse[index + 1 :]) for index, start in enumerate(coarse)]
            _, start, end = run_search(pool, best_deviation, tasks, "First pass")
            near_start = endpoints_near(network, start, coarse_spacing, boundary_length)
            near_end = endpoints_near(network, end, coarse_spacing, boundary_length)
            tasks = [(start, near_end) for start in near_start]
            best = run_search(pool, best_deviation, tasks, "Second pass")
            if best is None:
                best = (best_deviation.value, start, end)
        else:
            tasks = [(start, np.arange(start + 1, endpoint_count)) for start in range(endpoint_count)]
            best = run_search(pool, best_deviation, tasks, "Search")

    if best is None:
        raise SystemExit("No pair of endpoints gives a valid straight line.")
    deviation, start_endpoint, end_endpoint = best
    start_node = network.endpoint_nodes[start_endpoint]
    end_node = network.endpoint_nodes[end_endpoint]

    #  Of the routes with the smallest deviation, take the shortest.
    with stage("Finding the shortest route in the corridor", "Found the shortest route in the corridor"):
        init_worker(network, best_deviation)
        corridor_ids, _ = corridor_edges(start_node, end_node, deviation * (1 + 1e-9))
        corridor_keys = {(edges[edge][0], edges[edge][1], edges[edge][2]) for edge in corridor_ids}
        corridor_graph = graph.edge_subgraph(corridor_keys)
        route_nodes = nx.shortest_path(corridor_graph, nodes[start_node], nodes[end_node], weight="length")
        route = straightline.route_line(corridor_graph, route_nodes)

    straight_line = LineString([network.node_xy[start_node], network.node_xy[end_node]])
    split = area_split(start_endpoint, np.array([end_endpoint]))[0]
    filename = f"{args.activity}-{name}"
    with stage(f"Writing {filename}.png", f"Wrote {filename}.png"):
        straightline.draw_result(
            graph,
            area,
            display_name,
            network.node_xy[network.endpoint_nodes],
            straight_line,
            deviation,
            route,
            f"{filename}.png",
        )
    with stage(f"Writing {filename}.gpx", f"Wrote {filename}.gpx"):
        straightline.write_gpx(graph, route, f"{args.activity} across {display_name}", f"{filename}.gpx")

    console.print()
    console.print(f"[bold]Max deviation: {deviation:.1f} m[/bold]")
    console.print(f"Straight line: {straight_line.length / 1000:.2f} km, route: {route.length / 1000:.2f} km")
    console.print(f"The line splits the area {split:.0%} / {1 - split:.0%}")


if __name__ == "__main__":
    main()
