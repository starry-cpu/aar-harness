"""schema_aware.py -- parses the schema, maps each sample query onto real columns,
then spends the index budget on the highest-frequency predicatable columns.

This is the honest version of the task: it never hardcodes a table or column name,
so it transfers to a schema it has never seen.
"""

import re

IDENT = re.compile(r"([a-z_][a-z0-9_]*)", re.IGNORECASE)
CREATE = re.compile(r"create\s+table\s+([a-z_][a-z0-9_]*)\s*\((.*?)\)\s*;", re.IGNORECASE | re.DOTALL)
FROM = re.compile(r"\bfrom\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)
JOIN = re.compile(r"\bjoin\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)
ORDER = re.compile(r"order\s+by\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)
GROUP = re.compile(r"group\s+by\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)


def parse_schema(ddl):
    tables = {}
    for name, body in CREATE.findall(ddl):
        cols = []
        for part in body.split(","):
            tokens = IDENT.findall(part.strip())
            if not tokens:
                continue
            if tokens[0].lower() in ("primary", "foreign", "unique", "constraint", "check"):
                continue
            cols.append(tokens[0].lower())
        tables[name.lower()] = cols
    return tables


def table_of(sql):
    m = FROM.search(sql)
    if m:
        return m.group(1).lower()
    m = JOIN.search(sql)
    return m.group(1).lower() if m else None


def aliases(sql):
    out = {}
    for table, alias in re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)\s+(?:as\s+)?([a-z_][a-z0-9_]*)", sql, re.IGNORECASE):
        if alias.lower() in ("on", "where", "group", "order", "join", "inner", "left"):
            continue
        out[alias.lower()] = table.lower()
    return out


def target_column(sql, col, tables, alias_map):
    if "." in col:
        prefix, name = col.split(".", 1)
        table = alias_map.get(prefix.lower(), prefix.lower())
        return table, name.lower()
    table = table_of(sql)
    if table and col.lower() in tables.get(table, []):
        return table, col.lower()
    for name, cols in tables.items():
        if col.lower() in cols:
            return name, col.lower()
    return None, None


def propose(schema_ddl, sample_queries, budget):
    tables = parse_schema(schema_ddl)
    weight = {}
    for q in sample_queries:
        sql = q["sql"]
        low = sql.lower()
        alias_map = aliases(sql)
        for col in re.findall(r"([a-z_][a-z0-9_.]*)\s*(?:=|>=|<=|>|<|between|like)", low):
            table, name = target_column(sql, col, tables, alias_map)
            if table and name:
                weight[(table, name)] = weight.get((table, name), 0) + 3
        for col in ORDER.findall(low) + GROUP.findall(low):
            table, name = target_column(sql, col, tables, alias_map)
            if table and name:
                weight[(table, name)] = weight.get((table, name), 0) + 2
        for other, left, right in re.findall(r"join\s+([a-z_][a-z0-9_]*)\s+\w*\s*on\s+([a-z0-9_.]+)\s*=\s*([a-z0-9_.]+)", low):
            for col in (left, right):
                table, name = target_column(sql, col, tables, alias_map)
                if table and name:
                    weight[(table, name)] = weight.get((table, name), 0) + 2
    ranked = sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))
    out = []
    for (table, col), _ in ranked[:budget["max_indexes"]]:
        out.append("CREATE INDEX ax_%s_%s ON %s(%s)" % (table, col, table, col))
    return out
