from fastapi.testclient import TestClient
from helpers import sample_report

from crypto_diligence.service.app import create_app


def make_client(settings):
    calls: list[str] = []

    async def runner(query, _settings):
        calls.append(query)
        return sample_report(query=query, run_id=f"r{len(calls)}")

    return TestClient(create_app(settings, runner=runner), follow_redirects=False), calls


def test_quota_cache_and_public_pages(settings):
    client, calls = make_client(settings)
    for i in range(3):
        r = client.post("/reports", data={"query": f"token{i}", "email": "A@b.co"})
        assert r.status_code == 303, r.text
    r = client.post("/reports", data={"query": "token9", "email": "a@b.co"})
    assert r.status_code == 429 and "quota" in r.json()["detail"]
    # a cached subject is served without a model run and without touching the quota
    r = client.post("/reports", data={"query": "token0", "email": "a@b.co"})
    assert r.status_code == 303 and r.headers["location"] == "/reports/r1"
    assert calls == ["token0", "token1", "token2"]
    # another email has its own quota
    assert client.post("/reports", data={"query": "token5", "email": "c@d.co"}).status_code == 303

    page = client.get("/reports/r1")
    assert page.status_code == 200 and "Information tool, not advice" in page.text
    assert "onchain-1" in page.text and "No source" in page.text
    assert client.get("/reports/r1.json").json()["run_id"] == "r1"
    assert client.get("/reports/r1.md").text.startswith("# ")
    assert client.get("/reports/nope").status_code == 404
    home = client.get("/")
    assert home.status_code == 200 and "Uniswap (UNI)" in home.text and "not advice" in home.text
    assert "token0" in client.get("/reports").text
    assert client.get("/health").text == "ok"


def test_deployment_cap_bounds_the_spend_whatever_the_emails(settings):
    settings.global_reports_per_day = 2
    client, calls = make_client(settings)
    assert client.post("/reports", data={"query": "t1", "email": "a@b.co"}).status_code == 303
    assert client.post("/reports", data={"query": "t2", "email": "c@d.co"}).status_code == 303
    r = client.post("/reports", data={"query": "t3", "email": "e@f.co"})
    assert r.status_code == 503 and "today" in r.json()["detail"]
    assert calls == ["t1", "t2"]
    # the cache still answers under the cap
    r = client.post("/reports", data={"query": "t1", "email": "g@h.co"})
    assert r.status_code == 303 and r.headers["location"] == "/reports/r1"
    assert client.get("/tiers").json()["deployment_reports_per_day"] == 2


def test_bad_input(settings):
    client, _ = make_client(settings)
    assert client.post("/reports", data={"query": "<script>", "email": "a@b.co"}).status_code == 400
    assert client.post("/reports", data={"query": "uni", "email": "nope"}).status_code == 400


def test_paid_routes_are_closed_while_the_tier_is_off(settings):
    client, _ = make_client(settings)
    client.post("/reports", data={"query": "uni", "email": "a@b.co"})
    assert client.post("/watchlist", data={"email": "a@b.co", "subject": "uni"}).status_code == 403
    assert client.get("/reports/r1/export.csv").status_code == 403
    tiers = client.get("/tiers").json()
    assert tiers["paid"]["enabled"] is False and tiers["free"]["reports_per_day"] == 3


def test_export_once_the_tier_is_on(settings):
    settings.paid_tier_enabled = True
    client, _ = make_client(settings)
    client.post("/reports", data={"query": "uni", "email": "a@b.co"})
    csv = client.get("/reports/r1/export.csv")
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("id,agent")
    assert "onchain-1" in csv.text
