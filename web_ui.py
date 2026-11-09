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


@tool("make_plot", base.MAKE_PLOT_TOOL["description"],
      base.MAKE_PLOT_TOOL["input_schema"])
async def make_plot(args):
    def reply(text):
        return {"content": [{"type": "text", "text": text}]}

    try:
        text, path = await base.run_plot_request(DB, args)
    except ValueError as err:
        STATE["events"].append({"type": "notice",
                                "text": f"Plot rejected: {err}"})
        return reply(f"Plot request rejected: {err}")
    except Exception as err:
        STATE["events"].append({"type": "notice",
                                "text": f"Plot error: {err}"})
        return reply(f"Plot error: {err}")
    STATE["events"].append({"type": "image",
                            "file": os.path.basename(path)})
    return reply(text)


async def api_ask(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "bad request"}, status=400)
    question = str(data.get("question", "")).strip()[:4000]
    if not question:
        return web.json_response({"error": "empty question"}, status=400)

    # Easter egg: encouragement for the frustrated (no model tokens)
    if "useless" in question.lower():
        return web.json_response({
            "events": [{"type": "image", "src": "/assets/brave_cow.png"}],
            "answer": ("勇敢牛马，不怕困难 — brave to the task, fearless of "
                       "trouble. You're not useless. Take a breath; "
                       "I'm right here when you're ready."),
            "tokens": {"query": 0, "session": STATE["session_tokens"],
                       "session_cap": base.SESSION_TOKEN_CAP,
                       "query_cap": base.QUERY_TOKEN_CAP},
        })

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


# ----------------------------------------
# Quick-link endpoints (fixed read-only SQL, no model tokens)
# ----------------------------------------
async def _fetch_all(sql, *args):
    """Uncapped read-only fetch for the fixed quick-link queries."""
    import asyncpg
    conn = await asyncpg.connect(**DB._conn_kwargs)
    try:
        async with conn.transaction(readonly=True):
            return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def _render_env_png(source, rows, hours, part_rows=None):
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import dates as mdates

    hep = base.apply_hep_style(plt)

    if source == "lab":
        panels = [("Temperature (°C)", "temp"), ("Relative humidity (%)", "rh")]
        key = "loc"
        suptitle = f"Lab environment — past {hours} h"
    else:
        panels = [("Temperature (°C)", "temperature_C"),
                  ("Dew point (°C)", "dewpoint_C"),
                  ("System status", "system_C")]
        key = "dev"
        suptitle = f"MMTS environment — past {hours} h"

    n_panels = len(panels) + (1 if part_rows is not None else 0)
    fig, axes = plt.subplots(n_panels, 1, figsize=(10, 3.8 * n_panels),
                             sharex=True, layout="constrained")
    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    for ax, (label, sel) in zip(axes, panels):
        groups = {}
        for r in rows:
            if source == "lab":
                val = r[sel]
            else:
                if r["metric"] != sel:
                    continue
                val = r["v"]
            if val is None:
                continue
            groups.setdefault(r[key], []).append((r["t"], float(val)))
        is_status = sel == "system_C"
        for name in sorted(groups):
            pts = groups[name]
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    linewidth=1.2, label=name,
                    drawstyle="steps-post" if is_status else "default")
        if is_status:
            ax.set_ylim(-0.3, 5.5)
            ax.set_yticks(range(6))
        ax.set_ylabel(label, fontsize=15)
        ax.grid(alpha=0.25)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(fontsize=11, frameon=False, loc="upper left",
                      bbox_to_anchor=(1.01, 1))
        if not groups:
            ax.text(0.5, 0.5, "no data in window", transform=ax.transAxes,
                    ha="center", color="#999")

    if part_rows is not None:
        ax = axes[-1]
        locs = sorted({r["loc"] for r in part_rows})
        channels = [("p500", "≥0.5 µm"), ("p1000", "≥1 µm"), ("p5000", "≥5 µm")]
        for loc in locs:
            pts = [r for r in part_rows if r["loc"] == loc]
            for col, label in channels:
                name = f"{label} · {loc}" if len(locs) > 1 else label
                ax.plot([r["t"] for r in pts],
                        [r[col] for r in pts],
                        marker="o", markersize=3.5, linewidth=1.2, label=name)
        ax.set_ylabel("Particles (per m³)", fontsize=15)
        ax.grid(alpha=0.25)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        if part_rows:
            ax.legend(fontsize=11, frameon=False, loc="upper left",
                      bbox_to_anchor=(1.01, 1))
        else:
            ax.text(0.5, 0.5, "no particle data in window",
                    transform=ax.transAxes, ha="center", color="#999")
    if hep:
        base.cms_label(axes[0])
    fig.suptitle(suptitle, fontsize=16)
    buf = io.BytesIO()
    # bbox_inches="tight" grows the canvas around the outside legends
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


async def api_env_plot(request):
    source = request.query.get("source", "lab")
    hours = min(max(int(request.query.get("hours", "6")), 1), 48)
    part_rows = None
    if source == "lab":
        rows = await _fetch_all(f"""
            SELECT date_trunc('minute', log_timestamp) AS t,
                   log_location AS loc,
                   avg(temp_c) AS temp, avg(rel_hum) AS rh
            FROM temp_humidity
            WHERE log_timestamp > now() - interval '{hours} hours'
            GROUP BY 1, 2 ORDER BY 1;""")
        part_rows = await _fetch_all(f"""
            SELECT log_timestamp AS t, log_location AS loc,
                   prtcls_per_cubic_m_500nm AS p500,
                   prtcls_per_cubic_m_1um AS p1000,
                   prtcls_per_cubic_m_5um AS p5000
            FROM particulate_counts
            WHERE log_timestamp > now() - interval '{hours} hours'
            ORDER BY 1;""")
    else:
        source = "mmts"
        rows = await _fetch_all(f"""
            SELECT date_trunc('minute', log_timestamp) AS t,
                   device_name AS dev, metric, avg(value) AS v
            FROM mmts_sensors_logging
            WHERE metric IN ('temperature_C', 'dewpoint_C', 'system_C')
              AND log_timestamp > now() - interval '{hours} hours'
            GROUP BY 1, 2, 3 ORDER BY 1;""")
    png = await asyncio.to_thread(_render_env_png, source, rows, hours,
                                  part_rows)
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": "no-store"})


async def api_production(request):
    rows = await _fetch_all("""
        WITH latest AS (
          SELECT DISTINCT ON (q.module_no) q.module_no, q.final_grade
          FROM module_qc_summary q
          ORDER BY q.module_no, q.grade_timestamp DESC NULLS LAST,
                   q.mod_qc_no DESC
        )
        SELECT left(m.module_name, 9) AS type,
          count(*) AS total,
          count(*) FILTER (WHERE l.final_grade = 'A') AS "A",
          count(*) FILTER (WHERE l.final_grade = 'B') AS "B",
          count(*) FILTER (WHERE l.final_grade = 'C') AS "C",
          count(*) FILTER (WHERE l.final_grade = 'F') AS "F",
          count(*) FILTER (WHERE l.module_no IS NOT NULL
                           AND l.final_grade IS NULL) AS "no grade",
          count(*) FILTER (WHERE l.module_no IS NULL) AS ungraded
        FROM module_info m LEFT JOIN latest l USING (module_no)
        GROUP BY 1 ORDER BY total DESC;""")
    columns = (["type", "total", "A", "B", "C", "F", "no grade", "ungraded"]
               if rows else [])
    return web.json_response({
        "columns": columns,
        "rows": [[str(r[c]) for c in columns] for r in rows],
    })


async def index(request):
    return web.FileResponse(os.path.join(HERE, "web_ui.html"))


async def on_startup(app):
    global DB, CLIENT
    DB = base.Database(base.resolve_db_password())
    schema_text = await DB.schema_text()
    server = create_sdk_mcp_server(name="macdb", version="1.0.0",
                                   tools=[run_sql, make_plot])
    options = ClaudeAgentOptions(
        cli_path=find_claude_cli(),
        mcp_servers={"macdb": server},
        tools=[],
        allowed_tools=["mcp__macdb__run_sql", "mcp__macdb__make_plot"],
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
    app.router.add_get("/api/env_plot", api_env_plot)
    app.router.add_get("/api/production", api_production)
    os.makedirs(base.PLOTS_DIR, exist_ok=True)
    app.router.add_static("/plots/", base.PLOTS_DIR)
    app.router.add_static("/assets/", os.path.join(HERE, "ui_assets"))
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"MAC-BOT George UI: http://localhost:{PORT}")
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
