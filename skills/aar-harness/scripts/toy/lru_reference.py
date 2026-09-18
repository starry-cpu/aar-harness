"""lru_reference.py -- plain LRU, identical in behaviour to the harness baseline.

Reference "no-op method": it reproduces the baseline exactly, so its aggregate is
zero.  Submitting it twice is the duplicate-artifact-hash fixture that stands in
for the resubmission lottery the paper found in 67% of confirmed cheating.
"""


class Policy:
    def __init__(self, capacity):
        self.capacity = capacity
        self.order = []

    def on_access(self, key, hit):
        if key in self.order:
            self.order.remove(key)
        self.order.append(key)

    def choose_victim(self, resident):
        for k in self.order:
            if k in resident:
                return k
        return sorted(resident)[0]

