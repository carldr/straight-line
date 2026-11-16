# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What it does

The script finds the route with the smallest deviation from a straight line across an OpenStreetMap area, on public ways for `walk` or `bike`.
It writes `<activity>-<name>.png` and `<activity>-<name>.gpx`. `README.md` describes the method for users.

## Environment and running

- Run `uv sync` once. The environment is in `.venv/`, with osmnx 2.x.
- Put the split WGS84 water polygons in `water-polygons-split-4326/` at the repository root. git ignores this directory.
- Run `uv run python run.py <area> <walk|bike>`. The area is a place name, which `search_boundaries` looks up on Nominatim, or an OSM relation id.
  A name with several matches asks for a choice on a terminal, and exits otherwise. Use the relation id, such as `172987`, in non-interactive runs.

The repository has no tests, linter or build step. Liverpool (relation 172987) is the usual check: walk gives 92.3 m, with both route ends on the boundary.
osmnx writes its HTTP cache to `cache/`, which git ignores.

## Code layout

- `straightline.py`: Nominatim search, Overpass settings, area and graph loading, bicycle one-way rules, PNG and GPX output.
- `run.py`: the search, the worker processes and the command line.

## How the search works

1. `load_area` gets the relation from Overpass with `rel(<id>); out geom;`, builds it with `polygonize`, removes the water polygons, and keeps the largest polygon.
2. `load_graph` projects the graph to UTM, so all search geometry is in metres. Walk is an undirected `MultiGraph`. Bike is a directed `MultiDiGraph`, cut to its largest strongly connected component.
3. `clip_graph_to_area` cuts every edge at the area boundary and adds a `boundary_crossing` node at each cut.
   `build_search_network` turns the graph into numpy arrays (`SearchNetwork`). Endpoints are nodes within 10 m of the area's exterior ring, which includes every crossing node, one per 25 m of ring.
4. `area_split` gives the area on each side of a line in O(1) per pair, from shoelace prefix sums along the ring. It is exact only for a line inside the area, and it ignores holes.
5. `search_from_endpoint` drops pairs below `--min-split` and pairs whose line leaves `area_buffered`.
6. `pair_deviation` gets the edges within the current best deviation from an STRtree. It then finds the exact smallest deviation by binary search over the edges sorted by deviation, with a BFS reachability check.
7. The best deviation so far is a `multiprocessing.Value` that all workers share. It prunes the corridor of every later pair.
8. `main` takes the shortest route by length inside the winning corridor.

With more than `MAX_COARSE_ENDPOINTS` endpoints, `main` searches a coarse subset first, then the fine endpoints near the best coarse pair.

## Points to know before you change code

- An edge's deviation is the largest distance of its geometry vertices from the segment. A polyline is furthest from a segment at a vertex, so no interpolation is needed.
- The pool uses the `spawn` start method. Worker state goes in through `init_worker`, so every worker function must be at module level.
- osmnx ignores `oneway:bicycle` and `cycleway=opposite*`. `apply_bicycle_one_way` applies them to the unsimplified graph, before `simplify_graph`.
- `draw_result` runs `open` on macOS only.
