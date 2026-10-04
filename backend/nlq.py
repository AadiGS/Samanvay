"""Plain-language question -> SQL over district_facts.

Rule-based, not an LLM. The parser picks metrics, comparisons, ranking and
district names out of the question, builds one parameterised SELECT, runs it
on the database, and returns the exact statement that was executed.
"""
import math
import re

# key -> (column, keywords). Columns are a fixed whitelist: nothing typed by a
# user is ever placed into SQL as an identifier.
METRICS = {
    "jjm_pct": ("jjm_tap_pct", ["tap", "jjm", "jal jeevan", "coverage", "water connection"]),
    "uncon": ("hh_without_tap", ["unconnected", "without a tap", "without tap", "no tap"]),
    "pm_per1000": ("pmayg_per_1000_hh", ["per 1000", "per 1,000", "housing", "construction"]),
    "pm_total": ("pmayg_houses", ["houses", "house", "pmay"]),
    "sanitation": ("nfhs_sanitation_pct", ["sanitation", "toilet"]),
    "water": ("nfhs_water_source_pct", ["improved water", "water source"]),
    "cleanfuel": ("nfhs_clean_fuel_pct", ["clean fuel", "cooking"]),
    "insurance": ("nfhs_insurance_pct", ["insurance"]),
    "hh": ("rural_households", ["rural households"]),
}
DEFAULT_COLS = ["jjm_pct", "pm_total", "sanitation"]
KEYS = sorted(((kw, k) for k, (_, kws) in METRICS.items() for kw in kws), key=lambda x: -len(x[0]))
SPLIT = re.compile(r"\b(?:and|but|with|while|yet)\b")


def _num(s: str):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _percentile(con, key: str, p: float) -> float:
    col = METRICS[key][0]
    vals = [r["v"] for r in con.all(f"SELECT {col} AS v FROM district_facts WHERE {col} IS NOT NULL ORDER BY {col}")]
    return vals[min(len(vals) - 1, math.floor(len(vals) * p))]


def parse(con, question: str) -> dict:
    q = " " + question.lower() + " "
    conds, used, order, limit = [], [], None, None
    for clause in SPLIT.split(q):
        hit = next((k for kw, k in KEYS if kw in clause), None)
        if not hit:
            continue
        if hit not in used:
            used.append(hit)
        if m := re.search(r"\b(top|highest|most)\s+(\d+)?", clause):
            order, limit = (hit, "DESC"), int(m.group(2)) if m.group(2) else 5
        elif m := re.search(r"\b(lowest|bottom|least)\s+(\d+)?", clause):
            order, limit = (hit, "ASC"), int(m.group(2)) if m.group(2) else 5
        elif (m := re.search(r"(below|under|less than|lower than|<)\s*([\d.,]+)", clause)) and _num(m.group(2)) is not None:
            conds.append((hit, "<", _num(m.group(2)), None))
        elif (m := re.search(r"(above|over|more than|greater than|at least|>)\s*([\d.,]+)", clause)) and _num(m.group(2)) is not None:
            conds.append((hit, ">", _num(m.group(2)), None))
        elif re.search(r"\b(high|heavy)\b", clause):
            conds.append((hit, ">=", _percentile(con, hit, 2 / 3), "top third"))
        elif re.search(r"\b(low|lagging|poor)\b", clause):
            conds.append((hit, "<=", _percentile(con, hit, 1 / 3), "bottom third"))
    names = [r["district"] for r in con.all("SELECT district FROM district_facts ORDER BY district")]
    named = [n for n in names if " " + n.lower() in q]
    return {"conds": conds, "used": used, "order": order, "limit": min(limit, 36) if limit else None, "named": named}


def _lit(v) -> str:
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(int(v)) if float(v).is_integer() else str(v)


def answer(con, question: str) -> dict:
    p = parse(con, question)
    if not p["used"] and not p["named"]:
        return {"error": "no_metric"}
    cols = p["used"] or DEFAULT_COLS
    where, params = [], []
    if p["named"]:
        where.append((f"district IN ({', '.join('?' * len(p['named']))})", p["named"], None))
    else:
        constrained = {c[0] for c in p["conds"]}
        for k in cols:
            if k not in constrained:
                where.append((f"{METRICS[k][0]} IS NOT NULL", [], None))
    for k, op, v, why in p["conds"]:
        where.append((f"{METRICS[k][0]} {op} ?", [v], why))
    first = cols[0]
    o = p["order"] or (first, "ASC" if any(c[0] == first and "<" in c[1] for c in p["conds"]) else "DESC")

    select = f"SELECT district, {', '.join(METRICS[k][0] for k in cols)}\nFROM district_facts"
    tail = f"\nORDER BY {METRICS[o[0]][0]} {o[1]}" + ("\nLIMIT ?" if p["limit"] else "")
    sql = select + ("\nWHERE " + "\n  AND ".join(w[0] for w in where) if where else "") + tail
    for w in where:
        params += w[1]
    if p["limit"]:
        params.append(p["limit"])
    rows = con.all(sql, params)

    # The statement as executed, with bound values written in for display.
    shown = []
    for text, vals, why in where:
        for v in vals:
            text = text.replace("?", _lit(v), 1)
        shown.append(text + (f"   -- {why} of districts" if why else ""))
    display = select + ("\nWHERE " + "\n  AND ".join(shown) if shown else "") + tail.replace("?", str(p["limit"]))
    return {"sql": display, "columns": cols, "districts": [r["district"] for r in rows],
            "rows": [dict(r) for r in rows], "count": len(rows)}
