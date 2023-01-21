# Straight Line

You may have seen Tom Davies aka Geowizard on YouTube, and his straight line adventures across Wales, Norway and Scotland, or perhaps 
Alastair Stanley's YouTube videos of him straight lining London and Cardiff.

This repository aims to give you a starting point when picking routes similar to Alastair's city straightlines.  It keeps to public
byways (the exact set it adheres to depends on the activity you pick, walking or biking for instance.)  It won't really help with
straight line planning across countryside like Geowizard does.

## Dependencies

- `brew install miniconda`
- `conda config --prepend channels conda-forge`
- `conda create -n ox --strict-channel-priority osmnx`
- `conda init zsh`
- Open new terminal, `conda activate ox`

- Get the world's coastline water polygons from https://osmdata.openstreetmap.de/data/water-polygons.html
  - Download the most recent shapefile, the split version, in WGS84 format.  It's about 762MB zipped.
  - Unzip the file, the directory should be called `water-polygons-split-4326`.

## Running

- Edit the `relation`, `filename` and `activity` variables to suit.
  - The `activity` is placed before `filename` when writing the image.
  - You get the relation number by searching on https://www.openstreetmap.org/ and searching for towns, cities, countries etc.  There are some examples.
- `python run.py`

## Current issues

- Only tested on macOS.  It should work elsewhere, you'll need to change/remove the call to `os.system` at the end of `draw_paths` on other OSs.
- It's not really finding the closest route to a single line, it's finding the shortest route between two notes, and then working out how
  far from ideal that route is.  Really, we want to favour routes which stay close to the ideal straight line.
- It assumes directions betweeen two nodes are bi-directional (which is probably fine for walking) and uses that to do half the number of
  path finds.
- It's pretty slow when doing country or large-county/state sized regions.
- Doesn't output a .gpx of the final route.
- The code is messy due to the high level of experimenting going on.

## Missing

- Doesn't try and calculate how far from straight the line is (ie, how far off a perfect straightline you'd go by travering the route.)

## Example

There are several .pngs in the repository, but here is one showing the straightest route when biking across Liverpool.

![Straightest route biking across Liverpool](bike-liverpool.png)