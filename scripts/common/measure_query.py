"""
Measure one query identically on Databricks and Snowflake.

The brief's rule: "A metric measured two different ways on two platforms is not a
comparison." So there is ONE script and the platform is a parameter. Neither side
gets a hand-tuned measurement path.

Usage:
    python scripts/common/measure_query.py --platform snowflake  --sql "SELECT 1"
    python scripts/common/measure_query.py --platform databricks --sql "SELECT 1"

What is timed, and why each phase is separate:
  connect_s  - opening the session
  execute_s  - submitting the query and the server finishing it. On a cold
               warehouse this INCLUDES the compute starting up, which is the
               "cold start penalty" the brief asks for.
  fetch_s    - pulling the rows back to this machine
  total_s    - the number a user would actually feel

Wall clock is measured client-side, on this machine, for both platforms.
Server-reported timings are NOT used: each vendor defines them differently, so
comparing them would compare definitions rather than platforms.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# The project root is two folders above this file (scripts/common/). Working it out from this file's
# own location means the scripts run from any machine and any folder - nothing
# assumes the project lives at D:\data-eng.
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _find_databricks_cli() -> str:
    """Locate the Databricks CLI without hard-coding this laptop's path.

    Checked in order:
      1. DATABRICKS_CLI in .env - an explicit override, if ever needed
      2. `databricks` on PATH - the normal case on any machine
      3. the folder winget installs it into on Windows - PATH is only refreshed
         in NEW terminals, so a session started before install cannot see it
    """
    if os.environ.get("DATABRICKS_CLI"):
        return os.environ["DATABRICKS_CLI"]
    on_path = shutil.which("databricks")
    if on_path:
        return on_path
    winget = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Databricks.DatabricksCLI_*\databricks.exe"))
    if winget:
        return winget[0]
    raise FileNotFoundError(
        "Databricks CLI not found. Install it, or set DATABRICKS_CLI in .env.")


DATABRICKS_CLI = _find_databricks_cli()


def databricks_oauth_token(profile: str) -> str:
    """Borrow a short-lived OAuth token from the CLI we already logged in with.

    Better than a personal access token: it expires on its own and never has to be
    written into .env.
    """
    out = subprocess.run(
        [DATABRICKS_CLI, "auth", "token", "--profile", profile],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)["access_token"]


def measure_snowflake(sql: str) -> dict:
    import snowflake.connector

    t0 = time.perf_counter()
    con = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
    )
    t1 = time.perf_counter()

    cur = con.cursor()
    cur.execute(sql)
    t2 = time.perf_counter()

    rows = cur.fetchall()
    t3 = time.perf_counter()

    # query_id lets us look the cost up afterwards in ACCOUNT_USAGE, rather than
    # guessing at it.
    query_id = cur.sfqid
    cur.close()
    con.close()

    return {
        "connect_s": t1 - t0, "execute_s": t2 - t1, "fetch_s": t3 - t2,
        "total_s": t3 - t0, "rows": len(rows), "query_id": query_id,
    }


def measure_databricks(sql: str) -> dict:
    from databricks import sql as dbsql

    token = databricks_oauth_token(os.environ.get("DATABRICKS_PROFILE", "trial"))
    host = os.environ["DATABRICKS_HOST"].replace("https://", "")

    t0 = time.perf_counter()
    con = dbsql.connect(
        server_hostname=host,
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=token,
    )
    t1 = time.perf_counter()

    cur = con.cursor()
    cur.execute(sql)
    t2 = time.perf_counter()

    rows = cur.fetchall()
    t3 = time.perf_counter()

    query_id = getattr(cur, "active_result_set", None)
    query_id = getattr(query_id, "command_id", None) if query_id else None
    cur.close()
    con.close()

    return {
        "connect_s": t1 - t0, "execute_s": t2 - t1, "fetch_s": t3 - t2,
        "total_s": t3 - t0, "rows": len(rows), "query_id": str(query_id),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--platform", required=True, choices=["snowflake", "databricks"])
    p.add_argument("--sql", default="SELECT 1")
    # --file lets us run version-controlled SQL instead of pasting statements
    # inline, so what ran is exactly what is committed.
    p.add_argument("--file", help="path to a .sql file; overrides --sql")
    p.add_argument("--label", default="first_query_cold")
    args = p.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            args.sql = fh.read()

    started = datetime.now(timezone.utc).isoformat()
    try:
        fn = measure_snowflake if args.platform == "snowflake" else measure_databricks
        result = fn(args.sql)
        result.update(ok=True)
    except Exception as e:                       # record failures, never hide them
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    result.update(platform=args.platform, sql=args.sql, label=args.label,
                  started_utc=started)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
