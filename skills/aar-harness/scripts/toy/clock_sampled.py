"""clock_sampled.py -- CLOCK / second-chance eviction with a sampled reference bit."""


class Policy:
    def __init__(self, capacity):
        self.capacity = capacity
        self.ref = {}
        self.hand = 0
        self.order = []

    def on_access(self, key, hit):
        self.ref[key] = 1
        if key not in self.order:
            self.order.append(key)

    def choose_victim(self, resident):
        keys = sorted(resident)
        if not keys:
            return None
        for _ in range(3 * len(keys) + 3):
            k = keys[self.hand % len(keys)]
            self.hand += 1
            if self.ref.get(k, 0) == 0:
                return k
            self.ref[k] = 0
        return keys[0]

