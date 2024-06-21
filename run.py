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

def do_node( graph, s_idx, e_idx, start_node, end_node, count = 3 ):
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

    #  Get the absolute max variation distance
    absolute_max_dist = 0.0
    for point in ox.utils_geo.interpolate_points( path_linestring, 0.00005 ): #  Remember this isn't metres, 0.00001 ~ 1.1m
      point = Point( point[0], point[1] )
      nearest_point_on_straight_line = straight_line.interpolate( straight_line.project( point ) )
      dist = nearest_point_on_straight_line.distance( point ) #  Could use the great circle

      if dist > absolute_max_dist:
        absolute_max_dist = dist

    #  Get the length of the route
    route_length = sum( ox.utils_graph.get_route_edge_attributes( graph, short_path, "length" ) )

    print( "Route {}-{},      Current best variation : {}, this route variation: {} over distance : {}m".format( s_idx, e_idx, this_end_node_variation, absolute_max_dist, route_length ) )

    if this_end_node_straight_path == None or absolute_max_dist < this_end_node_variation:
      print( "Route {}-{},        Found best for this end node, old: {}, new: {}".format( s_idx, e_idx, this_end_node_variation, absolute_max_dist ) )
      this_end_node_straight_path = short_path
      this_end_node_variation = absolute_max_dist
      this_end_node_route_length = route_length

    paths.append( short_path )
    lengths.append( route_length )
    variations.append( absolute_max_dist )


  print( "Route {}-{}, 1/2: Best for this end node : variation {} over distance : {}m".format( s_idx, e_idx, this_end_node_variation, this_end_node_route_length ) )
  print( "Route {}-{},      Now checking similar variations for end node".format( s_idx, e_idx ) )

  #
  #
  additional_path = None

  #
  #  TODO: k_shortest_paths returns paths in distance order, so we can do this in the loop above
  #
  for i in range(len(paths)):
    #  Now, for all routes we've seen, if the ending variation is less than about 10cm metre (0.000001 longitude at equator) then
    #  prefer distance  
    if abs(this_end_node_variation - variations[i]) > 0.000001:
      continue

    #  If the length of this path is longer than the best one at the moment
    if lengths[ i ] > this_end_node_route_length:
      print( "Route {}-{},        Found similar variation, picking longer path".format( s_idx, e_idx ) )
      print( "Route {}-{},        New: variation = {}, length = {}".format( s_idx, e_idx, variations[ i ], lengths[ i ] ) )

      additional_path = this_end_node_straight_path

      # TODO: See how zip() works
      this_end_node_straight_path = paths[ i ]
      this_end_node_variation = variations[ i ]
      this_end_node_route_length = lengths[ i ]

  print( "Route {}-{}, 2/2: Settled on best for this end node : variation {} over distance : {}m".format( s_idx, e_idx, this_end_node_variation, this_end_node_route_length ) )

  return this_end_node_straight_path, this_end_node_variation, this_end_node_route_length, paths, additional_path



def do_start_node( deets ):
  graph, s_idx, start_node, minimum_distance, boundary_nodes = deets

  paths = []
  straightest_path_route_length = None
  straightest_path_variation = None
  straightest_path = None

  for e_idx, end_node in enumerate( boundary_nodes ):
    if start_node == end_node or s_idx > e_idx:
      continue

    print( "Route {}-{},      Tracing {} to {}".format( s_idx, e_idx, start_node, end_node ) )

    # y = lat, x = long
    straight_line_distance = ox.distance.great_circle_vec(
      graph.nodes[ start_node ][ 'y' ],
      graph.nodes[ start_node ][ 'x' ], 
      graph.nodes[ end_node ][ 'y' ],
      graph.nodes[ end_node ][ 'x' ]
    )
    
    if straight_line_distance < minimum_distance:
      print( "Route {}-{},        Great circle distance below minimum".format( s_idx, e_idx ) )
      continue

    this_end_node_straight_path, this_end_node_variation, this_end_node_route_length, _, _ = do_node( graph, s_idx, e_idx, start_node, end_node )
    if this_end_node_straight_path == None:
      continue

    if straightest_path == None or this_end_node_variation < straightest_path_variation:
      print( "Route {}-{},      Best variation so far, old: {}, new: {}".format( s_idx, e_idx, straightest_path_variation, this_end_node_variation ) )
      straightest_path = this_end_node_straight_path
      straightest_path_variation = this_end_node_variation
      straightest_path_route_length = this_end_node_route_length

    paths.append( { "path" : this_end_node_straight_path, "width" : 0.3, "colour" : "red" } )

  print( "Route {} ***: Best variation found: {} over length {}m".format( s_idx, straightest_path_variation, straightest_path_route_length ) )

  return {
    "paths" : paths,
    "straightest_path" : straightest_path,
    "straightest_path_route_length" : straightest_path_route_length,
    "straightest_path_variation" : straightest_path_variation
  }

def do_find( filename, relation, activity ):
  graph, boundary_nodes, minimum_distance, boundary, boundary_gdf = straightline.setup( relation, activity )

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

  print()
  print( "Considering {} results".format( len( return_values ) ) )

  for node in return_values:
    s_paths = node[ "paths" ]
    s_straightest_path = node[ "straightest_path" ]
    s_path_variation = node[ "straightest_path_variation" ]
    s_path_length = node[ "straightest_path_route_length" ]

    print( "  This path variation {} over distance {}m".format( s_path_variation, s_path_length ) )

    for s_path in s_paths:
      paths.append( s_path )

    if s_straightest_path == None:
      continue

    if straightest_path_variation == None or s_path_variation < straightest_path_variation:
      print( "    Current best variation {} over {}m".format( s_path_variation, s_path_length ) )
      straightest_path = s_straightest_path
      straightest_path_variation = s_path_variation
      straightest_path_length = s_path_length

  print()
  print( "Overall best variation {} over distance {}m, between nodes {} and {}".format( straightest_path_variation, straightest_path_length, straightest_path[0], straightest_path[-1] ) )

  print()
  print( "Doing the best 100 routes for the best start/end nodes found, see if there is maybe a slightly better option" )

  straightest_path, straightest_path_variation, straight_path_route_length, these_paths, additional_path = do_node(
    graph,
    "final",
    "final",
    straightest_path[0],
    straightest_path[-1],
    100
  )

  print()
  print()
  print( "Rendering" )
  print()

  # Append the routes we tried for the best path found
  for path in these_paths:
    paths.append( { "path" : path, "width" : 0.2, "colour" : "orange" } )

  paths.append( { "path" : straightest_path, "colour" : "green", "width" : 1.0, "line" : True } )

  #  This was the path which was beaten on distance, with the same variation
  if additional_path:
    paths.append( { "path" : additional_path, "width" : 0.5, "colour" : "purple" } )

  straightline.draw_paths( graph, boundary, boundary_gdf, paths, activity + "-" + filename )


  print()
  print()
  print()
  print( "Approximate max variation : {}m over distance {}m".format( straightest_path_variation / 0.00001 / 1.1, straightest_path_length ) )

  os._exit( 0 )




def main( argv ):
  #relation = "R6795460"
  #filename = "whitchurch.png"
  #activity = "bike"

  #relation = "R1410720"
  #filename = "crewe.png"
  #activity = "walk"

  #relation = "R4581086"
  #filename = "shrewsbury.png"
  #activity = "walk"

  #relation = "R163183"
  #filename = "stoke.png"
  #activity = "walk"

  #relation = "R42602"
  #filename = "florence.png"
  #activity = "walk"

  #relation = "R172987"
  #filename = "liverpool.png"
  #activity = "walk"

  #relation = "R146656"
  #filename = "manchester.png"
  #activity = "walk"

  #filename = "cardiff.png"
  #relation = "R1625787"
  #activity = "walk"

  relation = "R167060"
  filename = "shropshire.png"
  activity = "bike"

  #relation = "R65606"
  #filename = "greater-london.png"
  #activity = "walk"

  #relation = "R58437"
  #filename = "wales.png"
  #activity = "bike"

  #relation = "R51701"
  #filename = "switzerland.png"
  #activity = "bike"

  #relation = "R214665"
  #filename = "kazakhstan.png"
  #activity = "walk"

  do_find( filename, relation, activity )

if __name__ == '__main__':
  main( sys.argv )



