import matplotlib.pyplot as plt
import osmnx as ox
from shapely.geometry import Polygon

#  Get the GeoDataFrame
gdf = ox.geocode_to_gdf( "R167060", by_osmid = True )  # Shropshire

#  Extract the boundary
boundary = Polygon( list( gdf.geometry[0].exterior.coords ) )

#  Build a graph of cycleable routes
graph = ox.graph_from_polygon( boundary, network_type = "bike" )  # "all_private", "all", "bike", "drive", "drive_service", "walk"

ox.plot_graph( graph )

plt.show()