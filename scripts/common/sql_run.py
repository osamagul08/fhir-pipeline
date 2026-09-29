"""
Run a .sql file and print the results as a readable table.

Handles files with several statements, and named parameters (:name) - the same
parameters the Job passes to the files in sql/databricks/ops/.

Usage:
    python scripts/common/sql_run.py sql/databricks/checks/reconcile_report.sql
    python scripts/common/sql_run.py sql/databricks/ops/drift_gate.sql \
        --param catalog=workspace --param schema=dev_osamagul08_brfss_etl
    python scripts/common/sql_run.py sql/snowflake/some_file.sql --platform snowflake

Exit code is 1 if any statement fails - so a gate that fires shows as a failure.

(Replaces query.py, which disappeared from disk on 2026-09-28 before it was ever
committed.)
"""

import argparse
import os
import sys

from dotenv import load_dotenv

# Reuse the connection and path logic in measure_query.py, so exactly one file
# knows how to find the project, the .env and the CLI.
sys.path.insert(0, os.path.dirname(__file__))
from measure_query import ROOT, databricks_oauth_token  # noqa: E402

load_dotenv(ROOT / ".env")


def connect(platform):
    if platform == "snowflake":
        import snowflake.connector
        return snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            role=os.environ["SNOWFLAKE_ROLE"],
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        )
    from databricks import sql as dbsql
    return dbsql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"].replace("https://", ""),
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=databricks_oauth_token(os.environ.get("DATABRICKS_PROFILE", "trial")),
    )


def split_statements(sql):
    """Split a file into statements.

    A statement ends on a line whose CODE - the part before any `--` comment -
    ends with ';'. Comments never end a statement: an earlier version split on
    any line ending in ';' and a comment ending in a semicolon cut a query in half.
    """
    pieces, current = [], []
    for line in sql.splitlines():
        current.append(line)
        if line.split("--", 1)[0].rstrip().endswith(";"):
            pieces.append("\n".join(current))
            current = []
    if current:
        pieces.append("\n".join(current))
    # Drop pieces that are only comments or blank lines.
    return [p for p in pieces
            if any(l.split("--", 1)[0].strip() for l in p.splitlines())]


def print_table(columns, rows):
    """Aligned table: each column as wide as its longest value."""
    if not rows:
        print("(no rows returned)")
        return
    text = [["NULL" if v is None else str(v) for v in r] for r in rows]
    widths = [max(len(c), *(len(r[i]) for r in text)) for i, c in enumerate(columns)]
    header = "  ".join(c.ljust(w) for c, w in zip(columns, widths))
    print(header)
    print("-" * len(header))
    for r in text:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
    print(f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("sql_file")
    p.add_argument("--platform", default="databricks", choices=["databricks", "snowflake"])
    p.add_argument("--param", action="append", default=[],
                   help="name=value for a :name parameter in the SQL; repeatable")
    # A Snowflake Scripting block (DECLARE ... BEGIN ... END;) contains many ';'
    # that belong INSIDE it. Splitting would cut it into broken pieces, so it
    # must be sent whole.
    p.add_argument("--no-split", action="store_true",
                   help="send the whole file as ONE statement (Snowflake Scripting blocks)")
    args = p.parse_args()

    params = dict(kv.split("=", 1) for kv in args.param)
    with open(args.sql_file, encoding="utf-8") as fh:
        text = fh.read()
    pieces = [text] if args.no_split else split_statements(text)

    con = connect(args.platform)
    cur = con.cursor()
    try:
        for i, stmt in enumerate(pieces, 1):
            if len(pieces) > 1:
                print(f"\n--- statement {i} of {len(pieces)} ---")
            # Only pass parameters when there are some; a parameter-free
            # statement must not receive an empty mapping.
            cur.execute(stmt, params) if params else cur.execute(stmt)
            if cur.description:
                print_table([d[0] for d in cur.description], cur.fetchall())
            else:
                print("ran ok (no rows to show)")
        return 0
    except Exception as e:
        print(f"FAILED: {type(e).__name__}\n{str(e)[:600]}")
        return 1
    finally:
        cur.close()
        con.close()


if __name__ == "__main__":
    sys.exit(main())
