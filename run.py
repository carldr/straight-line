from time import sleep
import sys
import os
import osmnx as ox
import networkx as nx
from shapely import distance
from shapely.geometry import Point, LineString
import multiprocessing

ox.settings.use_cache = True
ox.settings.log_console = True

import straightline

def do_node( graph, s_idx, start_node, end_node, count = 3 ):
  this_end_node_straight_path = None
  this_end_node_variation = None
  this_end_node_route_length = None
  
  paths = []
  variations = []
  lengths = []

  #short_path = ox.shortest_path( graph, start_node, end_node, weight = "length" )
 
  #  TODO: Can this method return distances?
  for short_path in ox.k_shortest_paths( graph, start_node, end_node, count, weight = "length" ):
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

    route_length = sum( ox.utils_graph.get_route_edge_attributes( graph, short_path, "length" ) )

    print( "Route {}, Worst variation : {}, distance : {}m".format( s_idx, absolute_max_dist, route_length ) )

    if this_end_node_straight_path == None or absolute_max_dist < this_end_node_variation:
      print( "Route {}, BEST THIS NODE".format( s_idx ) )
      this_end_node_straight_path = short_path
      this_end_node_variation = absolute_max_dist
      this_end_node_route_length = route_length

    paths.append( short_path )
    lengths.append( route_length )
    variations.append( absolute_max_dist )


  #
  #  Now, for all routes we've seen, if the ending variation is less than about 10cm metre (0.000001 longitude at equator) then
  #  prefer distance  
  #
  additional_path = None

  #
  #  TODO: k_shortest_paths returns paths in distance order, so we can do this in the loop above
  #

  for i in range(len(paths)):
    if this_end_node_variation - variations[i] > 0.000001:
      continue

    if lengths[ i ] < this_end_node_route_length:
      print( "Route {}, BEST THIS NODE ON LENGTH, picking longer path".format( s_idx ) )
      print( "Route {}, Old: variation = {}, length = {}".format( s_idx, this_end_node_variation, this_end_node_route_length ) )
      print( "Route {}, New: variation = {}, length = {}".format( s_idx, variations[ i ], lengths[ i ] ) )

      additional_path = this_end_node_straight_path

      # TODO: See how zip() works
      this_end_node_straight_path = paths[ i ]
      this_end_node_variation = variations[ i ]
      this_end_node_route_length = lengths[ i ]

  return this_end_node_straight_path, this_end_node_variation, this_end_node_route_length, paths, additional_path



def do_start_node( deets ):
  graph, s_idx, start_node, minimum_distance, boundary_nodes = deets

  print( "Route {}/{}".format(  s_idx, len( boundary_nodes ) ) )

  paths = []
  straightest_path_route_length = None
  straightest_path_variation = None
  straightest_path = None

  for e_idx, end_node in enumerate( boundary_nodes ):
    if start_node == end_node or s_idx > e_idx:
      continue

    print( "Route {}, {} to {}".format( s_idx, start_node, end_node ) )

    # y = lat, x = long
    straight_line_distance = ox.distance.great_circle_vec(
      graph.nodes[ start_node ][ 'y' ],
      graph.nodes[ start_node ][ 'x' ], 
      graph.nodes[ end_node ][ 'y' ],
      graph.nodes[ end_node ][ 'x' ]
    )
    
    if straight_line_distance < minimum_distance:
      print( "Route {}, Great circle distance below minimum".format( s_idx ) )
      continue

    this_end_node_straight_path, this_end_node_variation, this_end_node_route_length, _, _ = do_node( graph, s_idx, start_node, end_node )
    if this_end_node_straight_path == None:
      continue

    if straightest_path == None or this_end_node_variation < straightest_path_variation:
      print( "Route {}, BEST".format( s_idx ) )
      straightest_path = this_end_node_straight_path
      straightest_path_variation = this_end_node_variation
      straightest_path_route_length = this_end_node_route_length

    paths.append( { "path" : this_end_node_straight_path, "width" : 0.3, "colour" : "red" } )

  return {
    "paths" : paths,
    "straightest_path" : straightest_path,
    "straightest_path_route_length" : straightest_path_route_length,
    "straightest_path_variation" : straightest_path_variation
  }


def main( argv ):
  relation = "R167060"
  filename = "shropshire.png"
  activity = "bike"

  #relation = "R58437"
  #filename = "wales.png"
  #activity = "bike"

  #relation = "R6795460"
  #filename = "whitchurch.png"
  #activity = "bike"

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
  #activity = "walk"

  #relation = "R65606"
  #filename = "greater-london.png"
  #activity = "walk"

  #filename = "cardiff.png"
  #relation = "R1625787"
  #activity = "walk"

  graph, boundary_nodes, minimum_distance, boundary, boundary_gdf = straightline.setup( relation, activity )

  #################################################################



  ##############################################################



  pool = multiprocessing.Pool( processes = 16 )
  jobs = []
  for s_idx, start_node in enumerate( boundary_nodes ):
    jobs.append( ( graph, s_idx, start_node, minimum_distance, boundary_nodes ) )

  return_values = pool.map( do_start_node, jobs )
  pool.close()
  pool.join()


  paths = []
  straightest_path_variation = None
  straightest_path = None
  straightest_path_length = None

  for node in return_values:
    s_paths = node[ "paths" ]
    s_straightest_path = node[ "straightest_path" ]
    s_path_variation = node[ "straightest_path_variation" ]
    s_path_length = node[ "straightest_path_route_length" ]

    for s_path in s_paths:
      paths.append( s_path )

    if s_straightest_path == None:
      continue

    #  
    if straightest_path_variation == None or s_path_length < straightest_path_variation:
      print( "Route {}, RET BEST, path {}km, var {}".format( s_idx, s_path_length, s_path_variation ) )
      straightest_path = s_straightest_path
      straightest_path_variation = s_path_variation
      straightest_path_length = s_path_length

  print( "Route {}, Doing the best 1500 routes for the best found so far".format( s_idx ) )
  straightest_path, straightest_path_variation, straight_path_route_length, these_paths, additional_path = do_node(
    graph,
    s_idx,
    straightest_path[0],
    straightest_path[-1],
    1500
  )
  
  # Append the routes we tried for the best path found
  for path in these_paths:
    paths.append( { "path" : path, "width" : 0.2, "colour" : "orange" } )

  paths.append( { "path" : straightest_path, "colour" : "green", "width" : 1.0, "line" : True } )

  #  This was the path which was beaten on distance, with the same variation
  if additional_path:
    print( "PURPLE" )
    paths.append( { "path" : additional_path, "width" : 0.5, "colour" : "purple" } )


  straightline.draw_paths( graph, boundary, boundary_gdf, paths, activity + "-" + filename )

  os._exit( 0 )

if __name__ == '__main__':
  main( sys.argv )
