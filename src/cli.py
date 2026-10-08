"""
Georgian HR assistant CLI (Northstar Services).
Starts the leave MCP server (mcp_server/main.py) over stdio and keeps one session for the
whole conversation. Usage: python src/cli.py
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

from src.assistant import GeorgianAIAssistant
from src.assistant import messages

SERVER_SCRIPT = os.path.join(ROOT, "mcp_server", "main.py")
SERVER_LOG = Path(ROOT) / "data" / "mcp_server.log"
QUIT_WORDS = {"გასვლა", "დასრულება", "exit", "quit", "q"}


async def read_line(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def main() -> int:
    raw_id = (await read_line("თანამშრომლის ID (მაგ. E1001): ")).strip()

    transport = PythonStdioTransport(
        script_path=SERVER_SCRIPT, cwd=ROOT, python_cmd=sys.executable, log_file=SERVER_LOG
    )
    async with Client(transport) as client:
        assistant = await GeorgianAIAssistant.login(client, raw_id)
        if assistant is None:
            print(f"❌ თანამშრომელი '{raw_id}' ვერ მოიძებნა. სესია დასრულდა.")
            return 1

        print(messages.welcome(assistant.employee_name, assistant.employee_id))

        while True:
            try:
                message = (await read_line("\nთქვენ: ")).strip()
            except EOFError:
                break
            if not message:
                continue
            if message.lower() in QUIT_WORDS:
                break

            result = await assistant.process_message(message)
            print(f"\nასისტენტი: {result['reply']}")

    print("\nნახვამდის!")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nნახვამდის!")
