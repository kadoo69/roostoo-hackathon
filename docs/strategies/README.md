# Short-term strategy files

The five best books on the dashboard at 2026-09-26 ~15:28 IST, one self-contained file each.

| rank | book | file |
|---|---|---|
| 1 | `momentum_top3_30m` | [01_momentum_top3_30m.md](01_momentum_top3_30m.md) |
| 2 | `momentum_top3_15m` | [02_momentum_top3_15m.md](02_momentum_top3_15m.md) |
| 3 | `accel_15m` | [03_accel_15m.md](03_accel_15m.md) |
| 4 | `momentum_top3_5m` | [04_momentum_top3_5m.md](04_momentum_top3_5m.md) |
| 5 | `momentum_top3_30m_allcash` | [05_momentum_top3_30m_allcash.md](05_momentum_top3_30m_allcash.md) |

All five share one engine (`bot/run.py`) and, except `accel_15m`, one signal (`signals/contenders.py`).
They differ in clock, 4h confirmation, stretch-skip lists, minimum hold, idle-cash absorption and the target lock.
Every live number here comes from 2-3 days with the host online 17-40% of the time, and every book's profit is one or two coins (mostly ONDO).
