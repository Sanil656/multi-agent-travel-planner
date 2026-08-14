import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from config import (
    AVIATION_STACK_API_KEY,
    OPENWEATHER_API_KEY,
    TAVILY_API_KEY,
)

# ---------------------------------------------------------
# Logging
# ---------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Project Paths
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

PYTHON = sys.executable

WEATHER_SERVER = BASE_DIR / "weather_mcp_server.py"

# ---------------------------------------------------------
# MCP Client
# ---------------------------------------------------------

client = MultiServerMCPClient(
    {
        "tavily": {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}",
        },
        "aviationstack": {
            "transport": "stdio",
            "command": PYTHON,
            "args": [
                "-m",
                "aviationstack_mcp",
                "mcp",
                "run",
            ],
            "env": {
                "AVIATION_STACK_API_KEY": AVIATION_STACK_API_KEY,
            },
        },
        "weather": {
            "transport": "stdio",
            "command": PYTHON,
            "args": [
                str(WEATHER_SERVER),
            ],
            "env": {
                "OPENWEATHER_API_KEY": OPENWEATHER_API_KEY,
            },
        },
    }
)

# ---------------------------------------------------------
# Tool Cache
# ---------------------------------------------------------

_tools_cache = None


# ---------------------------------------------------------
# Tool Discovery
# ---------------------------------------------------------

async def get_tools():
    """
    Fetch available MCP tools once and cache them.
    """
    global _tools_cache

    if _tools_cache is None:

        try:
            tools = await client.get_tools()

            _tools_cache = {
                tool.name: tool
                for tool in tools
            }

            logger.info(
                "Loaded %d MCP tools.",
                len(_tools_cache),
            )

        except Exception:
            logger.exception("Failed to load MCP tools.")
            raise

    return _tools_cache


# ---------------------------------------------------------
# Generic Tool Caller
# ---------------------------------------------------------

async def call_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
):

    tools = await get_tools()

    tool = tools.get(tool_name)

    if tool is None:

        available = ", ".join(tools.keys())

        raise ValueError(
            f"Tool '{tool_name}' not found.\n"
            f"Available tools: {available}"
        )

    try:

        return await tool.ainvoke(args or {})

    except Exception:

        logger.exception(
            "Tool '%s' failed.",
            tool_name,
        )

        raise


# ---------------------------------------------------------
# Convenience Wrapper Functions
# ---------------------------------------------------------

async def tavily_search(query: str):

    return await call_tool(
        "tavily_search",
        {
            "query": query,
        },
    )


async def list_airports(
    search: str = "",
    limit: int = 10,
):

    return await call_tool(
        "list_airports",
        {
            "search": search,
            "limit": limit,
            "offset": 0,
        },
    )


async def list_airlines(
    search: str = "",
    limit: int = 10,
):

    return await call_tool(
        "list_airlines",
        {
            "search": search,
            "limit": limit,
            "offset": 0,
        },
    )


async def current_weather(city: str):

    return await call_tool(
        "get_current_weather",
        {
            "city": city,
        },
    )


async def forecast(city: str):

    return await call_tool(
        "get_forecast",
        {
            "city": city,
        },
    )