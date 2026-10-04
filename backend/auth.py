"""Accounts and sessions.

Passwords: PBKDF2-HMAC-SHA256 with a per-user salt.
Sessions: random opaque token in an HttpOnly cookie; only its SHA-256 is stored,
so a leaked database does not leak usable sessions.
"""
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Cookie, Depends, HTTPException

from .db import DB, ROOT, get_db

COOKIE = "samanvay_session"
SESSION_DAYS = 7
ITERATIONS = 200_000
SEED_USERS = ROOT / "backend" / "seed_users.json"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt)[0], pw_hash)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(con: DB, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    con.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
        (hashlib.sha256(token.encode()).hexdigest(), user_id,
         (_now() + timedelta(days=SESSION_DAYS)).isoformat()),
    )
    return token


def drop_session(con: DB, token: str | None) -> None:
    if token:
        con.execute("DELETE FROM sessions WHERE token_hash = ?",
                    (hashlib.sha256(token.encode()).hexdigest(),))


def public_user(row: dict) -> dict:
    return {k: row[k] for k in ("id", "name", "email", "role", "ministry")}


def current_user(session: str | None = Cookie(default=None, alias=COOKIE),
                 con: DB = Depends(get_db)) -> dict:
    if not session:
        raise HTTPException(401, "Not signed in")
    row = con.one(
        "SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (hashlib.sha256(session.encode()).hexdigest(),),
    )
    if not row or datetime.fromisoformat(row["expires_at"]) < _now():
        raise HTTPException(401, "Session expired")
    return public_user(row)


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admin role required")
    return user


def audit(con: DB, user_id: int | None, action: str, detail: str = "") -> None:
    con.execute("INSERT INTO audit_log (user_id, action, detail) VALUES (?,?,?)", (user_id, action, detail))


def seed_users(con: DB) -> None:
    """Create demo accounts if they do not exist yet. Source: backend/seed_users.json
    (kept out of git), or the SAMANVAY_SEED_USERS environment variable holding the same JSON."""
    raw = SEED_USERS.read_text(encoding="utf-8") if SEED_USERS.exists() else os.environ.get("SAMANVAY_SEED_USERS")
    if not raw:
        return
    users = json.loads(raw)
    emails = [u["email"].lower() for u in users]
    have = {r["email"] for r in con.all(
        f"SELECT email FROM users WHERE email IN ({','.join('?' * len(emails))})", emails)}
    for u in users:
        if u["email"].lower() in have:
            continue
        h, s = hash_password(u["password"])
        con.execute(
            "INSERT INTO users (name, email, pw_hash, pw_salt, role, ministry) VALUES (?,?,?,?,?,?)",
            (u["name"], u["email"].lower(), h, s, u.get("role", "analyst"), u.get("ministry")),
        )
    con.commit()
