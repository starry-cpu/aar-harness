"""world.py -- study domain: SQLite index selection across heterogeneous workloads.

Target system: a SQLite database rebuilt deterministically from a seeded generator.
A method is a tuner program that, given a schema and a SAMPLE of the workload,
proposes a bounded set of DDL statements (indexes).  The runner applies them and
measures the cost of the EVALUATION workload, which the tuner never sees.

Cost is measured as executed VM opcodes through SQLite progress handler, so the
metric is deterministic: no timing noise, and the same method always scores the same.
"""

from __future__ import annotations

import random
import sqlite3

N_USERS = 5000
N_ORDERS = 20000
N_EVENTS = 40000
N_DEVICES = 2000
N_READINGS = 30000
T0 = 1600000000
WINDOWS = 5
STEP = 50
MAX_INDEXES = 4

MAIN_SCHEMA = """
CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL, tier TEXT NOT NULL, signup_ts INTEGER NOT NULL);
CREATE TABLE orders(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, sku TEXT NOT NULL, qty INTEGER NOT NULL, amount REAL NOT NULL, created_ts INTEGER NOT NULL, status TEXT NOT NULL);
CREATE TABLE events(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, ts INTEGER NOT NULL, payload TEXT NOT NULL);
"""

SENSOR_SCHEMA = """
CREATE TABLE devices(id INTEGER PRIMARY KEY, site TEXT NOT NULL, model TEXT NOT NULL, installed_ts INTEGER NOT NULL);
CREATE TABLE readings(id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, ts INTEGER NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL);
"""

CITIES = ["berlin", "lagos", "osaka", "lima", "oslo", "delhi", "cairo", "quito"]
TIERS = ["free", "pro", "team", "enterprise"]
STATUSES = ["pending", "paid", "shipped", "refunded", "cancelled"]
KINDS = ["view", "click", "search", "share", "purchase"]
SKUS = ["sku-%04d" % i for i in range(400)]
SITES = ["north", "south", "east", "west", "central"]
MODELS = ["m-%02d" % i for i in range(20)]
METRICS = ["temp", "humidity", "pressure", "vibration"]


def connect():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    return conn


def build_main(conn, rng):
    conn.executescript(MAIN_SCHEMA)
    conn.executemany("INSERT INTO users VALUES (?,?,?,?,?)", [(i, "u%d" % i, CITIES[rng.randrange(len(CITIES))], TIERS[rng.randrange(len(TIERS))], T0 + rng.randrange(0, 30000000)) for i in range(1, N_USERS + 1)])
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", [(i, rng.randrange(1, N_USERS + 1), SKUS[rng.randrange(len(SKUS))], rng.randrange(1, 9), round(rng.random() * 500.0, 2), T0 + rng.randrange(0, 30000000), STATUSES[rng.randrange(len(STATUSES))]) for i in range(1, N_ORDERS + 1)])
    conn.executemany("INSERT INTO events VALUES (?,?,?,?,?)", [(i, rng.randrange(1, N_USERS + 1), KINDS[rng.randrange(len(KINDS))], T0 + rng.randrange(0, 30000000), "p" * (10 + rng.randrange(40))) for i in range(1, N_EVENTS + 1)])
    conn.commit()


def build_sensors(conn, rng):
    conn.executescript(SENSOR_SCHEMA)
    conn.executemany("INSERT INTO devices VALUES (?,?,?,?)", [(i, SITES[rng.randrange(len(SITES))], MODELS[rng.randrange(len(MODELS))], T0 + rng.randrange(0, 30000000)) for i in range(1, N_DEVICES + 1)])
    conn.executemany("INSERT INTO readings VALUES (?,?,?,?,?)", [(i, rng.randrange(1, N_DEVICES + 1), T0 + rng.randrange(0, 30000000), METRICS[rng.randrange(len(METRICS))], round(rng.random() * 100.0, 3)) for i in range(1, N_READINGS + 1)])
    conn.commit()


# ---------------------------------------------------------------- workloads

def w_point(rng, n):
    return [("SELECT id, sku, amount, status FROM orders WHERE user_id = ?", (rng.randrange(1, N_USERS + 1),)) for _ in range(n)]


def w_point_status(rng, n):
    return [("SELECT COUNT(*), SUM(amount) FROM orders WHERE user_id = ? AND status = ?", (rng.randrange(1, N_USERS + 1), STATUSES[rng.randrange(len(STATUSES))])) for _ in range(n)]


def w_range_sort(rng, n):
    out = []
    for _ in range(n):
        a = T0 + rng.randrange(0, 29000000)
        out.append(("SELECT id, amount FROM orders WHERE created_ts BETWEEN ? AND ? ORDER BY amount DESC LIMIT 20", (a, a + 400000)))
    return out


def w_join_agg(rng, n):
    return [("SELECT u.city, COUNT(*), SUM(o.amount) FROM orders o JOIN users u ON u.id = o.user_id WHERE o.status = ? GROUP BY u.city", (STATUSES[rng.randrange(len(STATUSES))],)) for _ in range(n)]


def w_event_lookup(rng, n):
    return [("SELECT COUNT(*) FROM events WHERE user_id = ? AND kind = ?", (rng.randrange(1, N_USERS + 1), KINDS[rng.randrange(len(KINDS))])) for _ in range(n)]


def w_range_status(rng, n):
    return [("SELECT id, created_ts FROM orders WHERE status = ? ORDER BY created_ts DESC LIMIT 50", (STATUSES[rng.randrange(len(STATUSES))],)) for _ in range(n)]


def w_join_agg_tier(rng, n):
    return [("SELECT u.tier, COUNT(*), AVG(o.amount) FROM orders o JOIN users u ON u.id = o.user_id WHERE o.qty >= ? GROUP BY u.tier", (rng.randrange(1, 6),)) for _ in range(n)]


def w_reading_lookup(rng, n):
    return [("SELECT value FROM readings WHERE device_id = ? AND metric = ? ORDER BY ts LIMIT 50", (rng.randrange(1, N_DEVICES + 1), METRICS[rng.randrange(len(METRICS))])) for _ in range(n)]


def w_reading_agg(rng, n):
    return [("SELECT d.site, COUNT(*), AVG(r.value) FROM readings r JOIN devices d ON d.id = r.device_id WHERE r.metric = ? GROUP BY d.site", (METRICS[rng.randrange(len(METRICS))],)) for _ in range(n)]


def w_writes_main(rng, n):
    return [("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", (N_ORDERS + 1 + i, rng.randrange(1, N_USERS + 1), SKUS[i % len(SKUS)], 1, 1.0, T0 + i, "pending")) for i in range(n)]


def w_writes_sensors(rng, n):
    return [("INSERT INTO readings VALUES (?,?,?,?,?)", (N_READINGS + 1 + i, rng.randrange(1, N_DEVICES + 1), T0 + i, "temp", 1.0)) for i in range(n)]


BENCHES = {
    "point": {"schema": "main", "eval": [(w_point, 25), (w_point_status, 25)], "sample": [(w_point, 6), (w_point_status, 6)], "n_sample": 12, "write": w_writes_main, "describes": "equality lookups on the order foreign key, half of them also filtered by a low-cardinality status"},
    "rangesort": {"schema": "main", "eval": [(w_range_sort, 15), (w_range_status, 15)], "sample": [(w_range_sort, 5), (w_range_status, 5)], "n_sample": 10, "write": w_writes_main, "describes": "timestamp range scan ordered by amount, mixed with a status-filtered recency listing"},
    "joinagg": {"schema": "main", "eval": [(w_join_agg, 10), (w_join_agg_tier, 10)], "sample": [(w_join_agg, 4), (w_join_agg_tier, 4)], "n_sample": 8, "write": w_writes_main, "describes": "two-table join with GROUP BY, grouped by city in one half and by tier in the other"},
    "sensors": {"schema": "sensor", "eval": [(w_reading_lookup, 20), (w_reading_agg, 12)], "sample": [(w_reading_lookup, 6), (w_reading_agg, 6)], "n_sample": 12, "write": w_writes_sensors, "describes": "device plus metric lookups with an ordered tail, mixed with per-site aggregation, on a different schema"},
}
SCORED = ("point", "rangesort", "joinagg")
HELDOUT = "sensors"
GATE_BENCH = "point"
N_WRITES = 3000


# A realistic DBA default: primary keys plus one foreign-key index per child table.
# The baseline is measured WITH these, so methods must beat a sensible starting point
# rather than a table-scan straw man, and every extra index is charged on the write gate.
# The untuned starting point: primary keys only, no secondary indexes.  Every index a
# method adds is charged to the write gate, and the budget is smaller than the number
# of competing query shapes, so a method has to prioritise rather than index everything.
DEFAULT_INDEXES = {"main": [], "sensor": []}


def schema_of(bench):
    return MAIN_SCHEMA if BENCHES[bench]["schema"] == "main" else SENSOR_SCHEMA


def schema_key(bench):
    return BENCHES[bench]["schema"]


def default_indexes(bench):
    return list(DEFAULT_INDEXES[schema_key(bench)])


def make_db(bench, seed, with_defaults=True):
    rng = random.Random(seed)
    conn = connect()
    if BENCHES[bench]["schema"] == "main":
        build_main(conn, rng)
    else:
        build_sensors(conn, rng)
    if with_defaults:
        for stmt in default_indexes(bench):
            conn.execute(stmt)
        conn.commit()
    return conn


def _mix(specs, rng):
    out = []
    for fn, n in specs:
        out.extend(fn(rng, n))
    return out


def sample_queries(bench, seed):
    spec = BENCHES[bench]
    rng = random.Random(seed)
    return [{"sql": s, "params": list(p)} for s, p in _mix(spec["sample"], rng)]


def eval_queries(bench, seed):
    spec = BENCHES[bench]
    return _mix(spec["eval"], random.Random(seed))


def write_queries(bench, seed):
    spec = BENCHES[bench]
    return spec["write"](random.Random(seed), N_WRITES)


def cost_of(conn, specs, windows=WINDOWS):
    """Executed VM opcodes, counted through the progress handler.  Deterministic.

    Returns (total, per_window) where each entry is the SUM of the opcodes of the
    queries inside that window -- not the cost of the boundary query.
    """
    per_window = []
    total = 0
    acc = 0
    per = max(1, len(specs) // windows)
    for i, item in enumerate(specs):
        sql, params = item[0], item[1]
        counter = [0]
        def handler():
            counter[0] += 1
            return 0
        conn.set_progress_handler(handler, STEP)
        try:
            conn.execute(sql, params).fetchall()
        finally:
            conn.set_progress_handler(None, 0)
        n = counter[0] * STEP
        total += n
        acc += n
        if (i + 1) % per == 0:
            per_window.append(acc)
            acc = 0
    if acc:
        if per_window:
            per_window[-1] += acc
        else:
            per_window.append(acc)
    while len(per_window) < windows:
        per_window.append(0)
    return total, per_window[:windows]


def measure(bench, conn, seed):
    total, windows = cost_of(conn, eval_queries(bench, seed))
    wtotal, wwindows = cost_of(conn, write_queries(bench, seed))
    return {"eval_cost": total, "eval_windows": windows, "write_cost": wtotal, "write_windows": wwindows}
