# Archive: finished research

Modules that no running book, deploy script or ops command imports, kept so every recorded result stays reproducible (`DECISIONS.md#dead-code-cleanup-2026-10-02`).
113 modules: 86 gates, 13 signals, 6 data collectors, 4 ml_research, 3 portfolio helpers and `bot/alt_data.py`; their tests are in `archive/tests`.

They are a normal package under `archive`, so a command that `DECISIONS.md` gives as `python3 -m gates.<name>` now runs from the repo root as:

    python3 -m archive.gates.<name>

Imports between archived modules point at `archive.<pkg>.<name>`; imports of live code (`gates.let_winners_run`, `bot.feed`, ...) are unchanged, and configs still live in `config/`.
Tests: `python3 -m pytest archive/tests -q` (not part of the default suite).

Nothing in the live tree may import from `archive`. When an archived study is revived, move it back with `git mv` and restore its imports.
Retired runtime (scanner, source hub, paper lab, scalper, accel/topdown/alpha_flow runners, old launchd plists) was deleted, not archived; it is in git history before commit `bb3c8ca`.
