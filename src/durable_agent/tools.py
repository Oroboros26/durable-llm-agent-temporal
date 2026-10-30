"""Plain functions, no Temporal imports. Side-effecting ones are idempotent by `key`."""
import csv
import os
import random
import re
import sqlite3
from pathlib import Path


def _db() -> str:
    return os.environ.get("AGENT_DB", "data/agent.db")


def seed() -> None:
    Path(_db()).parent.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(42)
    con = sqlite3.connect(_db())
    con.executescript(
        """
        DROP TABLE IF EXISTS sales; DROP TABLE IF EXISTS outbox; DROP TABLE IF EXISTS effect_log;
        CREATE TABLE sales(order_id INTEGER PRIMARY KEY, region TEXT, product TEXT, qty INT, amount REAL, month TEXT);
        CREATE TABLE outbox(key TEXT PRIMARY KEY, to_addr TEXT, subject TEXT, body TEXT);
        CREATE TABLE effect_log(key TEXT, applied INT);
        """
    )
    for i in range(200):
        qty = rnd.randint(1, 20)
        con.execute(
            "INSERT INTO sales VALUES (?,?,?,?,?,?)",
            (i, rnd.choice(["EMEA", "APAC", "AMER"]), rnd.choice(["shell", "pack", "glove"]),
             qty, round(qty * rnd.uniform(20, 300), 2), f"2026-{rnd.randint(1, 9):02d}"),
        )
    con.commit()
    con.close()


def describe_schema() -> str:
    con = sqlite3.connect(f"file:{_db()}?mode=ro", uri=True)
    rows = con.execute("SELECT sql FROM sqlite_master WHERE name='sales'").fetchall()
    con.close()
    return "\n".join(r[0] for r in rows)


def run_sql(sql: str) -> str:
    if not re.match(r"\s*select\b", sql, re.IGNORECASE) or ";" in sql.strip().rstrip(";"):
        raise ValueError("only a single SELECT is allowed")
    con = sqlite3.connect(f"file:{_db()}?mode=ro", uri=True)  # read-only is the real guard
    rows = con.execute(sql).fetchmany(200)
    con.close()
    return "\n".join(",".join(map(str, r)) for r in rows)


def export_csv(sql: str, filename: str, key: str) -> str:
    safe = re.sub(r"\W", "_", key)
    path = Path("out") / f"{safe}.csv"  # path derives from key: re-running overwrites, never duplicates
    path.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(f"file:{_db()}?mode=ro", uri=True)
    cur = con.execute(sql)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([c[0] for c in cur.description])
        w.writerows(cur.fetchmany(1000))
    con.close()
    return str(path)


def send_report_email(to: str, subject: str, body: str, key: str) -> str:
    """Simulated provider. The outbox row is the 'send'; the PK on key makes a retry a no-op."""
    con = sqlite3.connect(_db())
    applied = con.execute(
        "INSERT OR IGNORE INTO outbox VALUES (?,?,?,?)", (key, to, subject, body)
    ).rowcount
    con.execute("INSERT INTO effect_log VALUES (?,?)", (key, applied))  # attempts: applied=0 means deduped
    con.commit()
    con.close()
    return "sent" if applied else "already sent (deduplicated)"


TOOLS = [
    {"name": "describe_schema", "description": "Show the sales table DDL.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_sql", "description": "Run one read-only SELECT on sales (max 200 rows).",
     "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}},
    {"name": "export_csv", "description": "Export a SELECT result to a CSV file.",
     "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}, "filename": {"type": "string"}},
                      "required": ["sql", "filename"]}},
    {"name": "send_report_email", "description": "Email a report. Requires human approval.",
     "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"},
                                                       "body": {"type": "string"}}, "required": ["to", "subject", "body"]}},
]
