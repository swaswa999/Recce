"""Decide which road the rider is on, out of every road in a bundle.

With one road loaded this was a windowed nearest-node scan. With thousands it
becomes a decision problem, and the failure to design against is not "picks the
wrong road once" but **flapping** — switching back and forth at a junction and
re-announcing corners the rider has already passed.

Three parts:

1. A grid index, so a fix searches ~10 candidate nodes rather than a million.
2. Scoring on perpendicular distance AND heading agreement. Distance alone
   picks the wrong road at an overpass, beside a frontage road, or on a
   switchback that doubles back within a few metres — which the Tail of the
   Dragon does repeatedly.
3. Hysteresis. A challenger must win several consecutive fixes before it takes
   over, so noise cannot swap roads.

Deliberately not an HMM. Nearest-segment-with-heading plus hysteresis is enough
for rural roads, which is where this product lives, and it is debuggable at the
roadside in a way a Viterbi lattice is not. Escalate only if measurement says so.
"""
import math

import numpy as np

# A fix further than this from every road is treated as off-network. Generous
# because GPS under tree cover is poor exactly where these roads are.
MAX_OFFROAD_M = 60.0

# Heading disagreement is scored as an equivalent distance penalty: at 90 degrees
# out, a candidate is treated as this much further away. Enough to reject a
# crossing road while tolerating GPS heading noise at low speed.
HEADING_PENALTY_M = 120.0

# Below this speed GPS heading is meaningless, so heading is not scored at all.
MIN_SPEED_FOR_HEADING = 2.5   # m/s, ~9 km/h

# Consecutive fixes a challenger must win before it takes over.
SWITCH_PATIENCE = 3


class Matcher:
    def __init__(self, bundle, max_offroad=MAX_OFFROAD_M,
                 patience=SWITCH_PATIENCE):
        self.roads = bundle["roads"]
        self.cell = bundle.get("cell", 0.01)
        self.index = bundle["index"]
        self.max_offroad = max_offroad
        self.patience = patience

        self.lat0 = math.radians(float(np.mean(
            [r["lat"][0] for r in self.roads])) if self.roads else 0.0)
        self._xy = [self._to_xy(r) for r in self.roads]

        self.current = None       # road index we believe we are on
        self.challenger = None
        self.challenger_hits = 0
        self.last_s = None

    def _to_xy(self, road):
        lon = np.asarray(road["lon"]); lat = np.asarray(road["lat"])
        return (lon * 111320.0 * math.cos(self.lat0), lat * 110540.0)

    def _candidates(self, lon, lat):
        c = self.cell
        gy, gx = int(math.floor(lat / c)), int(math.floor(lon / c))
        out = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                out.extend(self.index.get(f"{gy+dy},{gx+dx}", ()))
        return out

    def _score(self, ri, ni, px, py, heading):
        """Distance from the fix to the segment at this node, plus a heading
        penalty. Returns (score, distance, arc-length position)."""
        xs, ys = self._xy[ri]
        n = len(xs)
        best = None
        for a in (ni - 1, ni):
            if a < 0 or a + 1 >= n:
                continue
            ax, ay, bx, by = xs[a], ys[a], xs[a + 1], ys[a + 1]
            vx, vy = bx - ax, by - ay
            L2 = vx * vx + vy * vy
            if L2 <= 1e-9:
                continue
            t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
            cx, cy = ax + t * vx, ay + t * vy
            dist = math.hypot(px - cx, py - cy)
            node_s = self.roads[ri]["node_s"]
            s = node_s[a] + t * (node_s[a + 1] - node_s[a])
            pen = 0.0
            if heading is not None:
                bearing = math.atan2(vy, vx)
                # a road is bidirectional: being 180 degrees out is still a match
                err = abs(math.atan2(math.sin(heading - bearing),
                                     math.cos(heading - bearing)))
                err = min(err, math.pi - err)
                pen = HEADING_PENALTY_M * (err / (math.pi / 2))
            cand = (dist + pen, dist, s)
            if best is None or cand[0] < best[0]:
                best = cand
        return best

    def update(self, lon, lat, heading=None, speed=None):
        """One GPS fix. Returns a dict describing where we think we are, or None
        when off-network.

        `heading` is radians in the local ENU frame (atan2(dy, dx)), or None.
        """
        if speed is not None and speed < MIN_SPEED_FOR_HEADING:
            heading = None

        px = lon * 111320.0 * math.cos(self.lat0)
        py = lat * 110540.0

        best_by_road = {}
        for ri, ni in self._candidates(lon, lat):
            got = self._score(ri, ni, px, py, heading)
            if got is None:
                continue
            if ri not in best_by_road or got[0] < best_by_road[ri][0]:
                best_by_road[ri] = got

        if not best_by_road:
            self._miss()
            return None

        ranked = sorted(best_by_road.items(), key=lambda kv: kv[1][0])
        top_ri, (top_score, top_dist, top_s) = ranked[0]
        if top_dist > self.max_offroad:
            self._miss()
            return None

        # Staying put is preferred: only a challenger that wins `patience`
        # consecutive fixes takes over. Without this, two roads a few metres
        # apart trade the lead on GPS noise and every corner is re-announced.
        if self.current is None:
            self._commit(top_ri, top_s)
        elif top_ri == self.current:
            self.challenger, self.challenger_hits = None, 0
            self.last_s = best_by_road[self.current][2]
        else:
            if self.current in best_by_road and \
                    best_by_road[self.current][1] <= self.max_offroad:
                # still plausibly on the current road — make the challenger earn it
                if self.challenger == top_ri:
                    self.challenger_hits += 1
                else:
                    self.challenger, self.challenger_hits = top_ri, 1
                if self.challenger_hits >= self.patience:
                    self._commit(top_ri, top_s)
                else:
                    self.last_s = best_by_road[self.current][2]
                    return self._state(self.current, best_by_road[self.current][1])
            else:
                self._commit(top_ri, top_s)

        ri = self.current
        return self._state(ri, best_by_road.get(ri, (0, top_dist, top_s))[1])

    def _commit(self, ri, s):
        if ri != self.current:
            self.current = ri
            self.last_s = s
            self.on_switch()
        self.challenger, self.challenger_hits = None, 0
        self.last_s = s

    def _miss(self):
        self.challenger, self.challenger_hits = None, 0

    def on_switch(self):
        """Hook: the app clears its spoken set here, so moving onto a new road
        does not stay silent about corners it announced on the previous one."""

    def _state(self, ri, dist):
        return {"road": ri, "name": self.roads[ri]["name"],
                "s": self.last_s, "dist": dist}
