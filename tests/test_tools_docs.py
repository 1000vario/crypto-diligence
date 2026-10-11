import pytest

from crypto_diligence.tools import docs, fixtures, http
from crypto_diligence.tools.http import ToolError


async def test_github_repo_facts(ctx):
    out = await docs.github_repo(ctx, "https://github.com/Uniswap/v3-core")
    assert out["full_name"] == "Uniswap/v3-core" and out["stars"] > 1000
    assert out["archived"] is False and out["license"]
    assert out["created_at"].startswith("20") and out["pushed_at"] > out["created_at"]
    assert out["latest_commit"]["sha"] and out["latest_commit"]["date"]
    assert out["contributors"]
    assert any("unauthenticated" in n for n in out["notes"])


def test_repo_path_normalisation():
    assert docs._repo_path("github.com/Uniswap/v3-core/") == "Uniswap/v3-core"
    assert docs._repo_path("Uniswap/v3-core.git") == "Uniswap/v3-core"
    with pytest.raises(ToolError):
        docs._repo_path("just-a-name")


async def test_fetch_page_refuses_local_and_private_addresses(ctx):
    for url in ("http://localhost/admin", "http://127.0.0.1:8545/", "http://10.0.0.5/x",
                "file:///etc/passwd", "ftp://example.org/x"):
        with pytest.raises(ToolError):
            await docs.fetch_page(ctx, url)


async def test_fetch_page_strips_html(ctx, tmp_path):
    key = http.fixture_key("GET", "https://example.test/doc", None)
    (tmp_path / "p.html").write_text(
        "<html><head><title>T</title><style>p{}</style></head>"
        "<body><h1>Whitepaper</h1><p>Audited by <b>two</b> firms.</p>"
        "<script>alert(1)</script></body></html>", encoding="utf-8")
    fixtures.save_index(tmp_path, {key: {"file": "p.html", "status": 200,
                                         "content_type": "text/html; charset=utf-8",
                                         "recorded": "2026-10-11"}})
    await http.aclose()
    http.configure(fixtures.replay_transport(tmp_path))
    try:
        out = await docs.fetch_page(ctx, "https://example.test/doc", max_chars=5000)
    finally:
        await http.aclose()
    assert out["status"] == 200 and out["content_type"] == "text/html"
    assert "Whitepaper" in out["text"] and "two firms" in out["text"]
    assert "alert(1)" not in out["text"] and "<p>" not in out["text"]
    assert not out["truncated"] and out["chars"] == len(out["text"])
