"""
Chart rendering for the MAC database web agent.

The model never writes plotting code: it sends a small declarative spec
(chart kind + which result columns go where), validated here and drawn with
matplotlib's object API (no pyplot, so it is safe to call from a thread).
"""

import os
import secrets
import time
from datetime import date, datetime
from decimal import Decimal

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

KINDS = ("bar", "line", "scatter", "hist", "box")
MAX_SERIES = 40
MAX_BAR_CATEGORIES = 150
PALETTE = ["#2f6db5", "#d1495b", "#3a9d5d", "#e39b2d", "#7b5ea7", "#2aa1a6",
           "#8c6d46", "#c55a9c", "#5b6770", "#9bb83a", "#d97b45", "#4e79a7"]

PLOT_TOOL = {
    # Same name and option names as nl_query_agent.MAKE_PLOT_TOOL, so the shared
    # system prompt's sketching rules apply; plus box charts, stacked bars,
    # several y columns, and a real date axis.
    "name": "make_plot",
    "description": (
        "Sketch a plot from a read-only SELECT and show it to the user on the web page. "
        "The query is validated and run like run_sql (up to 20,000 rows for plotting). "
        "Return tidy columns, one row per point, and do aggregation (GROUP BY, "
        "date_trunc, width_bucket) in SQL where sensible. Kinds: 'line', 'scatter', "
        "'bar' (categories or dates on x; stacked=true to stack series), 'hist' "
        "(distribution of y; x unused), 'box' (distribution of y per x category). "
        "Use series to get one line/bar group per value of that column."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "SELECT returning the data to plot."},
            "kind": {"type": "string", "enum": list(KINDS)},
            "x": {"type": "string", "description": "x column (not needed for hist)."},
            "y": {"anyOf": [{"type": "string"},
                            {"type": "array", "items": {"type": "string"}}],
                  "description": "y column (values column for hist); a list of "
                                 "columns plots several y columns."},
            "series": {"type": "string",
                       "description": "Optional column: one series per distinct value."},
            "title": {"type": "string"},
            "xlabel": {"type": "string"},
            "ylabel": {"type": "string"},
            "logx": {"type": "boolean"},
            "logy": {"type": "boolean"},
            "xmin": {"type": "number"},
            "xmax": {"type": "number"},
            "ymin": {"type": "number"},
            "ymax": {"type": "number"},
            "stacked": {"type": "boolean", "description": "Stack bars (bar only)."},
            "bins": {"type": "integer", "description": "Histogram bins (default 30)."},
        },
        "required": ["sql", "kind", "y"],
    },
}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, Decimal):
        return float(v)
    return "bad"


def _numeric_column(rows, col):
    out = []
    for r in rows:
        v = _num(r[col])
        if v == "bad":
            raise ValueError(
                f"Column {col!r} is not numeric (found {type(r[col]).__name__} value "
                f"{str(r[col])[:40]!r}). Cast or aggregate it in SQL, or use a different column."
            )
        out.append(v)
    return out


def _x_values(rows, col):
    """Return (values, kind) with kind in {'num', 'date', 'cat'}."""
    vals = [r[col] for r in rows]
    present = [v for v in vals if v is not None]
    if present and all(isinstance(v, (date, datetime)) for v in present):
        return vals, "date"
    if present and all(_num(v) not in (None, "bad") for v in present):
        return [_num(v) for v in vals], "num"
    return ["∅" if v is None else str(v) for v in vals], "cat"


def _groups(rows, group_by):
    if not group_by:
        return [(None, rows)]
    order, buckets = [], {}
    for r in rows:
        key = "∅" if r[group_by] is None else str(r[group_by])
        if key not in buckets:
            order.append(key)
            buckets[key] = []
        buckets[key].append(r)
    if len(order) > MAX_SERIES:
        raise ValueError(
            f"series column {group_by!r} has {len(order)} distinct values; at most "
            f"{MAX_SERIES} series fit in one chart. Filter or bucket it in SQL."
        )
    try:  # numeric groups in numeric order, else alphabetical
        order.sort(key=float)
    except ValueError:
        order.sort()
    return [(k, buckets[k]) for k in order]


def _fmt(v):
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def render_chart(columns, rows, spec, out_dir):
    """Draw the chart. Returns (png_path, summary_for_model).
    Raises ValueError with a model-readable message for a bad spec."""
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}.")
    # PostgreSQL lowercases unquoted aliases: match column names ignoring case
    by_lower = {c.lower(): c for c in columns}
    fix = lambda c: by_lower.get(c.lower(), c) if isinstance(c, str) and c else c  # noqa: E731
    ys = spec.get("y") or []
    if isinstance(ys, str):
        ys = [ys]
    ys = [fix(c) for c in ys]
    x = fix(spec.get("x"))
    group_by = fix(spec.get("series") or spec.get("group_by"))
    x_label = spec.get("xlabel") or spec.get("x_label")
    y_label = spec.get("ylabel") or spec.get("y_label")
    needed = list(ys) + ([x] if x and kind != "hist" else []) + ([group_by] if group_by else [])
    missing = [c for c in needed if c not in columns]
    if missing:
        raise ValueError(f"Columns {missing} are not in the query result {columns}.")
    if not ys:
        raise ValueError("Give at least one y column.")
    if kind != "hist" and not x:
        raise ValueError(f"A {kind} chart needs an x column.")
    if kind == "box" and len(ys) != 1:
        raise ValueError("A box chart takes exactly one y column (categories go on x).")
    if group_by and len(ys) > 1 and kind != "hist":
        raise ValueError("Use either several y columns or series, not both.")
    if not rows:
        raise ValueError("The query returned no rows, so there is nothing to plot.")

    fig = Figure(figsize=(9, 4.8), dpi=110, layout="constrained")
    ax = fig.add_subplot()
    ax.grid(True, alpha=0.3)
    ax.set_axisbelow(True)
    groups = _groups(rows, group_by)
    series = []  # (label, x_list, y_list)
    for gname, grows in groups:
        for ycol in ys:
            label = gname if gname is not None else (ycol if len(ys) > 1 else None)
            series.append((label, grows, ycol))
    if len(series) > MAX_SERIES:
        raise ValueError(f"That is {len(series)} series; at most {MAX_SERIES} fit in one chart.")

    summary = []
    xkind = None
    if len(series) > len(PALETTE):
        cmap = matplotlib.colormaps["turbo"]
        colors = [matplotlib.colors.to_hex(cmap(0.05 + 0.9 * i / (len(series) - 1)))
                  for i in range(len(series))]
    else:
        colors = PALETTE
    if kind == "hist":
        bins = max(5, min(int(spec.get("bins") or 30), 200))
        for i, (label, grows, ycol) in enumerate(series):
            vals = [v for v in _numeric_column(grows, ycol) if v is not None]
            if not vals:
                continue
            ax.hist(vals, bins=bins, alpha=0.55 if len(series) > 1 else 0.9,
                    color=colors[i], label=label, edgecolor="white", linewidth=0.4)
            summary.append(f"{label or ycol}: n={len(vals)}, min={_fmt(min(vals))}, "
                           f"max={_fmt(max(vals))}, mean={_fmt(sum(vals) / len(vals))}")
        ax.set_ylabel(y_label or "count")
        ax.set_xlabel(x_label or (ys[0] if len(ys) == 1 else "value"))
    elif kind == "box":
        xs, xkind = _x_values(rows, x)
        yvals = _numeric_column(rows, ys[0])
        cats = {}
        for xv, yv in zip(xs, yvals):
            if yv is not None:
                cats.setdefault(str(xv), []).append(yv)
        if len(cats) > MAX_BAR_CATEGORIES:
            raise ValueError(f"{len(cats)} categories is too many for a box chart.")
        names = list(cats)
        try:  # numeric categories in numeric order, else alphabetical
            names.sort(key=float)
        except ValueError:
            names.sort()
        ax.boxplot([cats[n] for n in names], tick_labels=names, patch_artist=True,
                   boxprops={"facecolor": PALETTE[0], "alpha": 0.35},
                   medianprops={"color": PALETTE[1]})
        for n in names:
            v = sorted(cats[n])
            summary.append(f"{n}: n={len(v)}, median={_fmt(v[len(v) // 2])}, "
                           f"min={_fmt(v[0])}, max={_fmt(v[-1])}")
        ax.set_xlabel(x_label or x)
        ax.set_ylabel(y_label or ys[0])
        if len(names) > 8:
            ax.tick_params(axis="x", labelrotation=45)
    else:
        xs_all, xkind = _x_values(rows, x)
        if kind == "scatter" and xkind == "cat":
            raise ValueError(f"Scatter needs a numeric or date x column; {x!r} is categorical.")
        if kind == "bar":
            cats = list(dict.fromkeys(xs_all))
            if xkind == "date":
                cats = sorted(c for c in cats if c is not None)
            if len(cats) > MAX_BAR_CATEGORIES:
                raise ValueError(f"{len(cats)} bar categories is too many; aggregate in SQL.")
            if xkind == "date":
                labels = [v.isoformat()[:10] for v in cats]
                # real time axis, so empty periods show as gaps
                xpos = list(mdates.date2num(cats))
                gaps = [b - a for a, b in zip(xpos, xpos[1:]) if b > a]
                slot = min(gaps) if gaps else 1.0
            else:
                labels = [_fmt(v) for v in cats]
                xpos, slot = list(range(len(cats))), 1.0
            pos = {c: i for i, c in enumerate(cats)}
            n = len(series)
            stacked = bool(spec.get("stacked")) and n > 1
            width = (0.8 if stacked or n == 1 else 0.8 / n) * slot
            bottom = [0.0] * len(cats)
            for i, (label, grows, ycol) in enumerate(series):
                gx, _ = _x_values(grows, x)
                gy = _numeric_column(grows, ycol)
                heights = [0.0] * len(cats)
                for xv, yv in zip(gx, gy):
                    if yv is not None and xv in pos:
                        heights[pos[xv]] += yv
                offs = 0 if stacked or n == 1 else (i - (n - 1) / 2) * width
                ax.bar([p + offs for p in xpos], heights, width,
                       bottom=bottom if stacked else None, label=label,
                       color=colors[i])
                if stacked:
                    bottom = [b + h for b, h in zip(bottom, heights)]
                summary.append(f"{label or ycol}: total={_fmt(sum(heights))}, "
                               f"max={_fmt(max(heights))} at {labels[heights.index(max(heights))]}")
            if xkind == "date":
                loc = mdates.AutoDateLocator(maxticks=14)
                ax.xaxis.set_major_locator(loc)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
            else:
                ax.set_xticks(xpos, labels)
            if xkind != "date" and (len(cats) > 8 or max(len(s) for s in labels) > 8):
                ax.tick_params(axis="x", labelrotation=60)
                for t in ax.get_xticklabels():
                    t.set_horizontalalignment("right")
        else:
            for i, (label, grows, ycol) in enumerate(series):
                gx, _ = _x_values(grows, x)
                gy = _numeric_column(grows, ycol)
                pts = [(a, b) for a, b in zip(gx, gy) if a is not None and b is not None]
                if kind == "line" and xkind != "cat":
                    pts.sort(key=lambda p: p[0])
                if not pts:
                    continue
                px, py = zip(*pts)
                color = colors[i]
                if kind == "line":
                    ax.plot(px, py, marker="o" if len(pts) <= 60 else None, markersize=3.5,
                            linewidth=1.6, label=label, color=color)
                else:
                    ax.scatter(px, py, s=14 if len(pts) > 300 else 24, alpha=0.75,
                               label=label, color=color, edgecolors="none")
                summary.append(f"{label or ycol}: n={len(pts)}, y min={_fmt(min(py))}, "
                               f"y max={_fmt(max(py))}, x from {_fmt(px[0]) if kind == 'line' else _fmt(min(px))} "
                               f"to {_fmt(px[-1]) if kind == 'line' else _fmt(max(px))}")
            if xkind == "date":
                fig.autofmt_xdate()
            elif xkind == "cat":
                ax.tick_params(axis="x", labelrotation=45)
        ax.set_xlabel(x_label or x)
        ax.set_ylabel(y_label or (ys[0] if len(ys) == 1 else "value"))

    if not summary:
        raise ValueError("All plotted values are NULL, so there is nothing to draw.")
    if spec.get("logy") or spec.get("log_y"):
        ax.set_yscale("log")
    if spec.get("logx") and kind in ("line", "scatter"):
        ax.set_xscale("log")
    numeric_x = kind == "hist" or (kind in ("line", "scatter") and xkind == "num")
    if numeric_x and (spec.get("xmin") is not None or spec.get("xmax") is not None):
        ax.set_xlim(spec.get("xmin"), spec.get("xmax"))
    if spec.get("ymin") is not None or spec.get("ymax") is not None:
        ax.set_ylim(spec.get("ymin"), spec.get("ymax"))
    if any(s[0] for s in series):
        if len(series) > 8:
            ax.legend(title=group_by, fontsize=8, title_fontsize=8, frameon=False,
                      loc="upper left", bbox_to_anchor=(1.01, 1),
                      ncol=1 if len(series) <= 20 else 2)
        else:
            ax.legend(title=group_by if group_by else None, fontsize=9, title_fontsize=9,
                      loc="best", frameon=False)
    ax.set_title(spec.get("title") or "", fontsize=12, loc="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"chart_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}.png")
    fig.savefig(path, facecolor="white")
    return path, "\n".join(summary)


def cleanup(out_dir, max_age_days=30):
    """Delete charts older than max_age_days."""
    if not os.path.isdir(out_dir):
        return
    cutoff = time.time() - max_age_days * 86400
    for name in os.listdir(out_dir):
        p = os.path.join(out_dir, name)
        if name.startswith("chart_") and os.path.getmtime(p) < cutoff:
            os.remove(p)


def render_env(source, rows, hours):
    """Quick-link plot of lab or MMTS environment (ported from web_ui.py,
    using the object API so concurrent requests are safe). Returns PNG bytes."""
    import io
    if source == "lab":
        panels = [("Temperature (°C)", "temp"), ("Relative humidity (%)", "rh")]
        key, suptitle = "loc", f"Lab environment — past {hours} h"
    else:
        panels = [("Temperature (°C)", "temperature_C"), ("Dew point (°C)", "dewpoint_C")]
        key, suptitle = "dev", f"MMTS environment — past {hours} h"
    fig = Figure(figsize=(9, 6), dpi=110, layout="constrained")
    axes = fig.subplots(len(panels), 1, sharex=True)
    for ax, (label, sel) in zip(axes, panels):
        groups = {}
        for r in rows:
            if source == "lab":
                val = r[sel]
            else:
                if r["metric"] != sel:
                    continue
                val = r["v"]
            if val is not None:
                groups.setdefault(r[key], []).append((r["t"], float(val)))
        for name in sorted(groups, key=str):
            pts = groups[name]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], linewidth=1.2, label=name)
        ax.set_ylabel(label, fontsize=9)
        ax.grid(alpha=0.25)
        loc = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
        if groups:
            ax.legend(fontsize=7, frameon=False, loc="upper left", ncol=max(1, len(groups) // 6))
        else:
            ax.text(0.5, 0.5, "no data in window", transform=ax.transAxes, ha="center", color="#999")
    fig.suptitle(suptitle, fontsize=11)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    return buf.getvalue()
