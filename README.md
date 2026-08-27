# nfl

Fantasy football project.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Layout

- `data/` — raw and processed datasets (kept out of git where large/derived)
- `src/` — project source code
- `notebooks/` — exploratory analysis

## TODO

- [ ] Define data sources (e.g. stats, schedules, projections)
- [ ] Build ingestion pipeline
- [ ] Implement scoring / ranking models
- [ ] Wire up weekly updates
