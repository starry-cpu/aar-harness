"""single_col.py -- top-k single-column indexes by how often the column is predicated."""

import re

PRED = re.compile(r"([a-z_]+)\s*(?:=|>=|<=|>|<|between|like)", re.IGNORECASE)
ORDER = re.compile(r"order\s+by\s+([a-z_]+)", re.IGNORECASE)
JOIN = re.compile(r"join\s+([a-z_]+)\s+\w+\s+on\s+\w+\.([a-z_]+)\s*=\s*\w+\.([a-z_]+)", re.IGNORECASE)
TABLES = re.compile(r"from\s+([a-z_]+)", re.IGNORECASE)


def propose(schema_ddl, sample_queries, budget):
    weight = {}
    for q in sample_queries:
        sql = q["sql"].lower()
        table = (TABLES.search(sql).group(1) if TABLES.search(sql) else "orders")
        for col in PRED.findall(sql):
            key = (table, col)
            weight[key] = weight.get(key, 0) + 3
        for col in ORDER.findall(sql):
            key = (table, col)
            weight[key] = weight.get(key, 0) + 2
        for m in JOIN.findall(sql):
            key = (m[0], m[2])
            weight[key] = weight.get(key, 0) + 1
    ranked = sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))
    out = []
    for (table, col), _ in ranked[:budget["max_indexes"]]:
        out.append("CREATE INDEX ix_%s_%s ON %s(%s)" % (table, col, table, col))
    return out
