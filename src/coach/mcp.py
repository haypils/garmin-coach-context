from mcp.server.fastmcp import FastMCP
from coach import context
from coach import garmin_client

def main():
    mcp = FastMCP("Coach MCP")
    mcp = context.register_tools(mcp)
    mcp = garmin_client.register_tools(mcp)
    mcp.run()


if __name__ == "__main__":
    main()