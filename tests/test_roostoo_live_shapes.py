from bot.intents import _heuristic
from bot.state import wallet_positions
from venue.roostoo import RoostooClient, RoostooError

BALANCE = {"Success": True, "ErrMsg": "", "MarginWallet": {},
           "SpotWallet": {"BTC": {"Free": 0.00236, "Lock": 0, "PendingOrders": 0, "ShortCollateral": 0},
                          "USD": {"Free": 49800.15, "Lock": 0, "PendingOrders": 0, "ShortCollateral": 0}}}
ORDER = {"Pair": "BTC/USD", "OrderID": 3403180, "Status": "PENDING", "Role": "MAKER",
         "Side": "BUY", "Type": "LIMIT", "Price": 76136.4, "Quantity": 0.00262,
         "FilledQuantity": 0, "CreateTimestamp": 1790777200910}


class Stub(RoostooClient):
    def __init__(self, reply):
        super().__init__("k", "s")
        self.reply = reply
        self.sent = []

    def _request(self, method, path, params=None, signed=False):
        self.sent.append(dict(params or {}))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_balance_reads_spot_wallet():
    holdings, cash = wallet_positions(Stub(BALANCE).balance(), quote="USD")
    assert holdings == {"BTCUSDT": 0.00236}
    assert cash == 49800.15


def test_query_order_normalises_order_matched_and_flag():
    c = Stub({"Success": True, "ErrMsg": "", "OrderMatched": [ORDER]})
    out = c.query_order(pending_only=True)
    assert out["OrderDetails"] == [ORDER]
    assert c.sent[0]["pending_only"] == "TRUE"


def test_query_order_no_match_is_empty_not_error():
    c = Stub(RoostooError("/v3/query_order:no order matched"))
    assert c.query_order(pending_only=True)["OrderDetails"] == []


def test_intent_heuristic_finds_order_in_query_response():
    resp = Stub({"Success": True, "OrderMatched": [ORDER]}).query_order(pair="BTC/USD")
    row = {"pair": "BTC/USD", "side": "BUY", "quantity": 0.00262, "ts": 1790777200.0}
    assert _heuristic(resp, row) is not None


def test_binance_rest_fails_over_to_mirror():
    import requests
    from data import binance

    class Resp:
        def __init__(self, code):
            self.status_code = code

    class Session:
        def __init__(self):
            self.urls = []

        def get(self, url, **kw):
            self.urls.append(url)
            if url.startswith(binance.REST):
                return Resp(451)
            return Resp(200)

    s = Session()
    assert binance.rest_get("/klines", session=s).status_code == 200
    assert s.urls[-1].startswith(binance.REST_MIRROR)

    class Down(Session):
        def get(self, url, **kw):
            self.urls.append(url)
            if url.startswith(binance.REST):
                raise requests.ConnectionError("down")
            return Resp(200)

    d = Down()
    assert binance.rest_get("/klines", session=d).status_code == 200


def test_rate_limit_is_not_failed_over():
    from data import binance

    class Resp:
        status_code = 429

    class Session:
        calls = 0

        def get(self, url, **kw):
            Session.calls += 1
            return Resp()

    assert binance.rest_get("/klines", session=Session()).status_code == 429
    assert Session.calls == 1
