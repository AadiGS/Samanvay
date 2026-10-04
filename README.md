# Samanvay

Cross-ministry district intelligence for Maharashtra. Joins Jal Jeevan Mission,
PMAY-Gramin and NFHS-5 on one resolved district record, then computes gaps,
overlaps and anomalies with their evidence.

## Run it

Needs Python 3.10 or newer.

- Windows: double-click `run.bat`
- macOS / Linux: `sh run.sh`

Then open http://localhost:8000. API docs are at http://localhost:8000/docs.

Create an account from the sign-in screen. For ready-made demo accounts, copy
`backend/seed_users.example.json` to `backend/seed_users.json` and set the
passwords; they are created on the next start. That file is kept out of git.

## What is where

| Path | What it does |
|---|---|
| `index.html` | The whole frontend. Holds no data: everything comes from the API. |
| `backend/main.py` | FastAPI app: auth, data, query, review and admin endpoints. |
| `backend/db.py` | Schema, SQLite/Postgres wrapper, and the seed step that loads `data.json` into tables. |
| `api/index.py`, `vercel.json` | Vercel entry point and routing. |
| `backend/auth.py` | Password hashing (PBKDF2-SHA256), cookie sessions, roles, audit log. |
| `backend/nlq.py` | Question to SQL. Rule-based parser, parameterised query, runs on the database. |
| `build_data.py` | Offline pipeline: entity resolution and findings. Writes `data.json`. |
| `index.static.html` | The earlier single-file version with data embedded. No server needed. |

## API

| Method | Path | Auth |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/logout` | public |
| GET | `/api/auth/me` | signed in |
| GET | `/api/bootstrap`, `/api/districts`, `/api/districts/{name}`, `/api/findings` | signed in |
| PATCH | `/api/findings/{id}/review` | signed in |
| POST | `/api/query` | signed in |
| GET | `/api/queries` | signed in |
| GET | `/api/admin/users`, `/api/admin/audit` | admin |
| GET | `/api/health` | public |

## Database

`users`, `sessions`, `district_facts`, `source_names`, `findings`,
`finding_evidence`, `finding_reviews`, `query_log`, `audit_log`, `meta`.
Locally this is SQLite (`backend/samanvay.db`, created on first start). If
`DATABASE_URL` is set, the same code runs on Postgres instead. Scheme tables are
loaded from `data.json` when the database is first created.

## Deploy (Vercel + Postgres)

1. Import the GitHub repo in Vercel. No build settings needed.
2. Add a Postgres database from the Vercel Storage tab (Neon). It sets
   `DATABASE_URL` for the project.
3. Optional: set `SAMANVAY_SEED_USERS` to the JSON from
   `backend/seed_users.example.json` with real passwords, for demo accounts.
4. Redeploy. `/api/health` should report `"database": "postgres"`.

Without a Postgres database the deployment will not work: serverless functions
have no persistent disk, so SQLite cannot hold accounts or sessions there.

## Honest limits

- The question parser is rule-based, not an LLM. The SQL shown is the SQL that ran.
- Findings are computed offline by `build_data.py`, not on request.
- The JJM and PMAY-G tables were transcribed from parliamentary answers and are
  still pending a line-by-line check against the source PDFs.
- Tested locally on SQLite and Postgres 16. `render.yaml` is included as an
  alternative host but has not been deployed.
