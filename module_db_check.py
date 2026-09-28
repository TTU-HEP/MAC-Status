#!/usr/bin/env python3
"""
module_db_check.py -- validate module names from a CSV column against PostgreSQL.

Designed to be imported as a plugin (call `run()` or the lower-level pieces)
or executed directly from the command line.

Checks, for every entry in the chosen CSV column:
  1. it exists in `module_info.module_name`           (required)
  2. it exists in each of the "presence" tables       (module_qc_summary,
     module_inspect, module_iv_test, module_pedestal_test)

Only dependency: psycopg2 (psycopg2-binary is fine).

Plugin usage
------------
    from module_db_check import run
    ok, report, results = run("modules.csv", "module_name",
                              dbname="ttu_mac_local", host="localhost",
                              user="postgres")
    print(report)

CLI usage
---------
    python module_db_check.py modules.csv module_name --dbname ttu_mac_local
    python module_db_check.py modules.csv 0 --dsn "postgresql://user@host/ttu_mac_local"
    python module_db_check.py bare_list.csv 0 --no-header

Connection parameters not given explicitly fall back to the standard libpq
environment variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE, ...).
"""

import argparse
import csv
import os
import sys

# ---------------------------------------------------------------------------
# Configuration (override by passing arguments; nothing here is auto-detected)
# ---------------------------------------------------------------------------

DEFAULT_DBNAME = "ttu_mac_local"
PRIMARY_TABLE = "module_info"
PRESENCE_TABLES = (
    "module_qc_summary",
    "module_inspect",
    "module_iv_test",
    "module_pedestal_test",
)
KEY_COLUMN = "module_name"


# ---------------------------------------------------------------------------
# CSV handling
# ---------------------------------------------------------------------------

def read_column(csv_path, column, has_header=True, dedupe=True):
    """Return the entries of one column of a CSV file as a list of strings.

    `column` is a header name (str) or a 0-based index (int, or a str of
    digits). With has_header=True the first row is treated as a header and
    skipped; with has_header=False every row is data and `column` must be an
    index. Blank entries are dropped and whitespace is stripped. With
    dedupe=True, order-preserving unique entries are returned.
    """
    with open(csv_path, newline="") as fh:
        rows = [r for r in csv.reader(fh) if any(c.strip() for c in r)]
    if not rows:
        return []

    is_index = isinstance(column, int) or str(column).isdigit()
    if has_header:
        header, body = rows[0], rows[1:]
        if is_index:
            idx = int(column)
        elif column in header:
            idx = header.index(column)
        else:
            raise ValueError(
                f"column {column!r} not found in header {header}; "
                f"give a header name or a 0-based index"
            )
    else:
        if not is_index:
            raise ValueError("without a header row, `column` must be a 0-based index")
        idx, body = int(column), rows

    entries = []
    for r in body:
        if idx < len(r):
            v = r[idx].strip()
            if v:
                entries.append(v)

    if dedupe:
        seen = set()
        entries = [e for e in entries if not (e in seen or seen.add(e))]
    return entries


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

def _existing(cur, table, key_column, names):
    """Return the subset of `names` present in `table.key_column`."""
    cur.execute(
        f"SELECT DISTINCT {key_column} FROM {table} WHERE {key_column} = ANY(%s)",
        (list(names),),
    )
    return {row[0] for row in cur.fetchall()}


def check_modules(conn, names, primary_table=PRIMARY_TABLE,
                  presence_tables=PRESENCE_TABLES, key_column=KEY_COLUMN):
    """Query the database once per table and report presence of each name.

    Returns an ordered dict: name -> {table_name: bool, ...}
    with the primary table listed first, then each presence table.
    """
    names = list(names)
    tables = (primary_table,) + tuple(presence_tables)
    results = {n: {} for n in names}
    if not names:
        return results

    with conn.cursor() as cur:
        for table in tables:
            found = _existing(cur, table, key_column, names)
            for n in names:
                results[n][table] = n in found
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def summarize(results):
    """Return (n_passed, n_total, failures) where failures maps
    name -> list of tables in which the name is missing."""
    failures = {}
    for name, presence in results.items():
        missing = [t for t, ok in presence.items() if not ok]
        if missing:
            failures[name] = missing
    return len(results) - len(failures), len(results), failures


def format_report(results, primary_table=PRIMARY_TABLE):
    """Human-readable report string.

    All pass  -> "N/N passed database checks"
    Otherwise -> summary line followed by one line per failing entry.
    """
    n_pass, n_total, failures = summarize(results)
    lines = [f"{n_pass}/{n_total} passed database checks"]
    if failures:
        lines.append("")
        lines.append("Failed entries:")
        for name, missing in failures.items():
            if primary_table in missing:
                detail = f"NOT in {primary_table}"
                rest = [t for t in missing if t != primary_table]
                if rest:
                    detail += "; also missing from: " + ", ".join(rest)
            else:
                detail = "missing from: " + ", ".join(missing)
            lines.append(f"  {name}: {detail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level entry point for plugin use
# ---------------------------------------------------------------------------

def connect(dsn=None, **conn_kwargs):
    """Open a psycopg2 connection. Unset parameters fall back to PG* env vars."""
    try:
        import psycopg2
    except ImportError as e:  # pragma: no cover
        raise ImportError("psycopg2 is required: pip install psycopg2-binary") from e
    if dsn:
        return psycopg2.connect(dsn)
    conn_kwargs = {k: v for k, v in conn_kwargs.items() if v is not None}
    conn_kwargs.setdefault("dbname", os.environ.get("PGDATABASE", DEFAULT_DBNAME))
    return psycopg2.connect(**conn_kwargs)


def run(csv_path, column, dsn=None, conn=None, has_header=True,
        primary_table=PRIMARY_TABLE, presence_tables=PRESENCE_TABLES,
        key_column=KEY_COLUMN, **conn_kwargs):
    """Read the CSV column, check every entry, and build the report.

    Returns (all_passed: bool, report: str, results: dict).
    Pass an existing `conn` to reuse a connection; otherwise one is opened
    from `dsn` / connection keyword arguments and closed afterwards.
    """
    names = read_column(csv_path, column, has_header=has_header)
    own_conn = conn is None
    if own_conn:
        conn = connect(dsn, **conn_kwargs)
    try:
        results = check_modules(conn, names, primary_table, presence_tables, key_column)
    finally:
        if own_conn:
            conn.close()
    report = format_report(results, primary_table)
    n_pass, n_total, _ = summarize(results)
    return n_pass == n_total, report, results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Validate CSV module names against the HGCal module database.")
    p.add_argument("csv_path", help="CSV file to read")
    p.add_argument("column", help="header name or 0-based index of the column")
    p.add_argument("--no-header", action="store_true",
                   help="CSV has no header row (column must then be an index)")
    p.add_argument("--dsn", help="libpq DSN / URI (overrides other connection args)")
    p.add_argument("--dbname", default=None, help=f"database (default {DEFAULT_DBNAME})")
    p.add_argument("--host")
    p.add_argument("--port")
    p.add_argument("--user", default="viewer")
    p.add_argument("--password", default=None)
    p.add_argument("--key-column", default=KEY_COLUMN,
                   help=f"column holding the module name (default {KEY_COLUMN})")
    p.add_argument("--tables", nargs="+", default=list(PRESENCE_TABLES),
                   help="presence tables to check in addition to module_info")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print the full per-table matrix, not just the summary")
    return p.parse_args(argv)


def main(argv=None):
    a = _parse_args(argv)
    ok, report, results = run(
        a.csv_path, a.column, dsn=a.dsn, has_header=not a.no_header,
        presence_tables=tuple(a.tables), key_column=a.key_column,
        dbname=a.dbname, host=a.host, port=a.port, user=a.user, password=a.password,
    )
    print(report)
    if a.verbose and results:
        tables = list(next(iter(results.values())).keys())
        width = max(len(n) for n in results)
        print()
        print(" " * width + "  " + "  ".join(tables))
        for name, presence in results.items():
            marks = "  ".join(("ok" if presence[t] else "--").ljust(len(t)) for t in tables)
            print(f"{name.ljust(width)}  {marks}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
