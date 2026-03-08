from mcp.server.fastmcp import FastMCP
from .context import register_tools


def main():
    app = FastMCP("Garmin Connect MCP")
    app = register_tools(app)
    app.run()


if __name__ == "__main__":
    main()