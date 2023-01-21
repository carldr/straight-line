import os
import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
import osmnx as ox
import networkx as nx
from shapely.geometry import Polygon, Point

ox.settings.use_cache = True
ox.settings.log_console = True


#relation = "R167060"
#filename = "shropshire.png"

#relation = "R6795460"
#filename = "whitchurch.png"

#relation = "R4581086"
#filename = "shrewsbury.png"

relation = "R146656"
filename = "manchester.png"
activity = "walk"

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



#   Get coast of the country/continent
#   Intersect that with the boundary
#   Find points which are outside the boundary, or within, say, 10m of it.




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

  #  Draw the boundary
  #
  patch = patches.PathPatch( Path( list( gdf.geometry[0].exterior.coords ) ), color = "black", lw = 0.5, fill = False )
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
    node_size = 0
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
      fill = False, color = "blue"
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
    route_length = sum( ox.utils_graph.get_route_edge_attributes( graph, straightest_path, "length") )
    straight_line_distance = ox.distance.great_circle_vec(
      graph.nodes[ straightest_path[0] ][ 'y' ],
      graph.nodes[ straightest_path[0] ][ 'x' ], 
      graph.nodes[ straightest_path[-1] ][ 'y' ],
      graph.nodes[ straightest_path[-1] ][ 'x' ]
    )

    print( "BEST : {}%% off perfect".format( straightest_path_extra_length_percent ) )
    print( "Route : {}m".format( route_length ) )
    print( "Crow : {}m".format( straight_line_distance ) )


#################################################################

#  Get the GeoDataFrame
gdf = ox.geocode_to_gdf( relation, by_osmid = True )

#  Extract the boundary
boundary = Polygon( list( gdf.geometry[0].exterior.coords ) )

#  Build a graph of cycleable routes, "all_private", "all", "bike", "drive", "drive_service", "walk"
graph = ox.graph_from_polygon(
  boundary,
  network_type = activity,
  truncate_by_edge = True
)  

#  Show how many coords we have in the boundary
coords = gdf.geometry[0].exterior.coords
print( "{} coords in boundary".format( len( coords ) ) )

#  For of those, find the closest node to each.
nodes = ox.nearest_nodes( graph, [ coord[0] for coord in coords ], [ coord[1] for coord in coords ] )
print( "{} nodes in boundary".format( len( nodes ) ) )

#  Get a unique list of nodes that are close to the boundary, this should be a lot fewer than the number of coords
unique_nodes = list( set( nodes ) )
unique_nodes.sort()
print( "{} unique nodes near boundary".format( len( unique_nodes ) ) )

#  Actually, we just need the nodes which are outside the boundary, since we want to start and end outside (this breaks on the coast!)
outside_nodes = []
for unique_node in unique_nodes:
  node_loc = graph.nodes[ unique_node ]
  point = Point( node_loc[ "x" ], node_loc[ "y" ] )
  if not point.within( boundary ):
    outside_nodes.append( unique_node )
print( "{} nodes outside boundary".format( len( outside_nodes ) ) )

#  Find the minimum distance we're going to allow for candidate routes - a third of the diagonal of the map
west, north, east, south = boundary.bounds
minimum_distance = ox.distance.great_circle_vec( north, west, south, east ) / 3.0
print( "Minimum permitted distance : {}m".format( minimum_distance ) )

##############################################################

a = 0
paths = []

straightest_path_extra_length_percent = None
straightest_path = None

for s_idx, start_node in enumerate( outside_nodes ):
  for e_idx, end_node in enumerate( outside_nodes ):
    start_node_loc = graph.nodes[ start_node ]
    start_point = Point( start_node_loc[ "x" ], start_node_loc[ "y" ] )

    end_node_loc = graph.nodes[ end_node ]
    end_point = Point( end_node_loc[ "x" ], end_node_loc[ "y" ] )

    if start_node == end_node or s_idx > e_idx:
      continue

    a = a + 1

    # y = lat, x = long
    straight_line_distance = ox.distance.great_circle_vec(
      graph.nodes[ start_node ][ 'y' ],
      graph.nodes[ start_node ][ 'x' ], 
      graph.nodes[ end_node ][ 'y' ],
      graph.nodes[ end_node ][ 'x' ]
    )

    if straight_line_distance < minimum_distance:
      continue

    path = ox.shortest_path( graph, start_node, end_node, weight = "length" )
    if path:
      route_length = sum( ox.utils_graph.get_route_edge_attributes( graph, path, "length") )

      difference = ( route_length - straight_line_distance )
      percentage = ( route_length - straight_line_distance ) / route_length * 100.0

      print(
        "{} to {} = straight: {}, length: {} = {}m, {}%".format(
          start_node, end_node,
          straight_line_distance, route_length,
          difference, percentage
         )
      )

      if straightest_path == None or percentage < straightest_path_extra_length_percent:
        print( "  BEST YET!" )
        straightest_path = path
        straightest_path_extra_length_percent = percentage

      paths.append( path )

    if a == 120000:
      draw_paths()
      os._exit( 0 )

draw_paths()