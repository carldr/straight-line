import os
import osmnx as ox
import networkx as nx
from shapely import distance
from shapely.geometry import Point, LineString
import multiprocessing

ox.settings.use_cache = True
ox.settings.log_console = True

import straightline

#relation = "R167060"
#filename = "shropshire.png"

relation = "R6795460"
filename = "whitchurch.png"
activity = "bike"

#relation = "R4581086"
#filename = "shrewsbury.png"
#activity = "walk"

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

graph, boundary_nodes, minimum_distance, boundary, boundary_gdf = straightline.setup( relation, activity )


"""
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
"""


#################################################################



##############################################################

paths = []
straightest_path_variation = None
straightest_path = None


def do_start_node( start_node, boundary_nodes ):
  paths = []
  straightest_path_variation = None
  straightest_path = None

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
      print( "  Great circle distance below minimum" )
      continue

    #short_path = ox.shortest_path( graph, start_node, end_node, weight = "length" )
    for short_path in ox.k_shortest_paths( graph, start_node, end_node, 3, weight = "length" ):
      #if short_path:
      straight_line = LineString( [ Point( graph.nodes[ start_node ][ 'x' ], graph.nodes[ start_node ][ 'y' ] ), Point( graph.nodes[ end_node ][ 'x' ], graph.nodes[ end_node ][ 'y' ] ) ] )

      # Turn path into linestring.
      points = []
      for node in short_path:
        points.append( Point( graph.nodes[ node ][ 'x' ], graph.nodes[ node ][ 'y' ] ) )
      path_linestring = LineString( points )

      absolute_max_dist = 0.0
      for point in ox.utils_geo.interpolate_points( path_linestring, 0.00005 ): #  Remember this isn't metres, 0.00001 ~ 1.1m
        point = Point( point[0], point[1] )
        nearest_point_on_straight_line = straight_line.interpolate( straight_line.project( point ) )
        dist = nearest_point_on_straight_line.distance( point ) #  Could use the great circle

        if dist > absolute_max_dist:
          absolute_max_dist = dist
          
      print( "  Worst distance : {}".format( absolute_max_dist ) )

      if straightest_path == None or absolute_max_dist < straightest_path_variation:
        print( "  BEST" )
        straightest_path = short_path
        straightest_path_variation = absolute_max_dist

      else:
        paths.append( { "path" : short_path, "width" : 0.3, "colour" : "red" } )

  return paths, straightest_path, straightest_path_variation


for s_idx, start_node in enumerate( boundary_nodes ):
  s_paths, s_straightest_path, s_path_variation = do_start_node( start_node, boundary_nodes )

  for s_path in s_paths:
    paths.append( s_path )

  if s_straightest_path == None:
    continue

  if straightest_path_variation == None or s_path_variation < straightest_path_variation:
    straightest_path = s_straightest_path
    straightest_path_variation = s_path_variation



paths.append( { "path" : straightest_path, "colour" : "green", "width" : 1.0, "line" : True } )

straightline.draw_paths( graph, boundary, boundary_gdf, paths, activity + "-" + filename )

os._exit( 0 )





"""
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
"""

#if a >= 50:
#  draw_paths()
#  os._exit( 0 )
