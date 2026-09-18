"""lfu_slow.py -- frequency policy with a much longer aging period."""


AGING_PERIOD = 30


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
                self.counts[k] = (self.counts[k] * 3) // 4

    def choose_victim(self, resident):
        return min(resident, key=lambda k: (self.counts.get(k, 0), self.recency.index(k) if k in self.recency else -1))

