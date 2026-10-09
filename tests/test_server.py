"""Tests that the tools are wired into the MCP server correctly."""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from sl_economy_mcp import server, snapshot
from sl_economy_mcp.errors import SourceUnavailable


def test_all_tools_are_registered():
    tools = asyncio.run(server.mcp.list_tools())
    assert [tool.name for tool in tools] == [
        "get_snapshot",
        "get_exchange_rate",
        "get_exchange_rate_history",
        "get_inflation_history",
        "get_interest_rates",
    ]
    assert all(tool.annotations.read_only_hint for tool in tools)


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
