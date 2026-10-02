"""Pre-flight never calls Roostoo with the competition key unless asked: Screen 1 rejects traces of
manually called APIs on the competition account. DECISIONS.md#comp-key-bot-only-2026-10-02"""
from gates import preflight


class FakeClient:
    used: list = []

    def __init__(self, key=None, secret=None):
        FakeClient.used.append(key)

    def sync_time(self):
        return 0

    def exchange_info(self):
        return {}

    def ticker(self):
        return {}

    def balance(self):
        return {"USD": {"Free": 1.0, "Lock": 0}}


def _patch(monkeypatch):
    FakeClient.used = []
    monkeypatch.setattr(preflight, "RoostooClient", FakeClient)
    monkeypatch.setattr(preflight, "credentials", lambda ks: ("TESTKEY", "ts") if ks == "test" else ("COMPKEY", "cs"))
    monkeypatch.setattr(preflight, "check", lambda name, fn: {"check": name, "ok": True, "ms": 0,
                                                              "detail": fn() if "wallet" in name else None})


def test_comp_key_is_checked_for_presence_only(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.delenv("PREFLIGHT_COMP", raising=False)
    rows = preflight.run()
    assert "COMPKEY" not in FakeClient.used and "TESTKEY" in FakeClient.used
    comp = next(r for r in rows if "comp" in r["check"])
    assert comp["check"] == "roostoo_keys_comp" and comp["ok"]


def test_comp_wallet_read_only_when_asked(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setenv("PREFLIGHT_COMP", "1")
    preflight.run()
    assert "COMPKEY" in FakeClient.used
