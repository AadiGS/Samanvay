"""Storage for Samanvay.

One code path, two engines:
- local development: SQLite file (backend/samanvay.db), zero setup
- deployment: Postgres, when DATABASE_URL (or POSTGRES_URL) is set

Schema, connection wrapper, and the seed step that loads the joined district
table (data.json, produced by build_data.py) into real tables.
"""
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
PG = bool(DATABASE_URL)
# Serverless hosts have a read-only project directory; /tmp there is per-instance and
# short-lived, so it only keeps the app bootable until DATABASE_URL is configured.
_DEFAULT = "/tmp/samanvay.db" if os.environ.get("VERCEL") else ROOT / "backend" / "samanvay.db"
DB_PATH = Path(os.environ.get("SAMANVAY_DB", _DEFAULT))
DATA_JSON = ROOT / "data.json"
SCHEMA_VERSION = "2"

# UTC timestamp as 'YYYY-MM-DD HH:MM:SS' text, same shape on both engines.
NOW = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')" if PG else "datetime('now')"
_PK = "SERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"

TABLES = ["audit_log", "query_log", "finding_reviews", "finding_evidence", "findings",
          "source_names", "district_facts", "sessions", "users", "meta"]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users (
  id {_PK},
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  pw_hash TEXT NOT NULL,
  pw_salt TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'analyst' CHECK (role IN ('analyst','admin')),
  ministry TEXT,
  created_at TEXT NOT NULL DEFAULT ({NOW})
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT ({NOW}),
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS district_facts (
  district TEXT PRIMARY KEY,
  position INTEGER NOT NULL,
  lgd_code INTEGER,
  rural_households INTEGER,
  tap_connections INTEGER,
  jjm_tap_pct DOUBLE PRECISION,
  hh_without_tap INTEGER,
  pmayg_2019_20 INTEGER,
  pmayg_2020_21 INTEGER,
  pmayg_2021_22 INTEGER,
  pmayg_houses INTEGER,
  pmayg_per_1000_hh DOUBLE PRECISION,
  pmayg_flag TEXT,
  nfhs_electricity_pct DOUBLE PRECISION,
  nfhs_water_source_pct DOUBLE PRECISION,
  nfhs_sanitation_pct DOUBLE PRECISION,
  nfhs_clean_fuel_pct DOUBLE PRECISION,
  nfhs_insurance_pct DOUBLE PRECISION,
  geom_path TEXT,
  centroid_x DOUBLE PRECISION,
  centroid_y DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS source_names (
  district TEXT NOT NULL REFERENCES district_facts(district),
  source TEXT NOT NULL,
  raw_name TEXT NOT NULL,
  method TEXT NOT NULL,
  score DOUBLE PRECISION,
  source_row INTEGER,
  PRIMARY KEY (district, source)
);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY,
  position INTEGER NOT NULL,
  type TEXT NOT NULL,
  severity TEXT NOT NULL,
  district TEXT,
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  rule TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS finding_evidence (
  id {_PK},
  finding_id INTEGER NOT NULL REFERENCES findings(id),
  position INTEGER NOT NULL,
  label TEXT NOT NULL,
  value DOUBLE PRECISION,
  source TEXT NOT NULL,
  source_row INTEGER
);
CREATE TABLE IF NOT EXISTS finding_reviews (
  finding_id INTEGER PRIMARY KEY REFERENCES findings(id),
  status TEXT NOT NULL CHECK (status IN ('open','acknowledged','resolved')),
  updated_by INTEGER NOT NULL REFERENCES users(id),
  updated_at TEXT NOT NULL DEFAULT ({NOW})
);
CREATE TABLE IF NOT EXISTS query_log (
  id {_PK},
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  sql_text TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT ({NOW})
);
CREATE TABLE IF NOT EXISTS audit_log (
  id {_PK},
  user_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL DEFAULT ({NOW})
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_query_user ON query_log(user_id, id DESC);
CREATE INDEX IF NOT EXISTS ix_evidence_finding ON finding_evidence(finding_id, position)
"""


class DB:
    """Thin wrapper so the app writes one SQL dialect ('?' placeholders, dict rows)."""

    def __init__(self):
        if PG:
            import psycopg
            from psycopg.rows import dict_row
            self.con = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.con = sqlite3.connect(DB_PATH, check_same_thread=False)
            self.con.row_factory = lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}
            self.con.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql: str, params=()):
        return self.con.execute(sql.replace("?", "%s") if PG else sql, tuple(params))

    def many(self, sql: str, rows: list) -> None:
        cur = self.con.cursor()
        cur.executemany(sql.replace("?", "%s") if PG else sql, rows)

    def all(self, sql: str, params=()) -> list[dict]:
        return self.execute(sql, params).fetchall()

    def one(self, sql: str, params=()):
        return self.execute(sql, params).fetchone()

    def commit(self):
        self.con.commit()

    def rollback(self):
        self.con.rollback()

    def close(self):
        self.con.close()


def get_db():
    """FastAPI dependency: one connection per request, committed on success."""
    con = DB()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def seed_data(con: DB) -> None:
    """Load data.json into the scheme tables."""
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    facts, names, finds, evid = [], [], [], []
    for pos, d in enumerate(data["districts"]):
        pm = d.get("pm") or [None, None, None]
        n = d.get("nfhs") or {}
        c = d.get("c") or [None, None]
        facts.append((d["name"], pos, d.get("lgd"), d.get("hh"), d.get("tap"), d.get("jjm_pct"), d.get("uncon"),
                      pm[0], pm[1], pm[2], d.get("pm_total"), d.get("pm_per1000"), d.get("pm_flag"),
                      n.get("electricity"), n.get("water"), n.get("sanitation"), n.get("cleanfuel"),
                      n.get("insurance"), d.get("path"), c[0], c[1]))
        for src, s in d["src"].items():
            names.append((d["name"], src, s["raw"], s["method"], s.get("score"), s.get("row")))
    for pos, f in enumerate(data["findings"]):
        finds.append((f["id"], pos, f["type"], f["sev"], f.get("district"), f["title"], f["detail"], f["rule"]))
        for i, e in enumerate(f["evidence"]):
            evid.append((f["id"], i, e["label"], e["value"], e["source"], e.get("row")))
    con.many("INSERT INTO district_facts VALUES (" + ",".join("?" * 21) + ")", facts)
    con.many("INSERT INTO source_names VALUES (?,?,?,?,?,?)", names)
    con.many("INSERT INTO findings VALUES (?,?,?,?,?,?,?,?)", finds)
    con.many("INSERT INTO finding_evidence (finding_id, position, label, value, source, source_row) "
             "VALUES (?,?,?,?,?,?)", evid)
    con.many("INSERT INTO meta VALUES (?,?)",
             [("state", json.dumps(data["state"])), ("map", json.dumps(data["map"])),
              ("schema_version", SCHEMA_VERSION)])


def init() -> None:
    """Create and seed the database if it is missing or from an older schema.
    One cheap query when everything is already in place."""
    con = DB()
    try:
        row = con.one("SELECT value FROM meta WHERE key = 'schema_version'")
    except Exception:
        con.rollback()
        row = None
    if not row or row["value"] != SCHEMA_VERSION:
        if PG:
            for t in TABLES:
                con.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        else:
            con.close()
            DB_PATH.unlink(missing_ok=True)
            con = DB()
        for stmt in SCHEMA.split(";"):
            con.execute(stmt)
        seed_data(con)
        con.commit()
    con.close()
