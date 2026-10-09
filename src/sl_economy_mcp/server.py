"""The MCP server: the list of tools an AI assistant is allowed to call.

Each tool is a thin wrapper. The real work lives in the other modules so it
can be tested without starting a server.
"""

from mcp.server.mcpserver import MCPServer

from . import snapshot

mcp = MCPServer("sl-economy-mcp")


@mcp.tool()
def get_snapshot() -> dict:
    """Latest headline Sri Lankan economic indicators from the Central Bank of Sri Lanka.

    Returns the overnight policy rate, CCPI inflation (year-on-year) and the
    USD/LKR telegraphic transfer buying and selling rates, fetched live from
    cbsl.gov.lk, with the source URL and fetch time.
    """
    return snapshot.get_snapshot()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
