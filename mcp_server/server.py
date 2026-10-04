from mcp_server.app import mcp
from mcp_server.tools import (
    create_leave_request,
    list_leave_requests,
    get_leave_balance,
    approve_or_reject_leave_request,
    cancel_leave_request,
    list_leave_types,
)

if __name__ == "__main__":
    print("🚀 Northstar Leave Management MCP Server starting...")
    mcp.run()
