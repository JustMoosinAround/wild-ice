# Crack-line detector: first calibration (2026-11-22)

Run: https://github.com/JustMoosinAround/wild-ice/actions/runs/45052548418
`lines` = share of the lake covered by thin bright lines (10-13 m/px Sentinel-2).

| Truth | Lake, day | Brightness class | lines |
|---|---|---|---|
| skated | Skilak 2025-02-12 (owner) | dark 0.100 | **0.065** |
| skated | Westchester 2025-11-09 | grey 0.234 | **0.068** |
| skated | Grant 2025-12-14 | grey 0.206 | **0.026** |
| skated | Skilak 2024-01-19 | dark 0.132 | **0.022** |
| skated | Portage 2024-01-19 | grey 0.267 | **0.022** |
| skated | Lower Trail 2024-11-19 | grey 0.260 | **0.015** |
| skated | Jean 2025-12-14 | grey 0.170 | **0.010** |
| skated | Skilak 2025-02-20 | dark 0.045 | 0.007 |
| skated | Eklutna 2025-01-08 | dark 0.131 | 0.001 |
| skated | Byers 2025-11-09 | dark 0.065 | 0.000 |
| skated | Arc 2025-12-14 | grey 0.360 | n/a (lake too small after the shore trim) |
| snow | Skilak 2024-01-27 | white | 0.006 |
| snow | Kashwitna 2025-11-09 | white | 0.000 |
| open | Kenai Lake 2025-10-18 | dark | 0.003 |
| open | Portage 2025-10-07 | dark | 0.001 |
| open | Skilak 2025-10-10, Eklutna 2025-10-07 | dark | 0.000 |

At lines >= 0.010: 7 of 10 skated days, 0 of 2 snow, 0 of 4 open water.
It catches 5 skated "grey" lakes that the brightness rule calls not-dark.
Dark OR lines >= 0.010 covers all 10 measurable skated days.
