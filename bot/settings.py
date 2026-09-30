from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    name: str
    interval: str
    entry_bars: int
    exit_bars: int
    top_n_pool: int
    weight_divisor: int
    max_gross: float
    quote: str
    execution: str
    limit_offset_bps: float
    limit_timeout_s: int
    poll_seconds: int
    universe_refresh_hours: int
    max_spread_bps: float
    min_history_bars: int
    derisk_start_utc: str
    derisk_end_utc: str
    kill_max_drawdown: float
    kill_error_rate: float
    kill_stale_ticker_s: int
    mirror_max_deviation_bps: float
    mirror_reference: str
    config_sha256: str
    dry_run: bool
    venue: str
    ranking_rule: str | None
    n_positions: int | None
    momentum_bars: int
    regime_gate: str
    min_cushion_pct: float
    full_deployment: bool = False
    booking: dict = field(default_factory=dict)
    target_lock: dict = field(default_factory=dict)
    short: dict = field(default_factory=dict)
    universe_mode: str = "binance_top"
    keyset: str | None = None

    @property
    def shorts_enabled(self) -> bool:
        return bool(self.short.get("enabled"))

    @property
    def bars_per_day(self) -> int:
        return {"5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6, "8h": 3, "12h": 2, "1d": 1}[self.interval]


def load(path: str | Path) -> Settings:
    p = Path(path)
    raw = p.read_bytes()
    cfg = yaml.safe_load(raw)
    if not cfg["meta"].get("frozen"):
        raise SettingsError(f"{p}:not_frozen")
    s = cfg["strategy"]
    e = cfg["execution"]
    r = cfg["risk"]
    return Settings(
        name=cfg["meta"]["name"],
        interval=s["interval"],
        entry_bars=int(s["entry_bars"]),
        exit_bars=int(s["exit_bars"]),
        top_n_pool=int(s["top_n_pool"]),
        weight_divisor=int(s["weight_divisor"]),
        max_gross=float(s["max_gross"]),
        quote=s["quote"],
        execution=e["order_type"],
        limit_offset_bps=float(e["limit_offset_bps"]),
        limit_timeout_s=int(e["limit_timeout_s"]),
        poll_seconds=int(e["poll_seconds"]),
        universe_refresh_hours=int(s["universe_refresh_hours"]),
        max_spread_bps=float(s["max_spread_bps"]),
        min_history_bars=int(s["min_history_bars"]),
        derisk_start_utc=r["derisk_start_utc"],
        derisk_end_utc=r["derisk_end_utc"],
        kill_max_drawdown=float(r["max_drawdown"]),
        kill_error_rate=float(r["max_error_rate"]),
        kill_stale_ticker_s=int(r["max_ticker_age_s"]),
        mirror_max_deviation_bps=float(r["mirror_max_deviation_bps"]),
        mirror_reference=r.get("mirror_reference", "binance_spot"),
        config_sha256=hashlib.sha256(raw).hexdigest()[:16],
        dry_run=bool(cfg["meta"].get("paper_only")) or os.environ.get("ROOSTOO_DRY_RUN", "1") != "0",
        venue=os.environ.get("BOT_VENUE", cfg["meta"].get("venue", "roostoo")),
        keyset=cfg["meta"].get("keyset"),
        ranking_rule=s.get("ranking_rule"),
        n_positions=(int(s["n_positions"]) if s.get("n_positions") else None),
        regime_gate=s.get("regime_gate", "always_on"),
        universe_mode=s.get("universe_mode", "binance_top"),
        min_cushion_pct=float(s.get("min_cushion_pct", 1.0)),
        full_deployment=bool(s.get("full_deployment", False)),
        booking=dict(cfg.get("booking") or {}),
        target_lock=dict(cfg.get("target_lock") or {}),
        short=dict(cfg.get("short") or {}),
        momentum_bars=int(s.get("momentum_bars", 20)),
    )


def credentials(keyset: str | None = None) -> tuple[str | None, str | None]:
    """Roostoo key pair for this process.

    `keyset` (a config's `meta.keyset`, else `ROOSTOO_KEYSET`) of `test` or `comp` selects
    `ROOSTOO_TEST_*` or `ROOSTOO_COMP_*`, so the competition keys reach only the book whose
    config names them; otherwise the plain `ROOSTOO_API_KEY` pair.
    DECISIONS.md#roostoo-keys-2026-09-30
    """
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    keyset = (keyset or os.environ.get("ROOSTOO_KEYSET", "")).strip().upper()
    if keyset:
        if keyset not in ("TEST", "COMP"):
            raise ValueError(f"ROOSTOO_KEYSET must be test or comp, got {keyset!r}")
        return (os.environ.get(f"ROOSTOO_{keyset}_API_KEY"),
                os.environ.get(f"ROOSTOO_{keyset}_SECRET_KEY"))
    return os.environ.get("ROOSTOO_API_KEY"), os.environ.get("ROOSTOO_SECRET_KEY")


def make_client(settings: "Settings"):
    key, secret = credentials(settings.keyset)
    if settings.venue == "binance_testnet":
        from venue.binance_testnet import BinanceTestnetClient
        return BinanceTestnetClient(os.environ.get("BINANCE_TESTNET_KEY"),
                                    os.environ.get("BINANCE_TESTNET_SECRET"))
    from venue.roostoo import RoostooClient
    return RoostooClient(key, secret)
