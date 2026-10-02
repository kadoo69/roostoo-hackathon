"""Tests never read this machine's run/LIVE_HOST_EC2 marker: the desk switches to EC2 mode only when a
test points the marker at a file it created. DECISIONS.md#ec2-cutover-2026-10-02"""
import pytest


@pytest.fixture(autouse=True)
def _no_ec2_marker(tmp_path, monkeypatch):
    from bot import ec2_feed
    monkeypatch.setattr(ec2_feed, "MARKER", tmp_path / "no_LIVE_HOST_EC2")
