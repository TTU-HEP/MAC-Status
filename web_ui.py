#!/usr/bin/env python3
"""
Web chat UI for MAC-BOT George, the read-only TTU MAC database agent.

Wraps the same agent as nl_query_agent_local.py (Claude Code login, no API
key) behind a small local web server with a chat interface. All safety
layers are shared with the CLI agents: SELECT-only validation, READ ONLY
transactions, reply scrubbing, outlier flagging, token caps.

Usage:
    python3 web_ui.py            # serves http://localhost:8765
Environment:
    MAC_AGENT_UI_PORT  port (default 8765)
    plus everything nl_query_agent.py honors (model, caps, ...)
"""

import asyncio
import os
import sys

from aiohttp import web

import nl_query_agent as base
from nl_query_agent import count_usage_tokens
from nl_query_agent_local import find_claude_cli

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    tool,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.getenv("MAC_AGENT_UI_PORT", "8765"))
MODEL = os.getenv("MAC_AGENT_MODEL", "claude-haiku-5-5")
UI_TABLE_ROW_CAP = 500  # rows sent to the browser per query

DB: base.Database | None = None
CLIENT: ClaudeSDKClient | None = None
LOCK = asyncio.Lock()
STATE = {"events": [], "show_sql": False, "session_tokens": 0}


@tool("run_sql", base.RUN_SQL_TOOL["description"], {"sql": str})
async def run_sql(args):
    def reply(text):
        return {"content": [{"type": "text", "text": text}]}

    try:
        cleaned = base.validate_sql(args.get("sql", ""))
    except ValueError as err:
        STATE["events"].append({"type": "notice",
                                "text": f"Query rejected: {err}"})
        return reply(f"Query rejected by read-only validator: {err}")
    if STATE["show_sql"]:
        STATE["events"].append({"type": "sql", "sql": cleaned})
    try:
        columns, rows, truncated = await DB.run(cleaned)
    except Exception as err:
        STATE["events"].append({"type": "notice",
                                "text": f"Database error: {err}"})
        return reply(f"Database error: {err}")
    display = base.materialize(columns, rows)
    STATE["events"].append({
        "type": "table",
        "columns": columns,
        "rows": [[r[c] for c in columns] for r in display[:UI_TABLE_ROW_CAP]],
        "truncated": truncated,
    })
    # shown=True: the UI renders the table next to the answer
    return reply(base.rows_for_model(columns, display, truncated, shown=True))


async def api_ask(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "bad request"}, status=400)
    question = str(data.get("question", "")).strip()[:4000]
    if not question:
        return web.json_response({"error": "empty question"}, status=400)

    async with LOCK:
        if STATE["session_tokens"] >= base.SESSION_TOKEN_CAP:
            return web.json_response({
                "error": (f"Session token cap reached "
                          f"({STATE['session_tokens']:,} of "
                          f"{base.SESSION_TOKEN_CAP:,}). Restart the server "
                          f"or raise MAC_AGENT_SESSION_TOKEN_CAP.")
            }, status=429)
        STATE["events"] = []
        STATE["show_sql"] = bool(data.get("show_sql"))
        texts, query_tokens, error = [], 0, None
        try:
            await CLIENT.query(question)
            async for msg in CLIENT.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            texts.append(base.scrub_reply(block.text.strip()))
                elif isinstance(msg, ResultMessage):
                    if msg.is_error:
                        error = str(msg.result or "agent error")
                    query_tokens = count_usage_tokens(msg.usage or {})
                    STATE["session_tokens"] += query_tokens
        except Exception as err:
            error = str(err)
        payload = {
            "events": STATE["events"],
            "answer": "\n\n".join(texts),
            "tokens": {
                "query": query_tokens,
                "session": STATE["session_tokens"],
                "session_cap": base.SESSION_TOKEN_CAP,
                "query_cap": base.QUERY_TOKEN_CAP,
            },
        }
        if error:
            payload["error"] = error
        return web.json_response(payload)


async def api_status(request):
    return web.json_response({
        "model": MODEL,
        "db": f"{base.CONFIG['dbname']} @ {base.CONFIG['db_hostname']}",
        "session_tokens": STATE["session_tokens"],
        "session_cap": base.SESSION_TOKEN_CAP,
    })


async def index(request):
    return web.FileResponse(os.path.join(HERE, "web_ui.html"))


async def on_startup(app):
    global DB, CLIENT
    DB = base.Database(base.resolve_db_password())
    schema_text = await DB.schema_text()
    server = create_sdk_mcp_server(name="macdb", version="1.0.0",
                                   tools=[run_sql])
    options = ClaudeAgentOptions(
        cli_path=find_claude_cli(),
        mcp_servers={"macdb": server},
        tools=[],
        allowed_tools=["mcp__macdb__run_sql"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep",
                          "WebFetch", "WebSearch", "NotebookEdit", "Task"],
        system_prompt=base.build_system_prompt(schema_text) + (
            "\n\nWEB UI MODE: you are running behind a chat web page. Every "
            "run_sql result table — including images from bytea columns — is "
            "rendered inline in the chat right above your reply. When the "
            "user asks for a plot or image, SELECT that bytea column (with "
            "the part's name column and a tight LIMIT) in a fresh query even "
            "if you fetched it before: the page then displays the image. "
            "Never say you cannot display images. Avoid repeating file paths; "
            "refer to 'the image above'."
        ),
        model=MODEL,
        max_turns=base.MAX_TOOL_TURNS,
        setting_sources=[],
    )
    CLIENT = ClaudeSDKClient(options=options)
    await CLIENT.connect()
    print(f"Agent ready (model: {MODEL})")


async def on_cleanup(app):
    if CLIENT:
        await CLIENT.disconnect()


def main():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/api/ask", api_ask)
    app.router.add_get("/api/status", api_status)
    os.makedirs(base.PLOTS_DIR, exist_ok=True)
    app.router.add_static("/plots/", base.PLOTS_DIR)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"MAC-BOT George UI: http://localhost:{PORT}")
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
