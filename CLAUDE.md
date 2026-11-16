# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What it does

The script finds the straightest route across an OpenStreetMap area on public ways for one activity, such as `walk` or `bike`.
It renders the result as a PNG named `<activity>-<filename>`, for example `walk-liverpool.png`.

## Environment and running

- Activate the conda environment from `README.md`: `conda activate ox`.
- Put the split WGS84 water polygons in `water-polygons-split-4326/` at the repository root. `straightline.setup` reads `water-polygons-split-4326/water_polygons.shp`.
- Set `relation`, `filename` and `activity` in `run.py` `main`. The commented blocks there are earlier runs.
- Run `python run.py`.

The repository has no tests, linter or build step.
osmnx writes its HTTP cache to `cache/`, which git ignores.

## Code layout

- `straightline.py`: `setup` builds the graph and the candidate end nodes. `draw_paths` renders the PNG.
- `run.py`: the route search and the hard-coded run settings.

## How the search works

1. `setup` loads the relation with `ox.geocode_to_gdf`. It keeps only the largest polygon of a MultiPolygon.
2. `setup` subtracts the water polygons from the boundary, so routes do not start or end in the sea.
3. `setup` builds the graph for the activity and keeps only the largest strongly connected component.
4. `setup` snaps each boundary coordinate to its nearest graph node. It keeps a node if the node is outside the boundary or within 5 m of the boundary coordinate.
5. The minimum route length is half the diagonal of the boundary's bounding box. `do_start_node` skips shorter node pairs.
6. `do_find` gives each boundary node to a `multiprocessing.Pool` of 12 processes. Each job gets a pickled copy of the whole graph, so memory use is high for large areas.
7. `do_start_node` checks each pair once (`s_idx > e_idx` is skipped). This assumes that routes are bidirectional.
8. `do_node` takes the k shortest paths (k=3) for a pair. It scores each path by its maximum distance from the straight line between the two end nodes.
9. If two paths have scores within 0.000001, `do_node` prefers the longer path.
10. `do_find` runs `do_node` again with k=100 on the best pair, then calls `draw_paths`.

In the PNG, red lines are the best path per pair. Orange lines are the 100 candidates for the best pair. Green is the result. Purple is a path with the same score but a shorter length.

## Points to know before you change code

- The variation score is in degrees, not metres. `do_find` converts it with `/ 0.00001 / 1.1` for the final message only.
- `west, north, east, south = boundary.bounds` uses wrong names. Shapely returns `(minx, miny, maxx, maxy)`, so `north` is the minimum latitude. `draw_paths` sets the axis limits from these names, so a rename must change both.
- `do_find` ends with `os._exit(0)`.
- `draw_paths` runs `open <file>` at the end, which works only on macOS. It saves at 2000 dpi.
- The code uses the osmnx 1.x API: `ox.utils_graph`, `ox.distance.great_circle_vec` and `get_route_edge_attributes`. osmnx 2.0 removed these.
- `README.md` says 16 processes. `run.py` uses 12.
