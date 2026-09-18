"""naive_all.py -- one index per predicate column, ignoring the budget."""

import re

COLS = re.compile(r"([a-z_]+)\s*(=|>=|<=|>|<|between|like)", re.IGNORECASE)


def propose(schema_ddl, sample_queries, budget):
    seen = []
    for q in sample_queries:
        for col in COLS.findall(q["sql"].lower()):
            if col[0] not in seen:
                seen.append(col[0])
    return ["CREATE INDEX ix_%s ON orders(%s)" % (c, c) for c in seen]
