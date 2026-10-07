import json
from fastmcp import FastMCP


mcp = FastMCP("Northstar-Leave-Management-MCP")


def run_tool(func, *args, **kwargs) -> str:
    """Run a tool body and return JSON; refusals keep their policy article and a 'forbidden' flag."""
    try:
        data = func(*args, **kwargs)
    except PermissionError as err:
        data = {"success": False, "forbidden": True, "error": str(err), "article": getattr(err, "article", None)}
    except Exception as err:
        data = {"success": False, "error": str(err)}
        if getattr(err, "article", None):
            data["article"] = err.article
    return json.dumps(data, ensure_ascii=False, indent=2)
