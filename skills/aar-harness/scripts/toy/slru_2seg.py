"""slru_2seg.py -- two-segment LRU (probationary + protected).

Reference "partial method": it beats the baseline on the uniform and scan
workloads but regresses on the zipf workload, so the geometric-mean rule zeroes
its aggregate.  This is the fixture that demonstrates that rule.
"""


class Policy:
    def __init__(self, capacity):
        self.capacity = capacity
        self.protected_cap = max(1, int(capacity * 0.8))
        self.probation = []
        self.protected = []

    def _touch(self, lst, key):
        if key in lst:
            lst.remove(key)
        lst.append(key)

    def on_access(self, key, hit):
        if key in self.protected:
            self._touch(self.protected, key)
        elif key in self.probation:
            self.probation.remove(key)
            self._touch(self.protected, key)
        else:
            self._touch(self.probation, key)

    def choose_victim(self, resident):
        while len(self.protected) > self.protected_cap:
            self.probation.insert(0, self.protected.pop(0))
        for k in self.probation:
            if k in resident:
                return k
        for k in self.protected:
            if k in resident:
                return k
        return sorted(resident)[0]

