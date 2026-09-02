# Projection backtest

This leakage-controlled returning-player backtest trains on 2022–2024 regular-season weekly rows and predicts 2025 half-PPR points per game. Players need at least four realized target-season games. It reports rank correlation, PPG error, and positional top-N recall.

## Production recency weights plus games/20 shrinkage

| Scope | Players | Spearman | MAE PPG | Top-N recall |
|---|---:|---:|---:|---:|
| ALL | 419 | 0.782 | 2.422 | — |
| QB | 52 | 0.688 | 4.043 | 0.500 (top 12) |
| RB | 100 | 0.759 | 2.631 | 0.750 (top 24) |
| WR | 172 | 0.794 | 2.245 | 0.458 (top 24) |
| TE | 95 | 0.761 | 1.633 | 0.500 (top 12) |

## Equal-season-weight comparison

| Scope | Players | Spearman | MAE PPG | Top-N recall |
|---|---:|---:|---:|---:|
| ALL | 419 | 0.776 | 2.459 | — |
| QB | 52 | 0.699 | 3.987 | 0.500 (top 12) |
| RB | 100 | 0.745 | 2.675 | 0.750 (top 24) |
| WR | 172 | 0.785 | 2.331 | 0.458 (top 24) |
| TE | 95 | 0.759 | 1.624 | 0.500 (top 12) |

## Prior-year PPG baseline

| Scope | Players | Spearman | MAE PPG | Top-N recall |
|---|---:|---:|---:|---:|
| ALL | 403 | 0.778 | 2.516 | — |
| QB | 51 | 0.545 | 4.974 | 0.417 (top 12) |
| RB | 94 | 0.810 | 2.464 | 0.708 (top 24) |
| WR | 164 | 0.805 | 2.205 | 0.542 (top 24) |
| TE | 94 | 0.720 | 1.778 | 0.583 (top 12) |

## Interpretation and limits

This validates the historical baseline, recency weighting, and games/20 shrinkage for returning players. It does not validate rookie priors because rookies have no prior NFL rows, and it intentionally excludes current depth-chart role and future schedule/SOS adjustments because using end-of-season target-year data would leak future information. Those components must remain separately labeled heuristics.

The model should not be described as a proven advantage merely because it beats or trails one baseline on one season. Re-run this report after every completed season and compare multiple target years when enough cached history exists.
