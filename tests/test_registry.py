import json

from crypto_diligence.schemas import AGENT_NAMES
from crypto_diligence.tools.registry import TOOLSETS, WEB_SEARCH, all_specs, run_tool, tools_for


def test_toolsets_are_scoped_and_single_is_their_union():
    names = set(all_specs()) | {WEB_SEARCH.name}  # web_search runs server side, no spec
    union: set[str] = set()
    for agent in AGENT_NAMES:
        assert set(TOOLSETS[agent]) <= names
        union |= set(TOOLSETS[agent])
    assert set(TOOLSETS["single"]) == union
    assert "analyze_bytecode" in TOOLSETS["onchain"]
    assert "analyze_bytecode" not in TOOLSETS["market"]
    assert set(TOOLSETS["market"]) <= {t.name for t in tools_for("market")}
    for spec in all_specs().values():
        assert spec.description and spec.input_schema["type"] == "object"


async def test_run_tool_reports_errors_as_results(ctx):
    text, is_error = await run_tool(ctx, "no_such_tool", {})
    assert is_error and "no_such_tool" in text
    text, is_error = await run_tool(ctx, "get_token_metadata", {"address": "nope"})
    assert is_error
    text, is_error = await run_tool(ctx, "get_token_metadata",
                                    {"address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"})
    assert not is_error and json.loads(text)["symbol"] == "UNI"
