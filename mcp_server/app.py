import json
from fastmcp import FastMCP


mcp = FastMCP("Northstar-Leave-Management-MCP")

def run_tool(func, *args, **kwargs) -> str:
    """Helper: Executes a database function safely and returns formatted JSON."""
    try:
        data = func(*args, **kwargs)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as err:
        return json.dumps({"success": False, "error": str(err)}, ensure_ascii=False, indent=2)