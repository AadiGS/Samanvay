"""Samanvay API.

Run from the prototype folder:  python -m uvicorn backend.main:app --port 8000
Interactive API docs:           http://localhost:8000/docs
"""
import json
import os
import re
import time
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import auth, db, nlq
from .auth import COOKIE, audit, current_user, require_admin
from .db import DB, NOW, ROOT, get_db


def startup() -> None:
    db.init()
    con = DB()
    auth.seed_users(con)
    con.close()


# Run at import so it also happens on serverless hosts that skip ASGI lifespan events.
startup()

app = FastAPI(
    title="Samanvay API",
    version="0.3.0",
    description="Cross-ministry district intelligence for Maharashtra: Jal Jeevan Mission, "
                "PMAY-Gramin and NFHS-5 joined on one resolved district record.",
)

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SECURE = os.environ.get("SAMANVAY_SECURE_COOKIE") == "1" or bool(os.environ.get("VERCEL"))
_fails: dict[str, list[float]] = {}


# ---------- models ----------
class Register(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=160)
    password: str = Field(min_length=8, max_length=200)
    ministry: str | None = Field(default=None, max_length=120)


class Login(BaseModel):
    email: str = Field(max_length=160)
    password: str = Field(max_length=200)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    log: bool = True


class Review(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
                    samesite="lax", secure=SECURE, path="/")


# ---------- auth ----------
@app.post("/api/auth/register", tags=["auth"], status_code=201)
def register(body: Register, resp: Response, con: DB = Depends(get_db)):
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address")
    if con.one("SELECT 1 AS x FROM users WHERE email = ?", (email,)):
        raise HTTPException(409, "An account with this email already exists")
    h, s = auth.hash_password(body.password)
    uid = con.one(
        "INSERT INTO users (name, email, pw_hash, pw_salt, ministry) VALUES (?,?,?,?,?) RETURNING id",
        (body.name.strip(), email, h, s, (body.ministry or "").strip() or None),
    )["id"]
    audit(con, uid, "register", email)
    _set_cookie(resp, auth.create_session(con, uid))
    return {"user": auth.public_user(con.one("SELECT * FROM users WHERE id = ?", (uid,)))}


@app.post("/api/auth/login", tags=["auth"])
def login(body: Login, resp: Response, con: DB = Depends(get_db)):
    email = body.email.strip().lower()
    recent = [t for t in _fails.get(email, []) if time.time() - t < 60]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
    row = con.one("SELECT * FROM users WHERE email = ?", (email,))
    if not row or not auth.verify_password(body.password, row["pw_hash"], row["pw_salt"]):
        _fails[email] = recent + [time.time()]
        raise HTTPException(401, "Email or password is incorrect")
    _fails.pop(email, None)
    audit(con, row["id"], "login")
    _set_cookie(resp, auth.create_session(con, row["id"]))
    return {"user": auth.public_user(row)}


@app.post("/api/auth/logout", tags=["auth"])
def logout(resp: Response, session: str | None = Cookie(default=None, alias=COOKIE),
           con: DB = Depends(get_db)):
    auth.drop_session(con, session)
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me", tags=["auth"])
def me(user: dict = Depends(current_user)):
    return {"user": user}


# ---------- data ----------
def _district(r: dict, sources: dict) -> dict:
    d = {"name": r["district"], "src": sources.get(r["district"], {}), "lgd": r["lgd_code"],
         "path": r["geom_path"], "c": [r["centroid_x"], r["centroid_y"]]}
    if r["rural_households"] is not None:
        d.update(hh=r["rural_households"], tap=r["tap_connections"], jjm_pct=r["jjm_tap_pct"],
                 uncon=r["hh_without_tap"], pm=[r["pmayg_2019_20"], r["pmayg_2020_21"], r["pmayg_2021_22"]],
                 pm_total=r["pmayg_houses"], pm_per1000=r["pmayg_per_1000_hh"])
        if r["pmayg_flag"]:
            d["pm_flag"] = r["pmayg_flag"]
    if r["nfhs_sanitation_pct"] is not None:
        d["nfhs"] = {"electricity": r["nfhs_electricity_pct"], "water": r["nfhs_water_source_pct"],
                     "sanitation": r["nfhs_sanitation_pct"], "cleanfuel": r["nfhs_clean_fuel_pct"],
                     "insurance": r["nfhs_insurance_pct"]}
    return d


def _districts(con: DB) -> list[dict]:
    sources: dict = {}
    for s in con.all("SELECT * FROM source_names"):
        e = {"raw": s["raw_name"], "method": s["method"], "score": s["score"]}
        if s["source_row"] is not None:
            e["row"] = s["source_row"]
        sources.setdefault(s["district"], {})[s["source"]] = e
    order = {"jjm": 0, "pmay": 1, "nfhs": 2, "lgd": 3}
    sources = {k: dict(sorted(v.items(), key=lambda kv: order.get(kv[0], 9))) for k, v in sources.items()}
    return [_district(r, sources) for r in con.all("SELECT * FROM district_facts ORDER BY position")]


def _findings(con: DB, type_: str | None = None, severity: str | None = None) -> list[dict]:
    ev: dict = {}
    for e in con.all("SELECT * FROM finding_evidence ORDER BY finding_id, position"):
        v = e["value"]
        ev.setdefault(e["finding_id"], []).append(
            {"label": e["label"], "value": int(v) if v is not None and float(v).is_integer() else v,
             "source": e["source"], "row": e["source_row"]})
    sql, args = "SELECT * FROM findings WHERE 1=1", []
    if type_:
        sql, args = sql + " AND type = ?", args + [type_]
    if severity:
        sql, args = sql + " AND severity = ?", args + [severity]
    return [{"id": f["id"], "type": f["type"], "sev": f["severity"], "district": f["district"],
             "title": f["title"], "detail": f["detail"], "rule": f["rule"], "evidence": ev.get(f["id"], [])}
            for f in con.all(sql + " ORDER BY position", args)]


def _reviews(con: DB) -> dict:
    return {r["finding_id"]: {"status": r["status"], "by": r["name"], "at": r["updated_at"]}
            for r in con.all("SELECT fr.*, u.name FROM finding_reviews fr JOIN users u ON u.id = fr.updated_by")}


@app.get("/api/bootstrap", tags=["data"], summary="Everything the app needs on first load")
def bootstrap(user: dict = Depends(current_user), con: DB = Depends(get_db)):
    meta = {r["key"]: json.loads(r["value"]) for r in con.all("SELECT * FROM meta")}
    return {"districts": _districts(con), "findings": _findings(con), "state": meta["state"],
            "map": meta["map"], "reviews": _reviews(con), "user": user}


@app.get("/api/districts", tags=["data"])
def districts(user: dict = Depends(current_user), con: DB = Depends(get_db)):
    return [{k: v for k, v in d.items() if k != "path"} for d in _districts(con)]


@app.get("/api/districts/{name}", tags=["data"])
def district(name: str, user: dict = Depends(current_user), con: DB = Depends(get_db)):
    for d in _districts(con):
        if d["name"].lower() == name.lower():
            return {**{k: v for k, v in d.items() if k != "path"},
                    "findings": [f for f in _findings(con) if f["district"] == d["name"]]}
    raise HTTPException(404, "District not found")


@app.get("/api/findings", tags=["data"])
def findings(type: str | None = None, severity: str | None = None,
             user: dict = Depends(current_user), con: DB = Depends(get_db)):
    rev = _reviews(con)
    return [{**f, "review": rev.get(f["id"], {"status": "open"})} for f in _findings(con, type, severity)]


@app.patch("/api/findings/{finding_id}/review", tags=["data"], summary="Set the review status of a finding")
def review(finding_id: int, body: Review, user: dict = Depends(current_user),
           con: DB = Depends(get_db)):
    if not con.one("SELECT 1 AS x FROM findings WHERE id = ?", (finding_id,)):
        raise HTTPException(404, "Finding not found")
    con.execute(
        "INSERT INTO finding_reviews (finding_id, status, updated_by) VALUES (?,?,?) "
        "ON CONFLICT(finding_id) DO UPDATE SET status = excluded.status, updated_by = excluded.updated_by, "
        f"updated_at = {NOW}",
        (finding_id, body.status, user["id"]),
    )
    audit(con, user["id"], "finding_review", f"{finding_id} -> {body.status}")
    return _reviews(con)[finding_id]


# ---------- query ----------
@app.post("/api/query", tags=["query"], summary="Answer a plain-language question with SQL")
def query(body: Question, user: dict = Depends(current_user), con: DB = Depends(get_db)):
    out = nlq.answer(con, body.question.strip())
    if body.log and "error" not in out:
        con.execute("INSERT INTO query_log (user_id, question, sql_text, row_count) VALUES (?,?,?,?)",
                    (user["id"], body.question.strip(), out["sql"], out["count"]))
    return out


@app.get("/api/queries", tags=["query"], summary="The signed-in user's recent questions")
def queries(user: dict = Depends(current_user), con: DB = Depends(get_db)):
    return con.all(
        "SELECT question, MAX(id) AS last_id, MAX(created_at) AS last_run, COUNT(*) AS runs FROM query_log "
        "WHERE user_id = ? GROUP BY question ORDER BY last_id DESC LIMIT 8", (user["id"],))


# ---------- admin ----------
@app.get("/api/admin/users", tags=["admin"])
def admin_users(_: dict = Depends(require_admin), con: DB = Depends(get_db)):
    return con.all(
        "SELECT u.id, u.name, u.email, u.role, u.ministry, u.created_at, "
        "(SELECT COUNT(*) FROM query_log q WHERE q.user_id = u.id) AS queries FROM users u ORDER BY u.id")


@app.get("/api/admin/audit", tags=["admin"])
def admin_audit(limit: int = 100, _: dict = Depends(require_admin), con: DB = Depends(get_db)):
    return con.all(
        "SELECT a.id, a.action, a.detail, a.created_at, u.email FROM audit_log a "
        "LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT ?", (max(1, min(limit, 500)),))


@app.get("/api/health", tags=["meta"])
def health(con: DB = Depends(get_db)):
    n = con.one("SELECT COUNT(*) AS n FROM district_facts")["n"]
    return {"status": "ok", "districts": n, "database": "postgres" if db.PG else "sqlite", "version": app.version}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-store"})
