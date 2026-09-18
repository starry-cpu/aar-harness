"""lfu_aged.py -- LFU with periodic halving (aging).

Reference "good method" for the toy domain: it improves every scored workload.
Also usable as a template: a method artifact is a directory whose policy.py
exposes exactly this interface.
"""


AGING_PERIOD = 10


class Policy:
    def __init__(self, capacity):
        self.capacity = capacity
        self.counts = {}
        self.recency = []
        self.n = 0

    def on_access(self, key, hit):
        self.counts[key] = self.counts.get(key, 0) + 1
        if key in self.recency:
            self.recency.remove(key)
        self.recency.append(key)
        self.n += 1
        if self.n % (AGING_PERIOD * self.capacity) == 0:
            for k in list(self.counts):
                self.counts[k] = self.counts[k] // 2

    def choose_victim(self, resident):
        def rank(k):
            return (self.counts.get(k, 0), self.recency.index(k) if k in self.recency else -1)
        return min(resident, key=rank)

