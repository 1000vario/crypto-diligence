import httpx
import pytest

from crypto_diligence.tools import fixtures, http


async def test_replay_serves_recorded_bodies_and_599_otherwise(tmp_path):
    key = http.fixture_key("GET", "https://example.test/a?b=1", None)
    (tmp_path / "r.json").write_bytes(b'{"ok": true}')
    fixtures.save_index(tmp_path, {key: {"file": "r.json", "status": 200,
                                         "content_type": "application/json",
                                         "recorded": "2026-10-11"}})
    http.configure(fixtures.replay_transport(tmp_path))
    try:
        assert await http.get_json("https://example.test/a?b=1") == {"ok": True}
        with pytest.raises(http.ToolError) as exc:
            await http.get_json("https://example.test/missing")
        assert "599" in str(exc.value)
    finally:
        await http.aclose()


def test_fixture_keys_never_hold_credentials():
    key = http.fixture_key("GET", "https://api.example.test/v1?apikey=SECRET123&x=1", None)
    assert "SECRET123" not in key and "x=1" in key
    a = http.fixture_key("POST", "https://rpc.test", b'{"a":1}')
    b = http.fixture_key("POST", "https://rpc.test", b'{"a":2}')
    assert a != b


async def test_recording_drops_the_encoding_header_and_skips_429(tmp_path, monkeypatch):
    async def fake(self, request):
        if "limited" in str(request.url):
            return httpx.Response(429, text="Throttled", request=request)
        r = httpx.Response(200, content=b'{"v": 1}',
                           headers={"content-type": "application/json"}, request=request)
        r.headers["content-encoding"] = "gzip"  # as the network layer reports after decoding
        return r

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake)
    http.configure(fixtures.RecordingTransport(tmp_path))
    try:
        assert await http.get_json("https://example.test/ok") == {"v": 1}
        with pytest.raises(http.ToolError):
            await http.get_json("https://example.test/limited")
    finally:
        await http.aclose()
    index = fixtures.load_index(tmp_path)
    assert len(index) == 1 and next(iter(index.values()))["status"] == 200
    http.configure(fixtures.replay_transport(tmp_path))
    try:
        assert await http.get_json("https://example.test/ok") == {"v": 1}
    finally:
        await http.aclose()
