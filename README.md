# Straight Line

## Dependencies

- `brew install miniconda`
- `conda config --prepend channels conda-forge`
- `conda create -n ox --strict-channel-priority osmnx`
- `conda init zsh`
- Open new terminal, `conda activate ox`

## Running

- Edit the `relation`, `filename` and `activity` variables to suit.  You get the relation number by searching on https://www.openstreetmap.org/ and
  searching for towns, cities, countries etc.  There are some examples.
- `python run.py`

## Current issues

- The starting and end node has to be outside of the boundary of the relation you picked, so doesn't work well when a large part of the 
  boundary is water.
- It assumes directions betweeen two nodes are bi-directional (which is probably fine for walking) and uses that to do half the number of
  path finds.