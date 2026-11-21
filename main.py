"""Forecaster for GTA VI trophy earn rates on Exophase.

Reads one case (a checkpoint, a horizon, the trophy list and every page
read the house kept before the checkpoint) and writes five quantiles of
each trophy's earn rate at the target.  The page only changes when
Exophase refreshes it, so the model works with holders and players
rather than with raw rates: a refresh brings a step of new players whose
own earn pattern dilutes every rate, and between refreshes the holders
of a trophy keep creeping up as tracked players play on.

Two regimes share the same output shaping.  A history with at most one
distinct read has never shown a refresh, so a tuned launch-night prior
drives a Monte Carlo over refresh times and player multipliers.  A
history with several distinct reads identifies, per trophy, how new
holders arrive through two channels (with the incoming players, and
from tracked players who do not hold the trophy yet), shrinks those
rates toward their tier, fits a decaying player-growth curve, and
simulates the horizon in six-hour steps.  Python 3.13, standard
library only, no network, fully deterministic.
"""

import math
import random
from datetime import datetime, timezone

TAUS = (0.05, 0.25, 0.5, 0.75, 0.95)
ZS = (-1.6448536269514722, -0.6744897501960817, 0.0,
      0.6744897501960817, 1.6448536269514722)
PIN_ROW = [99.97, 99.99, 99.99, 99.99, 99.99]
SEED = 20261121
KNOWN_TIERS = ("platinum", "gold", "silver", "bronze")


def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def logit_pct(pct):
    """Log-odds of a percentage, the percentage clamped first."""
    p = clamp(pct, 0.01, 99.99)
    return math.log(p / (100.0 - p))


def inv_logit(x):
    """Inverse log-odds back to a percentage, overflow-safe."""
    if x >= 0.0:
        return 100.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return 100.0 * e / (1.0 + e)


def sample_quantile(sorted_vals, tau):
    """Linear-interpolated quantile of an already sorted sample."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = tau * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def five_quantiles(values):
    ordered = sorted(values)
    return [sample_quantile(ordered, t) for t in TAUS]


def widen(quantiles, sigma):
    """Spread five quantiles in logit space, then force monotone."""
    out = []
    for q, z in zip(quantiles, ZS):
        v = inv_logit(logit_pct(q) + z * sigma)
        v = clamp(round(v, 4), 0.0, 100.0)
        if out and v < out[-1]:
            v = out[-1]
        out.append(v)
    return out


def median_of(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def parse_time(text):
    s = str(text).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def holders_of(rate_pct, players):
    return rate_pct * players / 100.0


def distinct_reads(case):
    """Collapse a case history to its distinct reads, gaps filled.

    A read that repeats the previously kept read exactly (same player
    count, same raw rate list) is the same page seen again and drops
    out.  A missing or null rate inherits the trophy's last seen rate,
    or 0.0 when the trophy has never shown one.  An empty history
    becomes a single synthetic read at the checkpoint.
    """
    n = len(case["trophies"])
    history = case.get("history") or []
    kept = []
    prev_key = None
    for read in history:
        raw_rates = read.get("rates") or []
        key = (read.get("players_tracked"), tuple(raw_rates))
        if kept and key == prev_key:
            continue
        kept.append(read)
        prev_key = key
    if not kept:
        return [{"when": parse_time(case["at"]), "players": 1.0,
                 "rates": [0.0] * n}]
    last_seen = [None] * n
    reads = []
    for read in kept:
        raw_rates = read.get("rates") or []
        filled = []
        for i in range(n):
            v = raw_rates[i] if i < len(raw_rates) else None
            if v is None:
                filled.append(last_seen[i] if last_seen[i] is not None
                              else 0.0)
            else:
                fv = float(v)
                filled.append(fv)
                last_seen[i] = fv
        players = read.get("players_tracked")
        reads.append({
            "when": parse_time(read["slot"]),
            "players": float(players) if players is not None else 0.0,
            "rates": filled,
        })
    return reads


def forecast_flat(case, reads):
    """Single distinct read: simulate refreshes from the tuned prior."""
    n = len(case["trophies"])
    last = reads[-1]
    base_rates = last["rates"]
    n0 = last["players"]
    horizon_h = float(case["horizon_minutes"]) / 60.0
    checkpoint = parse_time(case["at"])
    age_h = (checkpoint - reads[0]["when"]).total_seconds() / 3600.0
    staleness = age_h + 0.709
    first_due = max(3.306 - staleness, 0.2)

    rng = random.Random(SEED)
    final_players = []
    for _ in range(1000):
        t = 0.0
        players = float(n0)
        done = 0
        for _step in range(500):
            med = first_due if done == 0 else 3.306
            gap = max(med * math.exp(0.303 * rng.gauss(0.0, 1.0)), 0.05)
            if t + gap > horizon_h:
                break
            t += gap
            done += 1
            mult = 5.509 * math.exp(0.112 * rng.gauss(0.0, 1.0))
            mult *= 0.951 ** (done - 1)
            players *= max(mult, 1.0)
            if players > 1e12:
                players = 1e12
                break
        final_players.append(players)

    weights = [0.209 * r + 0.791 * (r ** 1.844) for r in base_rates]
    total_w = sum(weights)
    if total_w > 0.0:
        share = [w / total_w * 1.008 for w in weights]
    else:
        share = [0.0] * n

    rows = []
    for i in range(n):
        r = base_rates[i]
        if r >= 100.0:
            rows.append(list(PIN_ROW))
            continue
        h0 = holders_of(r, n0)
        scen_rates = []
        for p_end in final_players:
            held = clamp(h0 + share[i] * (p_end - n0), 0.0, p_end)
            scen_rates.append(100.0 * held / p_end if p_end > 0.0
                              else 0.0)
        rows.append(widen(five_quantiles(scen_rates), 0.142))
    return rows


def fit_two_channel(reads, n):
    """Per-trophy raw (a, g): holders arriving per new player, and per
    non-holder per hour, from recency-weighted interval regressions."""
    k_intervals = len(reads) - 1
    counts = [rd["players"] for rd in reads]
    held = [[holders_of(rd["rates"][i], rd["players"]) for i in range(n)]
            for rd in reads]
    hours = [(rd["when"] - reads[0]["when"]).total_seconds() / 3600.0
             for rd in reads]
    spans = [max(hours[k + 1] - hours[k], 0.05)
             for k in range(k_intervals)]
    raw_a = []
    raw_g = []
    for i in range(n):
        sxx = sxy = sxz = syz = szz = 0.0
        for k in range(k_intervals):
            wk = 0.85 ** (k_intervals - 1 - k)
            x = counts[k + 1] - counts[k]
            z = (counts[k] - held[k][i]) * spans[k]
            y = held[k + 1][i] - held[k][i]
            sxx += wk * x * x
            sxy += wk * x * y
            sxz += wk * x * z
            syz += wk * y * z
            szz += wk * z * z
        det = (sxx + 1e-9) * (szz + 1e-9) - sxz * sxz
        if abs(det) < 1e-12:
            a = sxy / sxx if sxx > 0.0 else 0.0
            g = 0.0
        else:
            a = (sxy * (szz + 1e-9) - syz * sxz) / det
            g = (syz * (sxx + 1e-9) - sxy * sxz) / det
        raw_a.append(clamp(a, 0.0, 1.0))
        raw_g.append(clamp(g, 0.0, 0.05))
    return raw_a, raw_g, counts, held, hours, spans


def shrink_channels(trophies, reads, raw_a, raw_g):
    """Pull each trophy's raw channels toward its tier's medians."""
    n = len(trophies)
    tiers = [t.get("tier") for t in trophies]
    med_a_all = median_of(raw_a)
    med_g_all = median_of(raw_g)
    med_a_tier = {}
    med_g_tier = {}
    for tier in KNOWN_TIERS:
        idx = [i for i in range(n) if tiers[i] == tier]
        if idx:
            med_a_tier[tier] = median_of([raw_a[i] for i in idx])
            med_g_tier[tier] = median_of([raw_g[i] for i in idx])
    last = reads[-1]
    a_fin = []
    g_fin = []
    for i in range(n):
        own = holders_of(last["rates"][i], last["players"])
        w = own / (own + 40.0)
        trust = min(1.0, own / 20.0)
        ma = med_a_tier.get(tiers[i], med_a_all)
        mg = med_g_tier.get(tiers[i], med_g_all)
        prior_a = 0.5 * (last["rates"][i] / 100.0) + 0.25 * ma * trust
        prior_g = mg * trust
        a_fin.append(clamp(w * raw_a[i] + (1.0 - w) * prior_a, 0.0, 1.0))
        g_fin.append(clamp(w * raw_g[i] + (1.0 - w) * prior_g,
                           0.0, 0.05))
    return a_fin, g_fin


def fit_growth(counts, hours, spans):
    """Decaying exponential for the log growth rate of the player
    count, fitted by grid search over the last few intervals."""
    k_intervals = len(counts) - 1
    rho = []
    mids = []
    for k in range(k_intervals):
        lo = math.log(max(counts[k], 1e-9))
        hi = math.log(max(counts[k + 1], 1e-9))
        rho.append((hi - lo) / spans[k])
        mids.append(0.5 * (hours[k] + hours[k + 1]))
    keep_from = k_intervals - min(6, k_intervals)
    kept = list(range(keep_from, k_intervals))
    r_last = rho[kept[-1]]
    anchor = mids[kept[-1]]
    best = None
    for tau in (24.0, 48.0, 96.0, 200.0, 400.0):
        for frac in (0.0, 0.1, 0.25, 0.45):
            r_inf = frac * r_last
            amp = r_last - r_inf
            err = 0.0
            for k in kept:
                pred = r_inf + amp * math.exp(-(mids[k] - anchor) / tau)
                err += (pred - rho[k]) ** 2
            if best is None or err < best[0]:
                best = (err, tau, r_inf, amp)
    _err, tau, r_inf, amp = best
    return tau, r_inf, amp, anchor


def forecast_multi(case, reads):
    """Several distinct reads: shrunk two-channel simulation."""
    trophies = case["trophies"]
    n = len(trophies)
    raw_a, raw_g, counts, held, hours, spans = fit_two_channel(reads, n)
    a_fin, g_fin = shrink_channels(trophies, reads, raw_a, raw_g)
    tau, r_inf, amp, anchor = fit_growth(counts, hours, spans)

    universal = [all(rd["rates"][i] >= 100.0 for rd in reads)
                 for i in range(n)]
    horizon_h = float(case["horizon_minutes"]) / 60.0
    n_steps = max(1, math.ceil(horizon_h / 6.0))
    t_last = hours[-1]

    rng = random.Random(SEED)
    scen_rates = [[] for _ in range(n)]
    for _scen in range(600):
        level = math.exp(0.25 * rng.gauss(0.0, 1.0))
        tau_s = tau * math.exp(0.45 * rng.gauss(0.0, 1.0))
        a_s = [clamp(a_fin[i] * math.exp(0.25 * rng.gauss(0.0, 1.0)),
                     0.0, 1.0) for i in range(n)]
        g_s = [clamp(g_fin[i] * math.exp(0.30 * rng.gauss(0.0, 1.0)),
                     0.0, 0.075) for i in range(n)]
        r_inf_s = max(r_inf * level, 0.0)
        amp_s = amp * level
        players = counts[-1]
        held_now = [held[-1][i] for i in range(n)]
        elapsed = 0.0
        for step in range(n_steps):
            h = min(6.0, horizon_h - elapsed)
            if h < 0.0:
                h = 0.0
            t_mid = t_last + step * 6.0 + 0.5 * h
            rate = clamp(r_inf_s + amp_s * math.exp(
                -(t_mid - anchor) / tau_s), 0.0, 0.5)
            d_players = players * (math.exp(rate * h) - 1.0)
            for i in range(n):
                gain = a_s[i] * d_players + g_s[i] * (players
                                                      - held_now[i]) * h
                held_now[i] = clamp(held_now[i] + gain, 0.0,
                                    players + d_players)
            players += d_players
            elapsed += h
        for i in range(n):
            scen_rates[i].append(100.0 * held_now[i] / players
                                 if players > 0.0 else 0.0)

    rows = []
    for i in range(n):
        if universal[i]:
            rows.append(list(PIN_ROW))
        else:
            rows.append(widen(five_quantiles(scen_rates[i]), 0.15))
    return rows


def forecast_case(case):
    """Five quantiles per trophy, in the case's trophy order."""
    reads = distinct_reads(case)
    if len(reads) <= 1:
        return forecast_flat(case, reads)
    return forecast_multi(case, reads)


def run_directory(in_dir, out_dir):
    """Forecast every *.in case in a directory, in filename order."""
    import json
    import os
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(os.listdir(in_dir)):
        if not name.endswith(".in"):
            continue
        with open(os.path.join(in_dir, name), "r",
                  encoding="utf-8") as fh:
            case = json.load(fh)
        rows = forecast_case(case)
        payload = {"trophies": [
            {"id": trophy["id"], "q": row}
            for trophy, row in zip(case["trophies"], rows)
        ]}
        text = json.dumps(payload, separators=(",", ":")) + "\n"
        out_name = name[:-len(".in")] + ".out"
        with open(os.path.join(out_dir, out_name), "w",
                  encoding="utf-8") as fh:
            fh.write(text)


def main():
    import os
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    run_directory(in_dir, out_dir)


if __name__ == "__main__":
    main()
