import asyncio
import json
import os
import shutil
import sys
from datetime import date, datetime

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from fastmcp import Client

import mcp_server.tools  # noqa: F401  (registers the tools on `mcp`)
import src.assistant.agent as agent_module
import src.service.leave_service as leave_service
import src.service.session as session_module
from mcp_server.app import mcp
from src.database import make_engine
from src.seed import seed_db_from_excel

# A Friday; the seed data's pending and future requests are relative to this date.
TODAY = date(2026, 10, 9)


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(TODAY.year, TODAY.month, TODAY.day)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(TODAY.year, TODAY.month, TODAY.day, 12, 0, 0)


@pytest.fixture(scope="session")
def seeded_db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "template.db"
    engine = make_engine(str(path))
    seed_db_from_excel(engine)
    engine.dispose()
    return path


@pytest.fixture(autouse=True)
def db(seeded_db_path, tmp_path, monkeypatch):
    """Every test gets a fresh copy of the seeded database; data/leave_system.db is never touched."""
    path = tmp_path / "leave_system.db"
    shutil.copy(seeded_db_path, path)
    engine = make_engine(str(path))
    monkeypatch.setattr(session_module, "engine", engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(leave_service, "date", FixedDate)
    monkeypatch.setattr(leave_service, "datetime", FixedDateTime)
    monkeypatch.setattr(mcp_server.tools, "datetime", FixedDateTime)
    monkeypatch.setattr(agent_module, "datetime", FixedDateTime)


def call_tool(name: str, **arguments):
    """Call an MCP tool over the in-memory transport and decode its JSON reply."""
    async def run():
        async with Client(mcp) as client:
            result = await client.call_tool(name, arguments)
            return json.loads(result.content[0].text)
    return asyncio.run(run())
