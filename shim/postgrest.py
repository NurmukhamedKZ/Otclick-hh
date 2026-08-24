"""PostgREST-compatible read/write layer over a direct Postgres connection.

This implements exactly the subset of the PostgREST HTTP API that the Otclick-hh
backend actually uses (see backend/app/db/supabase.py + the query-builder call
sites). The translation rules come straight from postgrest/base_request_builder.py:

  GET    /rest/v1/{table}?select=...&{col}=eq.{val}&{col}=in.(a,b)&order=&limit=
  POST   /rest/v1/{table}            body = row(s)        Prefer: return=representation[,resolution=merge-duplicates]
  PATCH  /rest/v1/{table}?{filters}  body = {set cols}
  PUT    /rest/v1/{table}?{filters}  body = full row (upsert semantics)
  DELETE /rest/v1/{table}?{filters}
  POST   /rest/v1/rpc/{name}         body = {named args}

Filters become query params shaped "{operator}.{value}":
  eq, neq, gt, lt, gte, lte, is, in, like, ilike, or, not.eq, etc.

Response shape (what APIResponse.from_http_request_response expects):
  - body = JSON array (or single object when Accept: application/vnd.pgrst.object+json)
  - count: parsed from the Content-Range header ("0-9/42") when Prefer has count=exact
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import config
from .db import db_ctx


# ── query-param parsing ────────────────────────────────────────────────────

# PostgREST operators (the part after the dot in "col=eq.value").
# Order matters: longer/compound operators first so "in" doesn't shadow nothing.
_FILTER_RE = re.compile(r"^(not\.)?([a-z]+)\.(.*)$", re.DOTALL)


def _split_top(s: str, sep: str = ",") -> list[str]:
    """Split on `sep` but not inside parens or quotes."""
    out: list[str] = []
    depth = 0
    in_str = False
    cur = ""
    for ch in s:
        if ch == '"' and (not cur or cur[-1] != "\\"):
            in_str = not in_str
            cur += ch
        elif ch == "(" and not in_str:
            depth += 1
            cur += ch
        elif ch == ")" and not in_str:
            depth -= 1
            cur += ch
        elif ch == sep and depth == 0 and not in_str:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out
def _parse_value(raw: str) -> Any:
    """PostgREST value decoding: parens → tuple, comma → list, JSON literals."""
    raw = raw.strip()
    if raw.lower() == "null":
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    # (a,b) → list
    if raw.startswith("(") and raw.endswith(")"):
        inner = raw[1:-1]
        if inner == "":
            return []
        return [_parse_value(p) for p in _split_top(inner)]
    # try JSON number / quoted string
    try:
        return json.loads(raw)
    except Exception:
        pass
    # strip surrounding quotes PostgREST adds for string literals
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return json.loads(raw)
    return raw


def _val_str(val: Any) -> str:
    """Normalize a parsed value to its text-comparable form. Booleans become
    Postgres 'true'/'false' (lowercase) — supabase-py str(True) == 'True'
    which wouldn't match a boolean column cast to ::text."""
    if val is True:
        return "true"
    if val is False:
        return "false"
    if val is None:
        return "null"
    return str(val)


def parse_filters(params: list[tuple[str, str]]) -> tuple[list[tuple[str, str, str, Any, bool]], list[str]]:
    """Split query params into (filters, or_groups).

    Returns:
      filters: list of (column, operator, raw_criteria, parsed_value, negate)
      or_groups: list of raw 'or' filter strings (to be ANDed together)
    Reserved params (select, order, limit, offset, on_conflict, columns, and_)
    are handled elsewhere.
    """
    reserved = {"select", "order", "limit", "offset", "on_conflict", "columns", "and", "or"}
    filters: list[tuple[str, str, str, Any, bool]] = []
    or_groups: list[str] = []
    for key, val in params:
        if key in reserved:
            if key == "or":
                or_groups.append(val)
            continue
        # key may itself be an "or" group: "or=(col.eq.x,col.eq.y)" is the 'or' param,
        # but "col=eq.x" is a normal filter. Some clients send nested: not.col=eq.x
        m = _FILTER_RE.match(val)
        if not m:
            # Bare filter without operator? PostgREST treats "{col}={val}" as eq.
            # But supabase-py always sends an operator. Be safe: treat as eq.
            filters.append((key, "eq", val, _parse_value(val), False))
            continue
        negate = bool(m.group(1))
        op = m.group(2)
        criteria = m.group(3)
        parsed = _parse_value(criteria)
        filters.append((key, op, criteria, parsed, negate))
    return filters, or_groups


# ── SQL building ───────────────────────────────────────────────────────────

def _ident(name: str) -> str:
    """Quote an identifier safely. Reject anything that isn't a column name
    (allow schema-qualified table.column and dotted relation refs via ( ))."""
    if not name:
        raise ValueError("empty identifier")
    # Allow: letters, digits, underscore, dot, and relation-subquery dots
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$", name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return ".".join('"' + part + '"' for part in name.split("."))


def _lit(value: Any) -> str:
    """Render a Python value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(_lit(v) for v in value) + ")"
    # string / fallback
    return "'" + str(value).replace("'", "''") + "'"


def _build_where(
    filters: list[tuple[str, str, str, Any, bool]],
    or_groups: list[str],
) -> tuple[str, list[Any]]:
    """Build a WHERE clause fragment (without the WHERE keyword).

    Uses psycopg2 parameter substitution for values to avoid injection.
    """
    clauses: list[str] = []
    params: list[Any] = []

    def _col_op(col: str, op: str, val: Any, negate: bool) -> tuple[str, Any]:
        qcol = _ident(col)
        not_kw = "NOT " if negate else ""
        # PostgREST casts both sides to text on a type mismatch (e.g. integer
        # value against a text column). We mirror that by casting the column
        # to ::text for the scalar comparison operators, so eq/in/etc. work
        # regardless of whether the caller passed an int, a uuid, or a string.
        qcol_t = f"{qcol}::text"
        if op == "eq":
            return f"{not_kw}{qcol_t} = %s::text", _val_str(val)
        if op == "neq":
            return f"{not_kw}{qcol_t} <> %s::text", _val_str(val)
        if op == "gt":
            return f"{not_kw}{qcol_t} > %s::text", _val_str(val)
        if op == "lt":
            return f"{not_kw}{qcol_t} < %s::text", _val_str(val)
        if op == "gte":
            return f"{not_kw}{qcol_t} >= %s::text", _val_str(val)
        if op == "lte":
            return f"{not_kw}{qcol_t} <= %s::text", _val_str(val)
        if op == "is":
            # is.null / is.true / is.false. With `not_` prefix (negate=True)
            # this becomes IS NOT (e.g. not_.is_('resume_id','null') → IS NOT NULL).
            if val is None:
                return f"{qcol} IS {'NOT ' if negate else ''}NULL", None
            return f"{qcol} IS {'NOT ' if negate else ''}%s", val
        if op == "in":
            # val is a list
            if not isinstance(val, list):
                val = [val]
            if not val:
                return f"{not_kw}FALSE", None
            placeholders = ", ".join(["%s::text"] * len(val))
            return f"{not_kw}{qcol_t} IN ({placeholders})", [_val_str(v) for v in val]
        if op == "like":
            return f"{not_kw}{qcol} LIKE %s", val
        if op == "ilike":
            return f"{not_kw}{qcol} ILIKE %s", val
        if op == "contains":
            # jsonb containment: col @> %s
            return f"{not_kw}{qcol} @> %s", json.dumps(val)
        if op == "cs":
            return f"{not_kw}{qcol} @> %s", json.dumps(val)
        if op == "cd":
            return f"{not_kw}{qcol} <@ %s", json.dumps(val)
        raise ValueError(f"unsupported operator: {op}")

    for col, op, _criteria, parsed, negate in filters:
        clause, p = _col_op(col, op, parsed, negate)
        clauses.append(clause)
        if p is not None:
            if isinstance(p, list):
                params.extend(p)
            else:
                params.append(p)

    # or-groups: each is "(col.eq.x,col.eq.y)" → (col = x OR col = y)
    for grp in or_groups:
        inner = grp
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        or_clauses: list[str] = []
        for term in _split_top(inner):
            m = _FILTER_RE.match(term.strip())
            if not m:
                continue
            negate = bool(m.group(1))
            op = m.group(2)
            col, _, criteria = term.strip().split("=", 1) if "=" in term else (term, "", "")
            # term shape: col=op.criteria  → split col from the rest
            col, rest = term.split("=", 1) if "=" in term else (term, "")
            m2 = _FILTER_RE.match(rest.strip())
            if not m2:
                continue
            negate = bool(m2.group(1))
            op = m2.group(2)
            parsed = _parse_value(m2.group(3))
            clause, p = _col_op(col, op, parsed, negate)
            or_clauses.append(clause)
            if p is not None:
                if isinstance(p, list):
                    params.extend(p)
                else:
                    params.append(p)
        if or_clauses:
            clauses.append("(" + " OR ".join(or_clauses) + ")")

    if not clauses:
        return "", params
    return " AND ".join(clauses), params


# ── main entry points ──────────────────────────────────────────────────────

def _select_cols(select_param: str | None) -> str:
    """PostgREST select= columns → SQL column list. We support plain columns
    and '*'. Resource embedding (table!fk) is not used by the backend."""
    if not select_param or select_param == "*":
        return "*"
    cols = []
    for c in _split_top(select_param):
        c = c.strip()
        if c == "*":
            cols.append("*")
            continue
        # alias: "col:alias" → "col AS alias"
        if ":" in c:
            name, alias = c.split(":", 1)
            cols.append(f"{_ident(name)} AS {_ident(alias)}")
        else:
            cols.append(_ident(c))
    return ", ".join(cols)


def query(
    table: str,
    method: str,
    params: list[tuple[str, str]],
    body: Any,
    headers: dict[str, str],
) -> tuple[int, Any, dict[str, str]]:
    """Execute a PostgREST-style request.

    Returns (status_code, json_body, response_headers).
    """
    table_q = _ident(table)
    filters, or_groups = parse_filters(params)
    select_param = next((v for k, v in params if k == "select"), None)
    order_param = next((v for k, v in params if k == "order"), None)
    limit = next((int(v) for k, v in params if k == "limit"), None)
    offset = next((int(v) for k, v in params if k == "offset"), None)
    on_conflict = next((v for k, v in params if k == "on_conflict"), None)
    if on_conflict:
        # PostgREST on_conflict is a comma-separated column list ("a,b").
        on_conflict = [c.strip() for c in on_conflict.split(",") if c.strip()]

    prefer = headers.get("prefer", "")
    accept = headers.get("accept", "")
    want_single = "vnd.pgrst.object" in accept
    want_count = "count=exact" in prefer
    want_representation = "return=representation" in prefer or not prefer or "count" in prefer

    with db_ctx() as conn:
        cur = conn.cursor()

        # HEAD is the same path as GET but returns only headers (the count).
        # The supabase-js client uses { count: "exact", head: true } → HEAD;
        # without this branch the UI's status-tab counters stay 0 (405).
        if method in ("HEAD", "GET"):
            where, qparams = _build_where(filters, or_groups)
            sql = f"SELECT {_select_cols(select_param)} FROM {table_q}"
            if where:
                sql += f" WHERE {where}"
            if order_param:
                sql += f" ORDER BY {_build_order(order_param)}"
            if limit is not None:
                sql += f" LIMIT {int(limit)}"
            if offset is not None:
                sql += f" OFFSET {int(offset)}"
            cur.execute(sql, qparams)
            rows = cur.fetchall()
            data = [dict(r) for r in rows]

            resp_headers: dict[str, str] = {}
            if want_count:
                # total count ignoring limit/offset
                csql = f"SELECT count(*) AS c FROM {table_q}"
                if where:
                    csql += f" WHERE {where}"
                cur.execute(csql, qparams)
                total = cur.fetchone()["c"]
                # PostgREST Content-Range: "start-end/total" or "*/total" when empty.
                if data:
                    rng = f"{offset or 0}-{(offset or 0) + len(data) - 1}"
                else:
                    rng = "*"
                resp_headers["content-range"] = f"{rng}/{total}"

            # HEAD: no body, only the count header. Status 200 (not 204) so the
            # client sees a real response with Content-Range.
            if method == "HEAD":
                return 200, None, resp_headers

            if want_single:
                if not data:
                    return 406, {"message": "JSON object requested, but no rows returned", "code": "PGRST116"}, {}
                return 200, _serialize(data[0]), resp_headers
            return 200, _serialize(data), resp_headers

        if method == "POST":
            # insert or upsert
            rows = body if isinstance(body, list) else [body]
            upsert_merge = "resolution=merge-duplicates" in prefer
            ignore_dup = "resolution=ignore-duplicates" in prefer
            if not rows:
                return 201, [], {}
            cols = list(rows[0].keys())
            col_sql = ", ".join(_ident(c) for c in cols)
            row_ph = "(" + ", ".join(["%s"] * len(cols)) + ")"
            placeholders = ", ".join([row_ph] * len(rows))
            all_values: list[Any] = []
            for r in rows:
                all_values.extend([r.get(c) for c in cols])
            sql = f"INSERT INTO {table_q} ({col_sql}) VALUES {placeholders}"
            if upsert_merge or ignore_dup:
                conflict_target = on_conflict or _conflict_cols(conn, table, cols)
                if conflict_target:
                    ct = ", ".join(_ident(c) for c in conflict_target)
                    if ignore_dup:
                        sql += f" ON CONFLICT ({ct}) DO NOTHING"
                    else:
                        update_cols = [c for c in cols if c not in conflict_target]
                        if update_cols:
                            sets = ", ".join(f"{_ident(c)} = EXCLUDED.{_ident(c)}" for c in update_cols)
                            sql += f" ON CONFLICT ({ct}) DO UPDATE SET {sets}"
                        else:
                            sql += f" ON CONFLICT ({ct}) DO NOTHING"
            if want_representation:
                sql += " RETURNING *"
            cur.execute(sql, all_values)
            if want_representation:
                rows_out = cur.fetchall()
                data = [dict(r) for r in rows_out]
                if want_single and data:
                    return 201, _serialize(data[0]), {}
                return 201, _serialize(data), {}
            return 201, None, {}

        if method == "PATCH":
            where, qparams = _build_where(filters, or_groups)
            if not where:
                # PostgREST refuses full-table updates without a filter; we do too.
                return 400, {"message": "PATCH requires a filter", "code": "PGRST116"}, {}
            set_cols = list(body.keys())
            sets = ", ".join(f"{_ident(c)} = %s" for c in set_cols)
            set_vals = [body[c] for c in set_cols]
            sql = f"UPDATE {table_q} SET {sets}"
            if where:
                sql += f" WHERE {where}"
            if want_representation:
                sql += " RETURNING *"
            cur.execute(sql, set_vals + qparams)
            if want_representation:
                rows_out = cur.fetchall()
                data = [dict(r) for r in rows_out]
                return 200, _serialize(data), {}
            return 204, None, {}

        if method == "PUT":
            # upsert: like POST with merge-duplicates
            rows = body if isinstance(body, list) else [body]
            if not rows:
                return 200, [], {}
            cols = list(rows[0].keys())
            col_sql = ", ".join(_ident(c) for c in cols)
            conflict_target = on_conflict or _conflict_cols(conn, table, cols)
            row_ph = ", ".join(["%s"] * len(cols))
            placeholders = []
            all_values = []
            for r in rows:
                placeholders.append(f"({row_ph})")
                all_values.extend([r.get(c) for c in cols])
            sql = f"INSERT INTO {table_q} ({col_sql}) VALUES {', '.join(placeholders)}"
            if conflict_target:
                ct = ", ".join(_ident(c) for c in conflict_target)
                update_cols = [c for c in cols if c not in conflict_target]
                if update_cols:
                    sets = ", ".join(f"{_ident(c)} = EXCLUDED.{_ident(c)}" for c in update_cols)
                    sql += f" ON CONFLICT ({ct}) DO UPDATE SET {sets}"
                else:
                    sql += f" ON CONFLICT ({ct}) DO NOTHING"
            if want_representation:
                sql += " RETURNING *"
            cur.execute(sql, all_values)
            if want_representation:
                rows_out = cur.fetchall()
                data = [dict(r) for r in rows_out]
                return 200, _serialize(data), {}
            return 200, None, {}

        if method == "DELETE":
            where, qparams = _build_where(filters, or_groups)
            if not where:
                return 400, {"message": "DELETE requires a filter", "code": "PGRST116"}, {}
            sql = f"DELETE FROM {table_q}"
            if where:
                sql += f" WHERE {where}"
            if want_representation:
                sql += " RETURNING *"
            cur.execute(sql, qparams)
            if want_representation:
                rows_out = cur.fetchall()
                data = [dict(r) for r in rows_out]
                return 200, _serialize(data), {}
            return 204, None, {}

    return 405, {"message": "method not allowed"}, {}


def _build_order(order_param: str) -> str:
    """order=col.asc.nullsfirst,col.desc → SQL ORDER BY."""
    parts = []
    for term in _split_top(order_param):
        term = term.strip()
        bits = term.split(".")
        col = bits[0]
        direction = "ASC"
        nulls = ""
        for b in bits[1:]:
            if b.lower() in ("asc", "desc"):
                direction = b.upper()
            elif b.lower() in ("nullsfirst", "nullsfirst"):
                nulls = " NULLS FIRST"
            elif b.lower() in ("nullslast", "nullslast"):
                nulls = " NULLS LAST"
        parts.append(f"{_ident(col)} {direction}{nulls}")
    return ", ".join(parts)


def _conflict_cols(conn: Any, table: str, cols: list[str]) -> list[str] | None:
    """Find a unique constraint on the table covering a subset of `cols`.
    Returns the column names of the first matching unique/pk index, or None."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = %s AND n.nspname = 'public'
              AND (i.indisunique OR i.indisprimary)
            """,
            (table,),
        )
        for row in cur.fetchall():
            # row is a RealDictRow; attname is the column
            attname = row["attname"] if isinstance(row, dict) else row[0]
            if attname in cols:
                return [attname]
        return None
    except Exception:
        return None


def _serialize(obj: Any) -> Any:
    """Make JSON-serializable: datetime, UUID, Decimal, etc."""
    import datetime
    import decimal
    import uuid

    if obj is None:
        return None
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return [_serialize(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


def rpc(name: str, args: dict[str, Any]) -> tuple[int, Any, dict[str, str]]:
    """POST /rest/v1/rpc/{name} — call a Postgres function with named args."""
    fn = _ident(name)
    # Build a parameterized call: fn(p_arg1 => %s, p_arg2 => %s)
    if not args:
        sql = f"SELECT {fn}() AS result"
        params: list[Any] = []
    else:
        call_parts = []
        params = []
        for k, v in args.items():
            call_parts.append(f"{_ident(k)} => %s")
            params.append(v)
        sql = f"SELECT {fn}({', '.join(call_parts)}) AS result"
    with db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return 200, None, {}
        result = row.get("result") if isinstance(row, dict) else row[0]
        # PostgREST returns the function's return value directly (not wrapped)
        # unless it's a set, in which case it's an array.
        if isinstance(result, list):
            return 200, _serialize(result), {}
        return 200, _serialize(result), {}
