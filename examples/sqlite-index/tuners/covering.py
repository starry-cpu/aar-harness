"""covering.py -- composite, covering indexes for the most common column combinations."""

import re

PRED = re.compile(r"([a-z_]+)\s*(?:=|>=|<=|>|<|between|like)", re.IGNORECASE)
ORDER = re.compile(r"order\s+by\s+([a-z_]+)", re.IGNORECASE)
TABLES = re.compile(r"from\s+([a-z_]+)", re.IGNORECASE)
SELECTS = re.compile(r"select\s+(.*?)\s+from\s", re.IGNORECASE)


def propose(schema_ddl, sample_queries, budget):
    combo = {}
    for q in sample_queries:
        sql = q["sql"].lower()
        table = (TABLES.search(sql).group(1) if TABLES.search(sql) else "orders")
        cols = []
        for c in PRED.findall(sql):
            if c not in cols:
                cols.append(c)
        for c in ORDER.findall(sql):
            if c not in cols:
                cols.append(c)
        if not cols:
            continue
        sel = SELECTS.search(sql)
        extras = []
        if sel:
            for token in re.findall(r"[a-z_]+", sel.group(1)):
                if token not in cols and token not in ("count", "sum", "avg", "min", "max") and token not in extras:
                    extras.append(token)
        key = (table, tuple(cols[:2]), tuple(extras[:2]))
        combo[key] = combo.get(key, 0) + 1
    ranked = sorted(combo.items(), key=lambda kv: (-kv[1], kv[0]))
    out = []
    for (table, cols, extras), _ in ranked[:budget["max_indexes"]]:
        allcols = list(cols) + [e for e in extras if e not in cols]
        name = "ix_%s_%s" % (table, "_".join(allcols))
        out.append("CREATE INDEX %s ON %s(%s)" % (name[:60], table, ", ".join(allcols)))
    return out
