from bot.run import ticker_age


class Client:
    def __init__(self, offset_ms: int, server_ms: int, true_offset_ms: int):
        self.time_offset_ms = offset_ms
        self.last_ticker_server_time_ms = server_ms
        self.true_offset_ms = true_offset_ms
        self.now_ms = 1_000_000
        self.syncs = 0

    def _timestamp(self) -> int:
        return self.now_ms + self.time_offset_ms

    def sync_time(self) -> int:
        self.syncs += 1
        self.time_offset_ms = self.true_offset_ms
        return self.time_offset_ms


def test_wrong_offset_is_resynced_instead_of_freezing():
    c = Client(offset_ms=464_000, server_ms=1_000_000 - 2_000, true_offset_ms=0)
    age, before = ticker_age(c, 120)
    assert c.syncs == 1 and before == 466.0 and age == 2.0


def test_fresh_ticker_does_not_resync():
    c = Client(offset_ms=0, server_ms=1_000_000 - 5_000, true_offset_ms=0)
    assert ticker_age(c, 120) == (5.0, None) and c.syncs == 0


def test_really_stale_ticker_stays_stale():
    c = Client(offset_ms=0, server_ms=1_000_000 - 600_000, true_offset_ms=0)
    age, before = ticker_age(c, 120)
    assert c.syncs == 1 and age == 600.0 and before == 600.0


def test_no_ticker_yet_is_infinite():
    c = Client(0, 0, 0)
    c.last_ticker_server_time_ms = None
    assert ticker_age(c, 120) == (float("inf"), None)
