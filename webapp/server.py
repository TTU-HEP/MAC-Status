#!/usr/bin/env python3
"""
Web front end for the TTU MAC natural-language database agent.

Lab members sign in with their name and a shared lab password, ask questions
in plain English, and watch the answer stream in live: each SQL query, its
result table (plots shown inline), then the summary. All database access
reuses nl_query_agent.py unchanged: only validated SELECT statements, run as
`viewer` inside a READ ONLY transaction.

Runs on an Anthropic API key (pay per use). Token usage is logged per user
to webapp/data/usage.jsonl and capped per question, per user per day, and
for the whole site per day.

Environment (normally from ~/.config/macdb-web/env):
    ANTHROPIC_API_KEY             required
    MACDB_WEB_PASSWORD            shared lab password; leave empty for no sign-in
                                  (then usage is tracked and capped per IP)
    MACDB_WEB_SECRET              optional, cookie signing key (random if unset:
                                  everyone is signed out on restart)
    MACDB_WEB_HOST / _PORT        default 127.0.0.1 / 8510
    MACDB_WEB_USER_DAILY_TOKENS   default 1,000,000 per user per day
    MACDB_WEB_DAILY_TOKENS        default 5,000,000 for the site per day
    MAC_AGENT_MODEL               default claude-haiku-5-5 (from nl_query_agent)

Run:
    venv/bin/python webapp/server.py
"""

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sys
import time
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import anthropic  # noqa: E402
import asyncpg  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import (  # noqa: E402
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response,
    StreamingResponse,
)

import nl_query_agent as base  # noqa: E402
import plotting  # noqa: E402

# ----------------------------------------
# Configuration
# ----------------------------------------
PASSWORD = os.getenv("MACDB_WEB_PASSWORD", "")
SECRET = (os.getenv("MACDB_WEB_SECRET") or secrets.token_hex(32)).encode()
HOST = os.getenv("MACDB_WEB_HOST", "127.0.0.1")
PORT = int(os.getenv("MACDB_WEB_PORT", "8510"))
USER_DAILY_TOKENS = int(os.getenv("MACDB_WEB_USER_DAILY_TOKENS", "1000000"))
SITE_DAILY_TOKENS = int(os.getenv("MACDB_WEB_DAILY_TOKENS", "5000000"))
MAX_HISTORY_QUESTIONS = 8        # earlier questions are dropped from context
SESSION_IDLE_S = 3 * 3600        # conversations forgotten after 3 h idle
COOKIE = "macdb_session"
COOKIE_MAX_AGE = 14 * 86400
MAX_QUESTION_CHARS = 2000

DATA_DIR = os.path.join(HERE, "data")
USAGE_LOG = os.path.join(DATA_DIR, "usage.jsonl")
INDEX_HTML = os.path.join(HERE, "static", "index.html")
CHART_DIR = os.path.join(DATA_DIR, "charts")
PLOT_MAX_ROWS = 20000

AUTH = bool(PASSWORD)  # no password set: open site, users tracked by IP

CLIENT = anthropic.AsyncAnthropic() if os.getenv("ANTHROPIC_API_KEY") else None
DB = base.Database(base.resolve_db_password())

# The CLI tool description and prompt talk about a terminal; adapt for the web.
RUN_SQL_TOOL = dict(base.RUN_SQL_TOOL)
RUN_SQL_TOOL["description"] = RUN_SQL_TOOL["description"].replace(
    "printed directly to the user's terminal", "shown directly to the user on the web page"
)
PROMPT_EDITS = [
    ("each image is automatically saved to agent_plots/ and the result shows its file "
     "path — point the user to those paths in your answer.",
     "each image is automatically displayed to the user on the web page next to its "
     "row — say the plot is shown above; do not list file paths."),
]
WEB_ADDENDUM = """

Web interface notes (these take precedence over earlier wording about terminals or files):
- You are answering through a shared lab web page. Every query you run and its full result \
table, including any plots, is displayed to the user directly above your reply.
- Keep replies short and well formatted with Markdown (short lists, bold key numbers).
- You can draw charts with the make_plot tool. Use it whenever the user asks for a plot, \
graph, chart, histogram, distribution, trend, or comparison over time, and offer it when a \
picture would clearly help. Its SQL should return just the needed columns, with aggregation \
done in SQL (e.g. date_trunc('week', ...) with COUNT(*) for counts per week). For per-channel \
array columns, expand them with unnest(...) WITH ORDINALITY to get (channel, value) rows. \
Stored images (hexplots etc.) are not charts: fetch those with run_sql as before. \
For strongly skewed distributions (e.g. leakage currents) set logy. Use kind 'box' to compare distributions across \
categories, stacked=true for stacked bars. For counts over time, make x a date column (date_trunc(...)::date) so empty periods show as gaps.
- After make_plot, the chart is already displayed; describe in a sentence or two what it \
shows using the numbers in the tool result, flag outliers as usual, and do not speculate \
about causes. If make_plot returns an error, fix the spec or query and try again.
- Today's date is {today}."""


# ----------------------------------------
# Signed session cookie (name + session id)
# ----------------------------------------
def _sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_cookie(name: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"n": name, "s": secrets.token_hex(12), "t": int(time.time())}).encode()
    ).decode()
    return f"{payload}.{_sign(payload)}"


def read_cookie(request: Request):
    raw = request.cookies.get(COOKIE, "")
    payload, _, sig = raw.rpartition(".")
    if not payload or not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except ValueError:
        return None
    if time.time() - data.get("t", 0) > COOKIE_MAX_AGE:
        return None
    return data


# Failed-login throttle per client address
FAILED_LOGINS: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    # uvicorn (proxy_headers, forwarded_allow_ips=127.0.0.1) already resolves the
    # real client from X-Forwarded-For, skipping the trusted nginx hop. Reading the
    # header's first entry ourselves would trust whatever the client sent.
    return request.client.host if request.client else "?"


def user_name(who: dict, request: Request) -> str:
    """Name used for usage caps and the log."""
    return who["n"] if AUTH else f"guest@{client_ip(request)}"


def login_blocked(ip: str) -> bool:
    recent = [t for t in FAILED_LOGINS.get(ip, []) if time.time() - t < 600]
    FAILED_LOGINS[ip] = recent
    return len(recent) >= 10


# ----------------------------------------
# Conversations and token accounting
# ----------------------------------------
class Session:
    def __init__(self):
        self.messages: list = []
        self.lock = asyncio.Lock()
        self.last_seen = time.time()


SESSIONS: dict[str, Session] = {}
USAGE_TODAY = {"day": date.today().isoformat(), "site": 0, "users": {}}


def _roll_day():
    today = date.today().isoformat()
    if USAGE_TODAY["day"] != today:
        USAGE_TODAY.update(day=today, site=0, users={})


def load_usage_log():
    """Rebuild today's totals from the log so caps survive restarts."""
    if not os.path.exists(USAGE_LOG):
        return
    today = date.today().isoformat()
    with open(USAGE_LOG) as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("ts", "").startswith(today):
                add_usage(rec.get("user", "?"), int(rec.get("tokens", 0)))


def add_usage(user: str, tokens: int):
    _roll_day()
    USAGE_TODAY["site"] += tokens
    key = user.lower()
    USAGE_TODAY["users"][key] = USAGE_TODAY["users"].get(key, 0) + tokens


def cap_message(user: str):
    _roll_day()
    if USAGE_TODAY["site"] >= SITE_DAILY_TOKENS:
        return ("The site's daily usage limit has been reached. "
                "Please try again tomorrow.")
    if USAGE_TODAY["users"].get(user.lower(), 0) >= USER_DAILY_TOKENS:
        return ("You have reached your daily usage limit. "
                "Please try again tomorrow.")
    return None


def log_question(user, ip, question, tokens, n_queries, status):
    os.makedirs(DATA_DIR, exist_ok=True)
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "user": user, "ip": ip,
           "question": question, "tokens": tokens, "queries": n_queries,
           "status": status, "model": base.MODEL}
    with open(USAGE_LOG, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def trim_history(messages: list):
    """Keep only the last MAX_HISTORY_QUESTIONS question/answer exchanges.
    Cuts only at plain-text user questions, so tool_use/tool_result pairs
    stay intact."""
    starts = [i for i, m in enumerate(messages)
              if m["role"] == "user" and isinstance(m["content"], str)]
    if len(starts) > MAX_HISTORY_QUESTIONS:
        del messages[: starts[-MAX_HISTORY_QUESTIONS]]


# ----------------------------------------
# System prompt (schema refreshed daily)
# ----------------------------------------
PROMPT_CACHE = {"day": None, "system": None}


async def system_blocks():
    today = date.today().isoformat()
    if PROMPT_CACHE["day"] != today:
        prompt = base.build_system_prompt(await DB.schema_text())
        for old, new in PROMPT_EDITS:
            if old not in prompt:
                print(f"[warn] prompt text not found, not adapted: {old[:50]}...")
            prompt = prompt.replace(old, new)
        prompt += WEB_ADDENDUM.format(today=today)
        PROMPT_CACHE.update(day=today, system=[
            {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}
        ])
    return PROMPT_CACHE["system"]


# ----------------------------------------
# Agent loop, emitting live events
# ----------------------------------------
PLACEHOLDER = re.compile(r"<(\w+) (image|file), (\d+) kB -> ([^>]+)>")


def webify(cell: str):
    """Turn saved-file placeholders from materialize() into plot links."""
    found = PLACEHOLDER.findall(cell)
    if not found:
        return cell
    return {"files": [
        {"url": "plots/" + os.path.basename(path), "ext": ext, "kb": int(kb),
         "image": kind == "image"}
        for ext, kind, kb, path in found
    ]}


async def fetch_rows(sql: str, limit: int):
    """Like base.Database.run (same read-only connection settings), with a
    custom row limit for plotting."""
    conn = await asyncpg.connect(**DB._conn_kwargs)
    try:
        async with conn.transaction(readonly=True):
            stmt = await conn.prepare(sql)
            columns = [a.name for a in stmt.get_attributes()]
            cursor = await stmt.cursor()
            rows = await cursor.fetch(limit + 1)
    finally:
        await conn.close()
    return columns, rows[:limit], len(rows) > limit


async def handle_plot(spec, emit) -> tuple[str, bool]:
    """Run one make_plot call. Returns (text for the model, whether it ran)."""
    sql = spec.get("sql", "")
    try:
        cleaned = base.validate_sql(sql)
    except ValueError as err:
        await emit({"type": "rejected", "reason": str(err)})
        return f"Query rejected by read-only validator: {err}", False
    try:
        columns, rows, truncated = await fetch_rows(cleaned, PLOT_MAX_ROWS)
    except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as err:
        await emit({"type": "db_error", "error": str(err)})
        return f"Database error: {err}", False
    try:
        path, summary = await asyncio.to_thread(
            plotting.render_chart, columns, rows, spec, CHART_DIR)
    except ValueError as err:
        await emit({"type": "notice", "text": f"Chart not drawn (the agent will retry): {err}"})
        return f"make_plot error: {err}", False
    display = base.materialize(columns, rows[: base.MAX_ROWS])
    await emit({
        "type": "chart", "url": "charts/" + os.path.basename(path),
        "title": spec.get("title", ""), "sql": cleaned, "columns": columns,
        "n_rows": len(rows), "truncated": truncated, "max_rows": base.MAX_ROWS,
        "rows": [[webify(r[c]) for c in columns] for r in display],
    })
    note = f" (truncated at {PLOT_MAX_ROWS} rows)" if truncated else ""
    return (f"Chart drawn and displayed to the user from {len(rows)} rows{note}.\n"
            f"Plotted series:\n{summary}"), True


async def handle_tool(name, tool_input, emit) -> tuple[str, bool]:
    """Run one tool call. Returns (text for the model, whether it ran)."""
    if name == "make_plot":
        return await handle_plot(tool_input, emit)
    sql = tool_input.get("sql", "")
    try:
        cleaned = base.validate_sql(sql)
    except ValueError as err:
        await emit({"type": "rejected", "reason": str(err)})
        return f"Query rejected by read-only validator: {err}", False
    await emit({"type": "sql", "sql": cleaned})
    try:
        columns, rows, truncated = await DB.run(cleaned)
    except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as err:
        await emit({"type": "db_error", "error": str(err)})
        return f"Database error: {err}", False
    display = base.materialize(columns, rows)
    await emit({
        "type": "table", "columns": columns, "truncated": truncated,
        "max_rows": base.MAX_ROWS,
        "rows": [[webify(r[c]) for c in columns] for r in display],
    })
    text = base.rows_for_model(columns, display, truncated, shown=True)
    return text.replace("in their terminal", "on the web page"), True


async def run_question(sess: Session, user: str, ip: str, question: str, emit):
    messages = sess.messages
    start = len(messages)
    tokens, n_queries, status = 0, 0, "ok"
    try:
        system = await system_blocks()
        messages.append({"role": "user", "content": question})
        for _ in range(base.MAX_TOOL_TURNS):
            async with CLIENT.messages.stream(
                model=base.MODEL, max_tokens=1500, system=system,
                tools=[RUN_SQL_TOOL, plotting.PLOT_TOOL], messages=messages,
            ) as stream:
                async for event in stream:
                    if event.type == "text":
                        await emit({"type": "delta", "text": event.text})
                final = await stream.get_final_message()
            step = base.count_usage_tokens(final.usage)
            tokens += step
            add_usage(user, step)
            messages.append({"role": "assistant", "content": final.content})
            text = "".join(b.text for b in final.content if b.type == "text")
            # replaces the streamed text with the checked, final version
            await emit({"type": "text_done", "text": base.scrub_reply(text)})
            if final.stop_reason != "tool_use":
                return
            results = []
            for block in final.content:
                if block.type == "tool_use":
                    result_text, ran = await handle_tool(block.name, block.input, emit)
                    n_queries += ran
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": result_text})
            messages.append({"role": "user", "content": results})
            stop = None
            if tokens >= base.QUERY_TOKEN_CAP:
                stop = ("Stopped: this question hit its usage limit. "
                        "Try asking something narrower.")
            stop = stop or cap_message(user)
            if stop:
                status = "capped"
                await emit({"type": "notice", "text": stop})
                del messages[start:]
                return
        status = "too_many_queries"
        await emit({"type": "notice",
                    "text": "Stopped: too many query attempts for one question."})
        del messages[start:]
    except asyncio.CancelledError:
        status = "cancelled"
        del messages[start:]
        raise
    except anthropic.APIError as err:
        status = "api_error"
        await emit({"type": "error", "text": f"Claude API error: {err}"})
        del messages[start:]
    except (asyncpg.PostgresError, OSError) as err:
        status = "db_error"
        await emit({"type": "error", "text": f"Database connection error: {err}"})
        del messages[start:]
    except Exception as err:  # never leave the browser hanging
        status = "error"
        print(f"[error] {type(err).__name__}: {err}")
        await emit({"type": "error", "text": f"Unexpected server error: {type(err).__name__}"})
        del messages[start:]
    finally:
        trim_history(messages)
        log_question(user, ip, question, tokens, n_queries, status)
        try:
            await emit({"type": "usage", "tokens": tokens,
                        "user_today": USAGE_TODAY["users"].get(user.lower(), 0),
                        "user_cap": USER_DAILY_TOKENS})
        except Exception:
            pass


# ----------------------------------------
# Web routes
# ----------------------------------------
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def login_page(error: str = "") -> HTMLResponse:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(LOGIN_HTML.replace("{{ERROR}}", err))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    page = FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})
    if not read_cookie(request):
        if AUTH:
            return login_page()
        # open site: hand out an anonymous session for conversation memory
        page.set_cookie(COOKIE, make_cookie("Guest"), max_age=COOKIE_MAX_AGE,
                        httponly=True, samesite="lax")
    return page


@app.post("/login")
async def login(request: Request, name: str = Form(""), password: str = Form("")):
    if not AUTH:
        return RedirectResponse("./", status_code=303)
    ip = client_ip(request)
    if login_blocked(ip):
        return login_page("Too many failed attempts. Try again in a few minutes.")
    name = re.sub(r"\s+", " ", name).strip()[:40]
    if not name:
        return login_page("Please enter your name.")
    if not hmac.compare_digest(password.encode(), PASSWORD.encode()):
        FAILED_LOGINS.setdefault(ip, []).append(time.time())
        return login_page("Wrong lab password.")
    resp = RedirectResponse("./", status_code=303)
    resp.set_cookie(COOKIE, make_cookie(name), max_age=COOKIE_MAX_AGE,
                    httponly=True, samesite="lax")
    return resp


@app.post("/logout")
async def logout():
    resp = RedirectResponse("./", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/api/me")
async def me(request: Request):
    who = read_cookie(request)
    if not who:
        return JSONResponse({"error": "signed out"}, status_code=401)
    _roll_day()
    return {"name": who["n"], "auth": AUTH, "model": base.MODEL,
            "db": base.CONFIG.get("dbname", ""),
            "ready": CLIENT is not None,
            "user_today": USAGE_TODAY["users"].get(user_name(who, request).lower(), 0),
            "user_cap": USER_DAILY_TOKENS}


@app.post("/api/reset")
async def reset(request: Request):
    who = read_cookie(request)
    if not who:
        return JSONResponse({"error": "signed out"}, status_code=401)
    SESSIONS.pop(who["s"], None)
    return {"ok": True}


@app.post("/api/ask")
async def ask(request: Request):
    who = read_cookie(request)
    if not who:
        return JSONResponse({"error": "Signed out. Reload the page."}, status_code=401)
    if not request.headers.get("content-type", "").startswith("application/json"):
        return JSONResponse({"error": "Bad request."}, status_code=400)
    body = await request.json()
    question = str(body.get("question", "")).strip()[:MAX_QUESTION_CHARS]
    if not question:
        return JSONResponse({"error": "Empty question."}, status_code=400)
    if CLIENT is None:
        return JSONResponse({"error": "The server has no ANTHROPIC_API_KEY configured."},
                            status_code=503)
    user = user_name(who, request)
    capped = cap_message(user)
    if capped:
        return JSONResponse({"error": capped}, status_code=429)

    # forget idle conversations
    now = time.time()
    for sid in [s for s, v in SESSIONS.items() if now - v.last_seen > SESSION_IDLE_S]:
        SESSIONS.pop(sid, None)
    sess = SESSIONS.setdefault(who["s"], Session())
    sess.last_seen = now
    if sess.lock.locked():
        return JSONResponse({"error": "Still answering your previous question."},
                            status_code=409)

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event):
        await queue.put(json.dumps(event, default=str) + "\n")

    async def worker():
        try:
            async with sess.lock:
                await run_question(sess, user, client_ip(request), question, emit)
        finally:
            await queue.put(None)

    task = asyncio.create_task(worker())

    async def stream():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():  # browser went away: stop spending tokens
                task.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ----------------------------------------
# Quick links (fixed read-only SQL from upstream web_ui.py, no model tokens)
# ----------------------------------------
async def fetch_all(sql: str):
    conn = await asyncpg.connect(**DB._conn_kwargs)
    try:
        async with conn.transaction(readonly=True):
            return await conn.fetch(sql)
    finally:
        await conn.close()


@app.get("/api/env_plot")
async def env_plot(request: Request, source: str = "lab", hours: int = 6):
    if not read_cookie(request):
        return JSONResponse({"error": "signed out"}, status_code=401)
    hours = min(max(int(hours), 1), 48)
    if source == "lab":
        rows = await fetch_all(f"""
            SELECT date_trunc('minute', log_timestamp) AS t, log_location AS loc,
                   avg(temp_c) AS temp, avg(rel_hum) AS rh
            FROM temp_humidity
            WHERE log_timestamp > now() - interval '{hours} hours'
            GROUP BY 1, 2 ORDER BY 1""")
    else:
        source = "mmts"
        rows = await fetch_all(f"""
            SELECT date_trunc('minute', log_timestamp) AS t, device_name AS dev,
                   metric, avg(value) AS v
            FROM mmts_sensors_logging
            WHERE metric IN ('temperature_C', 'dewpoint_C')
              AND log_timestamp > now() - interval '{hours} hours'
            GROUP BY 1, 2, 3 ORDER BY 1""")
    png = await asyncio.to_thread(plotting.render_env, source, rows, hours)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/production")
async def production(request: Request):
    if not read_cookie(request):
        return JSONResponse({"error": "signed out"}, status_code=401)
    rows = await fetch_all("""
        WITH latest AS (
          SELECT DISTINCT ON (q.module_no) q.module_no, q.final_grade
          FROM module_qc_summary q
          ORDER BY q.module_no, q.grade_timestamp DESC NULLS LAST, q.mod_qc_no DESC
        )
        SELECT left(m.module_name, 9) AS type,
          count(*) AS total,
          count(*) FILTER (WHERE l.final_grade = 'A') AS "A",
          count(*) FILTER (WHERE l.final_grade = 'B') AS "B",
          count(*) FILTER (WHERE l.final_grade = 'C') AS "C",
          count(*) FILTER (WHERE l.final_grade = 'F') AS "F",
          count(*) FILTER (WHERE l.module_no IS NOT NULL AND l.final_grade IS NULL) AS "no grade",
          count(*) FILTER (WHERE l.module_no IS NULL) AS ungraded
        FROM module_info m LEFT JOIN latest l USING (module_no)
        GROUP BY 1 ORDER BY total DESC""")
    columns = ["type", "total", "A", "B", "C", "F", "no grade", "ungraded"] if rows else []
    return {"columns": columns, "rows": [[str(r[c]) for c in columns] for r in rows]}


@app.get("/charts/{name}")
async def chart(name: str, request: Request):
    if not read_cookie(request):
        return JSONResponse({"error": "signed out"}, status_code=401)
    path = os.path.join(CHART_DIR, os.path.basename(name))
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


@app.get("/plots/{name}")
async def plot(name: str, request: Request):
    if not read_cookie(request):
        return JSONResponse({"error": "signed out"}, status_code=401)
    path = os.path.join(base.PLOTS_DIR, os.path.basename(name))
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


LOGIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MAC-BOT Dobby</title>
<style>
:root{color-scheme:light;--bg:#eef7f1;--panel:#fff;--accent:#5fae8d;--accent-soft:#c4e5d5;--text:#2f473c;--muted:#7fa191;--border:#ddeee4;--warn:#fdf0dc;--warn-text:#a8793a}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font:15px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;padding:16px}
form{background:var(--panel);border:1px solid var(--border);border-radius:24px;padding:28px;width:100%;max-width:360px;box-shadow:0 4px 16px rgba(60,50,90,.07)}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.logo{width:38px;height:38px;border-radius:14px;background:var(--accent-soft);color:var(--accent);display:flex;align-items:center;justify-content:center;font-size:20px}
h1{font-size:16px;margin:0;font-weight:650}p{margin:0;color:var(--muted);font-size:12px}
label{display:block;font-size:12.5px;font-weight:600;margin:12px 0 4px}
input{width:100%;padding:9px 14px;border:1px solid var(--border);border-radius:14px;background:var(--bg);color:var(--text);font:inherit;outline:none}
input:focus{border-color:var(--accent)}
button{margin-top:18px;width:100%;padding:10px;border:0;border-radius:16px;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer}
.err{color:var(--warn-text);background:var(--warn);border-radius:12px;padding:6px 12px;margin:12px 0 0;font-size:12.5px}
</style></head><body>
<form method="post" action="login">
<div class="brand"><div class="logo">⬡</div><div><h1>MAC-BOT Dobby</h1><p>TTU MAC database · read-only</p></div></div>
<label for="name">Your name</label><input id="name" name="name" autocomplete="name" required maxlength="40">
<label for="pw">Lab password</label><input id="pw" name="password" type="password" required>
<button>Sign in</button>{{ERROR}}
</form></body></html>"""


if __name__ == "__main__":
    load_usage_log()
    plotting.cleanup(CHART_DIR)
    if CLIENT is None:
        print("[warn] ANTHROPIC_API_KEY not set: the site will load but cannot answer.")
    print(f"MAC database Q&A on http://{HOST}:{PORT}/ (model {base.MODEL})")
    uvicorn.run(app, host=HOST, port=PORT, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1", log_level="info")
