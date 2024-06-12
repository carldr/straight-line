import os
import osmnx as ox
from shapely.geometry import MultiPolygon, Polygon, Point
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
from shapely import difference

def setup( relation, activity ):
  #  Get the GeoDataFrame
  gdf = ox.geocode_to_gdf( relation, by_osmid = True )

  #  Some relations have multiple areas, like Cardiff.  For now, we're juat interested in the largest one
  largest_poly = None
  largest_poly_area = None
  if type( gdf.geometry[0] ) == MultiPolygon:
    for poly in list( gdf.geometry[0].geoms ):
      if largest_poly_area == None or poly.area > largest_poly_area:
        largest_poly_area = poly.area
        largest_poly = poly
  else:
    largest_poly = gdf.geometry[0]

  #  Extract the boundary
  boundary = Polygon( list( largest_poly.exterior.coords ) )
  west, north, east, south = boundary.bounds

  #  Load the coastline
  coastlines = gpd.read_file( 'water-polygons-split-4326/water_polygons.shp', bbox=( west, north, east, south ) )
  for i in range( len( coastlines ) ):
    water = coastlines.loc[ i, 'geometry' ]

    boundary = difference( boundary, water )

  boundary_gdf = gpd.GeoDataFrame( index=[0], crs='epsg:4326', geometry=[ boundary ] )
  west, north, east, south = boundary.bounds

  #  Build a graph of cycleable routes, "all_private", "all", "bike", "drive", "drive_service", "walk"
  graph = ox.graph_from_polygon(
    boundary,
    network_type = activity,
    truncate_by_edge = True,
    retain_all = True
  )

  #  Get a strongly connected graph, see https://stackoverflow.com/questions/63690631/osmnx-shortest-path-how-to-skip-node-if-not-reachable-and-take-the-next-neares
  #  This fixes a number of nodes which otherwise couldn't be routed to/from
  #  TODO: Oh, I wonder if others are because they are one-way?
  graph = ox.utils_graph.get_largest_component( graph, strongly=True )

  #  Show how many coords we have in the boundary
  coords = largest_poly.exterior.coords
  print( "{} coords in boundary".format( len( coords ) ) )

  #  For of those, find the closest node to each.
  nodes, dists = ox.nearest_nodes( graph, [ coord[0] for coord in coords ], [ coord[1] for coord in coords ], return_dist = True )
  print( "{} nodes in boundary".format( len( nodes ) ) )

  boundary_nodes = []
  for i in range(len(nodes)):
    street_node = nodes[ i ]
    dist = dists[ i ]

    node_loc = graph.nodes[ street_node ]
    point = Point( node_loc[ "x" ], node_loc[ "y" ] )

    #  If the node is outside the boundary, we definitely want it
    if not point.within( boundary ):
      print( "{}: outside boundary (checking {} nodes)".format( i, len(nodes) ) )
      boundary_nodes.append( street_node )
      continue

    if dist < 5.0: # Less than 5m?
      boundary_nodes.append( street_node )

  print( "{} nodes outside or near boundary".format( len( boundary_nodes ) ) )

  #  Get a unique list of nodes that are close to the boundary, this should be a lot fewer than the number of coords
  boundary_nodes = list( set( boundary_nodes ) )
  boundary_nodes.sort()
  print( "{} unique nodes outside or near boundary".format( len( boundary_nodes ) ) )

  #  Find the minimum distance we're going to allow for candidate routes - a quarter of the diagonal of the map
  minimum_distance = ox.distance.great_circle_vec( north, west, south, east ) / 4.0
  print( "Minimum permitted distance : {}m".format( minimum_distance ) )


  return graph, boundary_nodes, minimum_distance, boundary, boundary_gdf










def draw_paths( graph, boundary, boundary_gdf, paths, filename ):
  print( "{} paths to draw".format( len( paths ) ) )

  #  Set up the figure
  fig, ax = plt.subplots( figsize = ( 8, 8 ), layout = "constrained" )
  ax.set_facecolor( "white" )

  #  Set up the axes
  #
  #  Mostly from _config_ax : https://github.com/gboeing/osmnx/blob/c034e2bf670bd8e9e46c5605bc989a7d916d58f3/osmnx/plot.py#L769 
  ax.margins( 0 )
  ax.get_xaxis().set_visible( False )
  ax.get_yaxis().set_visible( False )
  ax.tick_params( which = "both", direction = "in" )
  _ = [s.set_visible(False) for s in ax.spines.values()]

  #  Draw the boundary (we could draw the real boundary, before coastal erosion?)
  #
  patch = patches.PathPatch( Path( list( boundary_gdf.geometry[0].exterior.coords ) ), color = "black", lw = 0.5, fill = False )
  ax.add_patch( patch )

  #  Draw the roads
  #
  fig, ax = ox.plot_graph(
    graph,
    ax = ax,
    show = False,
    close = False,
    edge_color = "black",
    edge_linewidth = 0.1,
    node_size = 1,
    node_color = "black"
  )

  #  Draw the routes
  #
  for idx, path in enumerate( paths ):
    print( "Drawing path {}/{}".format( idx+1, len( paths ) ) )

    fig, ax = ox.plot_graph_route(
      graph,
      path[ "path" ],
      ax = ax,
      show = False,
      close = False,
      route_alpha = 1.0, 
      route_color = path[ "colour" ],
      route_linewidth = path[ "width" ],
      orig_dest_size = 5
    )

  for path in paths:
    if "line" in path.keys() and path[ "line" ] == True:
      first_loc = graph.nodes[ path[ "path" ][ 0 ] ]
      last_loc = graph.nodes[ path[ "path" ][ -1 ] ]
    
      patch = patches.Arrow(
        first_loc[ 'x' ],
        first_loc[ 'y' ],
        last_loc[ 'x' ] - first_loc[ 'x' ],
        last_loc[ 'y' ] - first_loc[ 'y' ],
        linewidth = 0.4,
        width = 0.0001,
        fill = False,
        color = "blue"
      )
      ax.add_patch( patch )

  #  Reset the bounds
  #
  west, north, east, south = boundary.bounds
  ax.set_xlim( west - 0.005, east + 0.005 )
  ax.set_ylim( north - 0.005, south + 0.005 )

  fig.savefig( filename, dpi = 1600 )

  print( "Opening " + filename )
  os.system( "open {}".format( filename ) )
