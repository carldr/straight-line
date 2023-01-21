# Straight Line

## Dependencies

- `brew install miniconda`
- `conda config --prepend channels conda-forge`
- `conda create -n ox --strict-channel-priority osmnx`
- `conda init zsh`
- Open new terminal, `conda activate ox`

## Running

- `python run.py 2> /dev/null && identify shropshire.png  && open shropshire.png`
- `python run.py 2> /dev/null && identify whitchurch.png  && open whitchurch.png`
