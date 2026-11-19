#!/usr/bin/env python3
"""Forecast GTA VI trophy earn rates (Exophase) at a case's target.

Refresh-step holders/players forecaster, Python 3.13 standard library
only, deterministic, no network.

Idea (see README.md): Exophase does not update continuously. The page
sits frozen for hours, then refreshes in one step: the tracked-player
count jumps and most earn rates fall, because the newly tracked players
have earned far fewer trophies than the players tracked so far. So this
program works in holders space, not in raw rates.

  1. Collapse the history to its distinct reads (consecutive identical
     reads are one refresh point); between distinct reads nothing changed.
  2. From the distinct reads estimate the refresh gap G (hours between
     distinct reads), the tracked-player multiplier M per refresh, and
     each trophy's cohort earn rate a_i: the share of the players who
     arrive at a refresh (and of the holders revealed by it) who hold
     trophy i, i.e. new holders per new tracked player at a refresh.
     a_i is estimated per interval as delta-holders / delta-players,
     pooled with recency weights (the most recent interval weighs 1,
     older ones decay by 0.85 per interval).
  3. Shrink a_i toward the median a of the trophy's own tier
     (platinum/gold/silver/bronze). The shrinkage weight grows with
     how many new players the history has actually seen, so a trophy
     with a noisy or short history borrows its tier-mates' behaviour.
     A trophy at 100% in every read is held by every tracked player,
     so its holders track the player count exactly (a_i = 1) and it is
     exempt from shrinkage.
  4. The future is a renewal process: the next refresh is due G - S
     hours after the checkpoint, where S is how stale the current page
     already is, then one refresh every G hours (gap lognormal, median
     the due gap / G, sigma 0.4). For a scenario, the player count
     compounds by M per refresh (multiplier decaying 0.9x per future
     refresh, since a launch influx fades) while holders grow by
     a_i per new tracked player; the rate is holders / players. The
     rate therefore asymptotes to what the incoming cohort actually
     earns -- a natural ceiling that damps extrapolation -- and holders
     are capped at the player count, so no rate can exceed 100%.
  5. The five quantiles are the quantiles of that refresh-count
     mixture over deterministic scenarios, widened in logit space by
     a fixed extra spread (SIGMA_EXTRA = 0.30) for parameter
     uncertainty.

Flat-history priors: when the history is completely flat (no refresh
ever observed, as on launch night) the data-driven estimates do not
exist and stated priors take over: gap 5 h, player multiplier 5x per
refresh, new players holding about one trophy each, spread over
trophies in proportion to (rate)^2 -- which puts almost all of a new
player's trophies on the near-universal trophy and almost none on the
rare ones. Staleness S then counts the observed flat window plus 1 h
for the staleness already present at the first probe. These priors are
the only place the launch-night shape is assumed; once the history
shows real refreshes they wash out.

Usage: reads every *.in file in $MAKEFUN_INPUT_DIR (else /input) and
writes /output/<id>.out for each (else $MAKEFUN_OUTPUT_DIR).
"""

import json
import math
import os
import random
import statistics
import sys
from datetime import datetime, timezone

# Fixed extra spread in logit space, chosen on the backtest in README.md.
SIGMA_EXTRA = 0.30
# Lognormal sigma for refresh gaps.
GAP_SIGMA = 0.4
# Decay of the player multiplier per future refresh.
MULT_DECAY = 0.9
# Flat-history priors (see module docstring).
FLAT_GAP_HOURS = 5.0
FLAT_MULTIPLIER = 5.0
# Number of deterministic scenarios for the refresh-count mixture.
N_SCENARIOS = 1000
# Fixed seed: two runs on the same case write byte-identical output.
SEED = 20261119

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]


def parse_time(text):
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def logit(pct):
    p = min(max(pct / 100.0, 0.0001), 0.9999)
    return math.log(p / (1.0 - p))


def inv_logit(x):
    if x >= 0:
        return 100.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return 100.0 * e / (1.0 + e)


def clamp_pct(x):
    return min(max(x, 0.0), 100.0)


def holders_of(rates, players):
    """Holders per trophy implied by rates (percent) and player count."""
    out = []
    for r in rates:
        if r is None:
            out.append(None)
        else:
            out.append(r * players / 100.0)
    return out


def distinct_reads(history):
    """Collapse consecutive identical reads to one refresh point each.

    Returns a list of dicts with slot time, players and rates, keeping
    the first occurrence of each distinct page.
    """
    distinct = []
    prev_key = None
    for read in history:
        key = (read.get("players_tracked"),
               tuple(read.get("rates") or []))
        if key == prev_key:
            continue
        prev_key = key
        distinct.append({
            "slot": parse_time(read["slot"]),
            "players": read.get("players_tracked"),
            "rates": list(read.get("rates") or []),
        })
    return distinct


def fill_rates(distinct, n_trophies):
    """Fill null rates in distinct reads from the previous distinct read."""
    last = [None] * n_trophies
    for d in distinct:
        rates = d["rates"]
        for i in range(n_trophies):
            if i >= len(rates):
                rates.append(None)
            if rates[i] is None:
                rates[i] = last[i] if last[i] is not None else 0.0
            last[i] = rates[i]
        d["rates"] = rates[:n_trophies]
    return distinct


def estimate_from_history(distinct, trophies):
    """Estimate gap, multiplier and per-trophy cohort rates.

    Returns (gap_hours, multiplier, cohort_rates, staleness_hours,
    is_flat, first_slot).
    """
    n = len(trophies)
    last = distinct[-1]
    n_last = float(last["players"])
    last_rates = last["rates"]

    if len(distinct) <= 1:
        # Flat history: stated priors only.
        total_sq = sum(r * r for r in last_rates) or 1.0
        cohort = [(r * r) / total_sq for r in last_rates]
        # The near-universal trophy: almost every new player holds it.
        return (FLAT_GAP_HOURS, FLAT_MULTIPLIER, cohort, True)

    # Refresh gap: median hours between distinct reads.
    gaps = []
    for a, b in zip(distinct, distinct[1:]):
        gaps.append((b["slot"] - a["slot"]).total_seconds() / 3600.0)
    gap = statistics.median(gaps) if gaps else FLAT_GAP_HOURS
    gap = min(max(gap, 0.5), 48.0)

    # Player multiplier per refresh: median of successive ratios.
    ratios = []
    for a, b in zip(distinct, distinct[1:]):
        if a["players"] and b["players"]:
            ratios.append(float(b["players"]) / float(a["players"]))
    mult = statistics.median(ratios) if ratios else 1.0
    mult = min(max(mult, 1.0), 20.0)

    # Per-interval cohort rates, pooled with recency weights.
    n_intervals = len(distinct) - 1
    holders = [holders_of(d["rates"], d["players"]) for d in distinct]
    weights = []
    delta_n_total = 0.0
    for j in range(n_intervals):
        w = 0.85 ** (n_intervals - 1 - j)
        dn = float(distinct[j + 1]["players"]) - float(distinct[j]["players"])
        if dn > 0:
            weights.append((j, w, dn))
            delta_n_total += w * dn
        else:
            weights.append((j, w, 0.0))
    raw = []
    for i in range(n):
        num = 0.0
        for (j, w, dn) in weights:
            if dn <= 0:
                continue
            dh = holders[j + 1][i] - holders[j][i]
            num += w * dh
        a = num / delta_n_total if delta_n_total > 0 else 0.0
        raw.append(min(max(a, 0.0), 1.0))

    # Tier medians for shrinkage.
    tier_median = {}
    for tier in ("platinum", "gold", "silver", "bronze"):
        vals = [raw[i] for i, t in enumerate(trophies)
                if t.get("tier") == tier]
        if vals:
            tier_median[tier] = statistics.median(vals)
    overall = statistics.median(raw) if raw else 0.0

    # Shrinkage weight: more new players seen -> trust the raw rate.
    shrink_w = delta_n_total / (delta_n_total + 1000.0) \
        if delta_n_total > 0 else 0.0

    cohort = []
    for i, t in enumerate(trophies):
        if all(d["rates"][i] >= 100.0 for d in distinct):
            cohort.append(1.0)  # held by every tracked player
            continue
        med = tier_median.get(t.get("tier"), overall)
        cohort.append(min(max(shrink_w * raw[i] + (1.0 - shrink_w) * med,
                              0.0), 1.0))
    return (gap, mult, cohort, False)


def forecast_case(case):
    trophies = case["trophies"]
    n = len(trophies)
    history = case.get("history") or []
    checkpoint = parse_time(case["at"])
    horizon_hours = float(case.get("horizon_minutes", 0)) / 60.0
    levels = case.get("levels") or LEVELS

    if not history:
        # No history at all: fall back to the flat priors on empty rates.
        last_rates = [0.0] * n
        n_last = 1.0
        gap, mult, cohort = FLAT_GAP_HOURS, FLAT_MULTIPLIER, [0.0] * n
        staleness = 1.0
        first_slot = checkpoint
    else:
        distinct = fill_rates(distinct_reads(history), n)
        last = distinct[-1]
        last_rates = last["rates"]
        n_last = float(last["players"])
        gap, mult, cohort, is_flat = estimate_from_history(distinct, trophies)
        first_slot = distinct[0]["slot"]
        if is_flat:
            # Staleness = observed flat window + 1 h already present
            # at the first probe.
            staleness = (checkpoint - first_slot).total_seconds() / 3600.0 + 1.0
        else:
            staleness = (checkpoint - last["slot"]).total_seconds() / 3600.0
            staleness = max(staleness, 0.0)

    holders_last = [r * n_last / 100.0 for r in last_rates]

    # Time to the next refresh: one gap minus the staleness already
    # present, floored so an overdue page refreshes imminently.
    due = gap - staleness
    due_median = max(due, 0.2)

    rng = random.Random(SEED)
    # Scenario player counts at the target: only the final count
    # matters, because holders grow by a_i per new tracked player and
    # the per-refresh increments telescope to (N_final - N_last).
    final_players = []
    for _ in range(N_SCENARIOS):
        t = 0.0
        players = n_last
        refresh = 0
        while refresh < 500:
            median_gap = due_median if refresh == 0 else gap
            step = median_gap * math.exp(GAP_SIGMA * rng.gauss(0.0, 1.0))
            step = max(step, 0.05)
            if t + step > horizon_hours:
                break
            t += step
            refresh += 1
            m = mult * (MULT_DECAY ** (refresh - 1))
            if m < 1.0:
                m = 1.0
            players *= m
            if players > 1e12:
                players = 1e12
                break
        final_players.append(players)

    rows = []
    for i, trophy in enumerate(trophies):
        a = cohort[i]
        h0 = holders_last[i]
        scen_rates = []
        for players in final_players:
            h = h0 + a * (players - n_last)
            if h > players:
                h = players
            if h < 0.0:
                h = 0.0
            scen_rates.append(100.0 * h / players if players > 0 else 0.0)
        scen_rates.sort()
        qs = []
        for tau in levels:
            qs.append(quantile_sorted(scen_rates, tau))
        # Widen in logit space by the fixed extra spread.
        widened = []
        for tau, z, q in zip(levels, Z, qs):
            widened.append(clamp_pct(inv_logit(logit(q) + z * SIGMA_EXTRA)))
        # Round to 4 decimals, keeping the row non-decreasing.
        rounded = []
        prev = 0.0
        for q in widened:
            q = round(q, 4)
            if q < prev:
                q = prev
            rounded.append(q)
            prev = q
        rows.append({"id": trophy["id"], "q": rounded})
    return {"trophies": rows}


def quantile_sorted(sorted_vals, tau):
    """Linear-interpolation quantile of an already sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = tau * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(output_dir, exist_ok=True)
    names = sorted(fn for fn in os.listdir(input_dir) if fn.endswith(".in"))
    for fn in names:
        case_id = fn[:-3]
        with open(os.path.join(input_dir, fn), "r", encoding="utf-8") as f:
            case = json.load(f)
        forecast = forecast_case(case)
        out_path = os.path.join(output_dir, case_id + ".out")
        text = json.dumps(forecast, separators=(",", ":"), sort_keys=False)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
