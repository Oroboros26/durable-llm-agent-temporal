import sqlite3
from pathlib import Path

import pytest

from durable_agent import tools


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DB", str(tmp_path / "t.db"))
    monkeypatch.chdir(tmp_path)  # export_csv writes ./out
    tools.seed()


def test_email_retry_is_deduplicated():
    assert tools.send_report_email("a@example.com", "s", "b", "wf:1:0") == "sent"
    assert "deduplicated" in tools.send_report_email("a@example.com", "s", "b", "wf:1:0")
    con = sqlite3.connect(tools._db())
    assert con.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1
    assert con.execute("SELECT SUM(applied) FROM effect_log").fetchone()[0] == 1


def test_export_is_overwrite_not_append():
    p1 = tools.export_csv("SELECT * FROM sales", "x.csv", "wf:2:0")
    n1 = len(Path(p1).read_text())
    p2 = tools.export_csv("SELECT * FROM sales", "x.csv", "wf:2:0")
    assert p1 == p2 and len(Path(p2).read_text()) == n1


@pytest.mark.parametrize("sql", ["DROP TABLE sales", "SELECT 1; DROP TABLE sales"])
def test_run_sql_rejects_writes(sql):
    with pytest.raises(ValueError):
        tools.run_sql(sql)
