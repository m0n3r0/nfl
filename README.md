# nfl

Fantasy football toolkit. Ingests public NFL player/stat data, scores it, ranks
players, and builds a weekly lineup.

## Data source

Player stats, rosters, and schedules are pulled from the public
[nflverse-data](https://github.com/nflverse/nflverse-data) GitHub release assets
(no API key required). Data is cached under `data/raw/` and not committed.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python cli.py ingest        # download + cache 2024 data into data/raw/
```

## CLI

```bash
python cli.py ingest                  # download + cache nflverse data
python cli.py rank --preset ppr --top 15
python cli.py week 9 --preset half-ppr --top 10
python cli.py lineup --preset ppr
python cli.py validate                # compare our scoring vs nflverse's shipped numbers
```

Presets: `standard`, `ppr`, `half-ppr`.

## Scoring

Weights were reverse-engineered from nflverse's own shipped `fantasy_points` /
`fantasy_points_ppr` columns via least-squares regression (R^2 = 1.000 on the
2024 weekly table), so `cli.py validate` shows a max delta of 0.00 across all
presets. Highlights that differ from generic textbook scoring:
- interceptions: −2.0
- every fumble LOST: −2.0 (split across rushing / receiving / sack fumbles)
- 2-point conversions: +2.0

See `src/config.py` for the full weight table.

## Tests

```bash
python -m pytest tests/ -q
```

`tests/test_scoring.py` asserts our scoring reproduces nflverse's numbers within
rounding and that PPR = standard + receptions.

## Known limitations

- The nflverse *player* stat table scores Kickers and Team-Defense as 0 (defense
  is team-level data). The lineup optimizer therefore leaves the K/DEF slots empty
  rather than fabricating 0-point picks. Feed those datasets in to fill them.
- The lineup optimizer is a greedy "best available" heuristic, not an optimal
  integer-program solver.
