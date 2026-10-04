import os
import sys


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.seed import seed_db_from_excel
from mcp_server.app import mcp
import mcp_server.tools

if __name__ == "__main__":
    print("Initializing Database...")
    seed_db_from_excel()

    print("🚀 Northstar Leave Management MCP Server starting...")
    mcp.run()