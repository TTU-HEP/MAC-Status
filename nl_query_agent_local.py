#!/usr/bin/env python3
"""
Local-credentials variant of nl_query_agent.py.

Same read-only natural-language database agent, but it runs through the
Claude Agent SDK using your existing Claude Code login (your Claude
subscription) instead of an ANTHROPIC_API_KEY. All database access,
validation, and rendering is reused from nl_query_agent.py:
only SELECT statements, executed as `viewer` in a READ ONLY transaction,
images saved to agent_plots/, arrays summarized.

Usage:
    python3 nl_query_agent_local.py                    # interactive REPL
    python3 nl_query_agent_local.py "modules assembled last week"

One-time setup if not logged in: run the Claude CLI once and log in
(the script prints the exact command when needed).
"""

import asyncio
import glob
import os
import shutil
import sys

import nl_query_agent as base
from nl_query_agent import count_usage_tokens

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
        create_sdk_mcp_server,
        tool,
    )
except ImportError:
    sys.exit("Missing dependency 'claude-agent-sdk'. Install with: pip install claude-agent-sdk")

MODEL = os.getenv("MAC_AGENT_MODEL", "claude-haiku-5-5")

BUNDLED_CLI_GLOB = os.path.expanduser(
    "~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude"
)


def find_claude_cli() -> str:
    """Prefer a `claude` on PATH, else the newest CLI bundled with the
    Claude desktop app."""
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    candidates = glob.glob(BUNDLED_CLI_GLOB)
    if candidates:
        return max(candidates, key=os.path.getmtime)
    sys.exit(
        "No Claude Code CLI found. Install it (https://claude.com/claude-code) "
        "or use nl_query_agent.py with an ANTHROPIC_API_KEY instead."
    )


DB: base.Database | None = None  # set in main()
SESSION_TOKENS = 0  # total tokens processed this session


@tool("run_sql", base.RUN_SQL_TOOL["description"], {"sql": str})
async def run_sql(args):
    def reply(text):
        return {"content": [{"type": "text", "text": text}]}

    try:
        cleaned = base.validate_sql(args.get("sql", ""))
    except ValueError as err:
        print(f"  [rejected] {err}")
        return reply(f"Query rejected by read-only validator: {err}")
    if base.SHOW_SQL:
        print(f"\nSQL> {cleaned}\n")
    try:
        columns, rows, truncated = await DB.run(cleaned)
    except Exception as err:  # asyncpg errors, network errors
        print(f"  [error] {err}")
        return reply(f"Database error: {err}")
    display_rows = base.materialize(columns, rows)
    # print_results may wait on the user's confirmation for huge tables:
    # run it in a thread so the SDK's event loop keeps pumping messages
    shown = await asyncio.to_thread(
        base.print_results, columns, display_rows, truncated
    )
    return reply(base.rows_for_model(columns, display_rows, truncated, shown))


@tool("make_plot", base.MAKE_PLOT_TOOL["description"],
      base.MAKE_PLOT_TOOL["input_schema"])
async def make_plot(args):
    def reply(text):
        return {"content": [{"type": "text", "text": text}]}

    try:
        text, path = await base.run_plot_request(DB, args)
    except ValueError as err:
        print(f"  [plot rejected] {err}")
        return reply(f"Plot request rejected: {err}")
    except Exception as err:
        print(f"  [plot error] {err}")
        return reply(f"Plot error: {err}")
    print(f"Sketch saved: {os.path.relpath(path)}")
    return reply(text)


async def answer(client: ClaudeSDKClient, question: str) -> None:
    global SESSION_TOKENS
    if SESSION_TOKENS >= base.SESSION_TOKEN_CAP:
        print(f"Session token cap reached ({SESSION_TOKENS:,} of "
              f"{base.SESSION_TOKEN_CAP:,}). Restart the agent, or raise "
              f"MAC_AGENT_SESSION_TOKEN_CAP.")
        return
    await client.query(question)
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    print(f"\n{base.scrub_reply(block.text.strip())}")
        elif isinstance(msg, ResultMessage) and not msg.is_error:
            query_tokens = count_usage_tokens(msg.usage or {})
            SESSION_TOKENS += query_tokens
            line = (f"[tokens — this query: {query_tokens:,}; session: "
                    f"{SESSION_TOKENS:,} / cap {base.SESSION_TOKEN_CAP:,}]")
            if query_tokens >= base.QUERY_TOKEN_CAP:
                line += " (per-query cap exceeded — ask narrower questions)"
            print(f"\n{line}")
        elif isinstance(msg, ResultMessage) and msg.is_error:
            text = str(msg.result or "unknown error")
            print(f"\n[agent error] {text}")
            if "login" in text.lower() or "authent" in text.lower():
                print(
                    "Log in once with your Claude account:\n"
                    f'  "{find_claude_cli()}"\n'
                    "then type /login inside it, finish in the browser, and exit."
                )


async def main():
    global DB
    cli_path = find_claude_cli()
    DB = base.Database(base.resolve_db_password())

    print("Connecting and reading schema...")
    try:
        schema_text = await DB.schema_text()
    except Exception as err:
        sys.exit(f"Could not connect to the database: {err}")

    server = create_sdk_mcp_server(name="macdb", version="1.0.0",
                                   tools=[run_sql, make_plot])
    options = ClaudeAgentOptions(
        cli_path=cli_path,
        mcp_servers={"macdb": server},
        tools=[],  # no built-in tools: the database tool is all it gets
        allowed_tools=["mcp__macdb__run_sql", "mcp__macdb__make_plot"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep",
                          "WebFetch", "WebSearch", "NotebookEdit", "Task"],
        system_prompt=base.build_system_prompt(schema_text),
        model=MODEL,
        max_turns=base.MAX_TOOL_TURNS,
        setting_sources=[],
    )

    async with ClaudeSDKClient(options=options) as client:
        # One-shot mode
        if len(sys.argv) > 1:
            await answer(client, " ".join(sys.argv[1:]))
            return

        print("---------------------------------------------")
        print(f"MAC-BOT George (read-only, local Claude login, model: {MODEL})")
        print("Ask in plain English, e.g. 'modules assembled in October 2025'")
        print("Type EXIT to quit." + ("" if base.SHOW_SQL else " (run with --show-sql to see queries)"))
        while True:
            print("---------------------------------------------")
            try:
                question = (await asyncio.to_thread(input, ">> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nMAC-BOT George signing off. Ciao!")
                return
            if not question:
                continue
            if question.upper() in ("EXIT", "QUIT"):
                print("MAC-BOT George signing off. Ciao!")
                return
            await answer(client, question)


if __name__ == "__main__":
    asyncio.run(main())
