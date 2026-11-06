"""Tests that the tools are wired into the MCP server correctly."""

import asyncio
import logging

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


def test_the_assistant_is_told_to_take_one_second_look_when_a_section_is_loading():
    tool = next(tool for tool in asyncio.run(server.mcp.list_tools()) if tool.name == "get_morning_rates")
    assert '"check_again": true' in tool.description and "once only" in tool.description
    # The wait the description promises is the one the sheet keeps to.
    assert f"up to {morning_rates.FOLLOW_UP_SECONDS} seconds" in tool.description
    assert "check_again" in server.mcp.instructions


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


def test_tools_without_inputs_say_they_only_give_the_latest_figures():
    # The MCP library ignores arguments a tool does not have, so an invented
    # "as at" date would silently get today's figures. The description must
    # tell the assistant there is no such input.
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    for name in ("get_morning_rates", "get_snapshot"):
        assert tools[name].input_schema.get("properties", {}) == {}
        assert "takes no inputs and always gives the latest figures" in " ".join(tools[name].description.split())
    assert "cannot give a sheet for an earlier date" in " ".join(tools["get_morning_rates"].description.split())


def test_the_server_trusts_the_computers_own_certificates(monkeypatch):
    calls = []
    monkeypatch.setattr(server.truststore, "inject_into_ssl", lambda: calls.append("truststore"))
    monkeypatch.setattr(server.mcp, "run", lambda: calls.append("run"))
    ours = logging.getLogger("sl_economy_mcp")
    before = (list(ours.handlers), ours.propagate, ours.level)
    try:
        server.main()
    finally:  # main() sets up the log for a real run; leave the other tests' logging as it was
        ours.handlers[:], ours.propagate, ours.level = before[0], before[1], before[2]
    assert calls == ["truststore", "run"]  # before any page is downloaded
