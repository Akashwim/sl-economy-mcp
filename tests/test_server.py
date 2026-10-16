"""Tests that the tools are wired into the MCP server correctly."""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from sl_economy_mcp import __version__, morning_rates, server, snapshot
from sl_economy_mcp.errors import SourceUnavailable


def test_all_tools_are_registered():
    tools = asyncio.run(server.mcp.list_tools())
    assert [tool.name for tool in tools] == [
        "get_morning_rates",
        "get_snapshot",
        "get_exchange_rate",
        "get_exchange_rate_history",
        "get_inflation_history",
        "get_interest_rates",
    ]
    assert all(tool.annotations.read_only_hint for tool in tools)
    assert all(tool.title for tool in tools)


def test_every_argument_tells_the_assistant_what_to_send():
    for tool in asyncio.run(server.mcp.list_tools()):
        for name, schema in tool.input_schema.get("properties", {}).items():
            assert schema.get("description"), f"{tool.name}.{name} has no description"
    tools = {tool.name: tool.input_schema for tool in asyncio.run(server.mcp.list_tools())}
    assert tools["get_interest_rates"]["properties"]["series"]["enum"] == ["policy", "lending"]
    assert tools["get_exchange_rate_history"]["properties"]["interval"]["enum"] == ["auto", "daily", "monthly"]
    assert tools["get_exchange_rate_history"]["required"] == ["currency", "start_date"]


def test_the_server_introduces_itself():
    assert server.mcp.version == __version__
    assert "Never estimate" in server.mcp.instructions


def test_the_morning_sheet_comes_first_as_plain_text_then_the_data(monkeypatch):
    sheet = {"table": "## Morning Sheet: Friday 16 October 2026\n\n| Section |", "sections": [], "date": "2026-10-16"}
    monkeypatch.setattr(morning_rates, "get_morning_rates", lambda: sheet)
    result = asyncio.run(server.mcp.call_tool("get_morning_rates", {}))
    blocks = result.content
    assert [block.type for block in blocks] == ["text", "text"]
    assert blocks[0].text == sheet["table"]  # exactly as built, not inside JSON
    assert '"date": "2026-10-16"' in blocks[1].text and "## Morning Sheet" not in blocks[1].text


def test_a_wrong_choice_is_refused_before_any_download(monkeypatch):
    with pytest.raises(ToolError, match="policy"):
        asyncio.run(server.mcp.call_tool("get_interest_rates", {"series": "treasury_bills"}))


def test_briefing_prompt_mentions_only_tools_that_exist():
    prompts = asyncio.run(server.mcp.list_prompts())
    assert [prompt.name for prompt in prompts] == ["macro_briefing"]
    text = server.macro_briefing()
    tool_names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    mentioned = {word.strip(".,'") for word in text.split() if word.startswith("get_")}
    assert mentioned and mentioned <= tool_names


def test_assistant_can_read_our_error_messages(monkeypatch):
    def cbsl_is_down(url, form=None):
        raise SourceUnavailable("Could not reach CBSL.")

    monkeypatch.setattr(snapshot, "fetch", cbsl_is_down)
    with pytest.raises(ToolError, match="Could not reach CBSL") as caught:
        asyncio.run(server.mcp.call_tool("get_snapshot", {}))
    assert not isinstance(caught.value, UnexpectedToolError)


def test_bugs_are_not_shown_to_the_assistant(monkeypatch):
    def bug(url, form=None):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(snapshot, "fetch", bug)
    with pytest.raises(UnexpectedToolError) as caught:
        asyncio.run(server.mcp.call_tool("get_snapshot", {}))
    assert "secret" not in str(caught.value)
