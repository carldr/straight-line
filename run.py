import os
import random
import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
import osmnx as ox
import networkx as nx
from shapely import difference, distance
from shapely.geometry import MultiPolygon, Polygon, Point, LineString
import geopandas as gpd

ox.settings.use_cache = True
ox.settings.log_console = True


#relation = "R167060"
#filename = "shropshire.png"

#relation = "R6795460"
#filename = "whitchurch.png"
#activity = "bike"

relation = "R4581086"
filename = "shrewsbury.png"
activity = "walk"

#relation = "R146656"
#filename = "manchester.png"
#activity = "walk"

#relation = "R1410720"
#filename = "crewe.png"
#activity = "walk"

#relation = "R163183"
#filename = "stoke.png"

#relation = "R42602"
#filename = "florence.png"

#relation = "R51701"
#filename = "switzerland.png"

#relation = "R214665"
#filename = "kazakhstan.png"
#activity = "walk"

#relation = "R172987"
#filename = "liverpool.png"
#activity = "bike"

#relation = "R65606"
#filename = "greater-london.png"
#activity = "walk"

#filename = "cardiff.png"
#relation = "R1625787"
#activity = "walk"

def add_edge_distances( graph, start_node, end_node ):
  first_loc = graph.nodes[ start_node ]
  last_loc = graph.nodes[ end_node ]
  line = LineString( [ Point( first_loc[ "x" ], last_loc[ "y" ] ), Point( last_loc[ "x" ], last_loc[ "y" ] ) ] )

  dists = {}

  for edge in graph.edges( keys = True ):
    edge_line = LineString( [ Point( graph.nodes[ edge[0] ][ 'x' ], graph.nodes[ edge[0] ][ 'y' ] ), Point( graph.nodes[ edge[1] ][ 'x' ], graph.nodes[ edge[1] ][ 'y' ] ) ] )

    #  Split the edge into 5m segments, and work out how far each is from the ideal.  Summing that amount
    #  gives a measure of how good or bad an edge is in total.
    dist = 0.0
    for point in ox.utils_geo.interpolate_points( edge_line, 5.0 ):
      #straight_line_distance = ox.distance.great_circle_vec(
      #  graph.nodes[ straightest_path[0] ][ 'y' ],
      #  graph.nodes[ straightest_path[0] ][ 'x' ], 
      #  graph.nodes[ straightest_path[-1] ][ 'y' ],
      #  graph.nodes[ straightest_path[-1] ][ 'x' ]
      #)

      #  This is using the units of lat/long, so the answer isn't in metres.
      #  The distances are so small we don't need to do the great circle distance
      #  We just can't take these numbers and use them to work out the largest deviation
      #  We could work out the real metre ditances when we draw the map though.
      point_dist = distance( line, Point( point[0], point[1] ) )
      if point_dist < 0.0:
        print( "Distance less than 0" )
        os._exit( 1 )

      dist += point_dist

    # midpoint = edge_line.interpolate( 0.5, normalized = True )
    #dists[ edge ] = distance( line, midpoint )

    dists[ edge ] = dist

  nx.set_edge_attributes( graph, dists, name = "from_ideal" )


def draw_paths():
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
  if len( paths ) == 1:
    fig, ax = ox.plot_graph_route(
      graph,
      path,
      ax = ax,
      show = False,
      close = False,
      color = "yellow",
      route_linewidth = 1,
      orig_dest_size = 5,
      dpi = 600
    )

  if len( paths ) > 1:
    fig, ax = ox.plot_graph_routes(
      graph,
      paths,
      ax = ax,
      show = False,
      close = False,
      route_colors = "red",
      route_linewidths = 1,
      orig_dest_size = 5,
    )

  #  Draw the straightest
  #
  if straightest_path:
    fig, ax = ox.plot_graph_route(
      graph,
      shortest_path,
      ax = ax,
      route_color = "orange",
      show = False,
      close = False,
      route_linewidth = 2,
      orig_dest_size = 20,
    )

    fig, ax = ox.plot_graph_route(
      graph,
      straightest_path,
      ax = ax,
      route_color = "green",
      show = False,
      close = False,
      route_linewidth = 2,
      orig_dest_size = 20,
    )

    first_loc = graph.nodes[ straightest_path[0] ]
    last_loc = graph.nodes[ straightest_path[-1] ]
  
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

  fig.savefig( activity + "-" + filename, dpi = 1600 )

  os.system( "open {}".format( activity + "-" + filename ) )

  if straightest_path:
    # route_length = sum( ox.utils_graph.get_route_edge_attributes( graph, straightest_path, "from_ideal") )
    #straight_line_distance = ox.distance.great_circle_vec(
    #  graph.nodes[ straightest_path[0] ][ 'y' ],
    #  graph.nodes[ straightest_path[0] ][ 'x' ], 
    #  graph.nodes[ straightest_path[-1] ][ 'y' ],
    #  graph.nodes[ straightest_path[-1] ][ 'x' ]
    #)

    print()
    print( "Straightest path route length : {}".format( straight_path_route_length ) )
    print( "Straightest path variation : {}".format( straightest_path_variation ) )
    print( "Shortest path route length : {}".format( shortest_path_route_length ) )

#################################################################

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
coords = boundary_gdf.geometry[0].exterior.coords
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
    print( "{}: outside boundary".format( i ) )
    boundary_nodes.append( street_node )
    continue

  if dist < 5.0: # Less than 5m?
    boundary_nodes.append( street_node )

print( "{} nodes outside or near boundary".format( len( boundary_nodes ) ) )

#  Get a unique list of nodes that are close to the boundary, this should be a lot fewer than the number of coords
boundary_nodes = list( set( boundary_nodes ) )
boundary_nodes.sort()
print( "{} unique nodes outside or near boundary".format( len( boundary_nodes ) ) )

#  Find the minimum distance we're going to allow for candidate routes - a third of the diagonal of the map
minimum_distance = ox.distance.great_circle_vec( north, west, south, east ) / 3.0
print( "Minimum permitted distance : {}m".format( minimum_distance ) )

##############################################################

a = 0
paths = []

straightest_path_route_length = None
straightest_path_variation = None
straightest_path = None
shortest_path = None
shortest_path_route_length = None



for s_idx, start_node in enumerate( boundary_nodes ):
  for e_idx, end_node in enumerate( boundary_nodes ):
    if start_node == end_node or s_idx > e_idx:
      continue

    print( "{} to {}".format( start_node, end_node ) )

    # y = lat, x = long
    straight_line_distance = ox.distance.great_circle_vec(
      graph.nodes[ start_node ][ 'y' ],
      graph.nodes[ start_node ][ 'x' ], 
      graph.nodes[ end_node ][ 'y' ],
      graph.nodes[ end_node ][ 'x' ]
    )
    
    if straight_line_distance < minimum_distance:
      print( "      Great circle distance below minimum" )
      continue

    a = a + 1

    #path = list( ox.k_shortest_paths( graph, start_node, end_node, 100, weight = "from_ideal" ) )
    short_path = ox.shortest_path( graph, start_node, end_node, weight = "length" )
    if short_path:
      #path = path[0]
      short_path_route_length = sum( ox.utils_graph.get_route_edge_attributes( graph, short_path, "length") )

      print( "      route_length: {}, straight line distance: {}".format( short_path_route_length, straight_line_distance ) )

      if short_path_route_length > straight_line_distance * 1.3:
        print( "      SKIP > 30%" )
        continue

      if ( straightest_path != None and short_path_route_length > shortest_path_route_length * 1.3 ): 
        print( "      SKIP: Shortest path 30% over current best shortest route length" )
        continue

      ## TODO: Add edge attributes which measure how far an edge is from the ideal line, and use that attribute for routing.
      ##       It's slow.
      add_edge_distances( graph, start_node, end_node )

      straight_path = ox.shortest_path( graph, start_node, end_node, weight = "from_ideal" )
      variation = sum( ox.utils_graph.get_route_edge_attributes( graph, straight_path, "from_ideal" ) )
      straight_path_route_length = sum( ox.utils_graph.get_route_edge_attributes( graph, straight_path, "length" ) )

      print( "      variation {} over {}".format( variation, straight_path_route_length ) )

      # Variation per route length
      if straightest_path == None or variation / short_path_route_length < straightest_path_variation / short_path_route_length:
        print( "  BEST YET!" )
        shortest_path = short_path
        shortest_path_route_length = short_path_route_length
        straightest_path = straight_path
        straightest_path_variation = variation
        straightest_path_route_length = straight_path_route_length

      paths.append( straight_path )

    #if a >= 50:
    #  draw_paths()
    #  os._exit( 0 )

draw_paths()