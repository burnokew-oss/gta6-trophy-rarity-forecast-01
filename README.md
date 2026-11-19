# gta6-trophy-rarity-forecast-01

Forecast, for every Grand Theft Auto VI PlayStation 5 trophy, its Exophase
earn rate at 2026-11-26T00:00:00Z as five quantiles (5%, 25%, 50%, 75%,
95%), from the house's recorded reads of the trophy page up to the case
checkpoint. Python 3.13, standard library only, deterministic, no network.

## Method: refresh-step holders/players forecaster

Exophase does not update its counts continuously: the page sits frozen for
hours, then refreshes in one step — the tracked-player count jumps and most
earn rates fall, because the newly tracked players have earned far fewer
trophies than the players tracked so far. Fitting a smooth curve through
the raw reads therefore misses the mechanism. This entry works in holders
space instead:

1. **Distinct reads.** The history is collapsed to its distinct pages
   (consecutive identical reads are one refresh point). Between distinct
   reads nothing changed.
2. **Per-refresh estimates.** From the distinct reads it estimates the
   refresh gap G (hours between distinct reads), the tracked-player
   multiplier M per refresh, and each trophy's holder growth v_i — new
   holders per tracked player per hour.
3. **Shrinkage.** v_i is shrunk toward the median v of the trophy's own
   tier (platinum/gold/silver/bronze), with recency-weighted medians, so
   a trophy with a noisy or short history borrows its tier-mates'
   behaviour. A trophy at 100% in every read is held by every tracked
   player, so its holders track N exactly and it is exempt from shrinkage.
4. **Refresh-count mixture.** The future is a renewal process: the next
   refresh is due G − S hours from the checkpoint, where S is how stale
   the current page already is, then one refresh every G hours (gap
   lognormal, median G, sigma 0.4). For a scenario with k future
   refreshes, N compounds by M per refresh (multiplier decaying 0.9x per
   future refresh, since a launch influx fades) while holders grow by v_i
   per player-hour; the rate is holders / players. The rate therefore
   asymptotes to what the incoming cohort actually earns — a natural
   ceiling that damps extrapolation — and holders are capped at N, so no
   rate can exceed 100%.
5. **Spread.** The five quantiles are the quantiles of that refresh-count
   mixture, widened in logit space by a fixed extra spread
   (SIGMA_EXTRA = 0.30, chosen on the backtest below) for parameter
   uncertainty.

**Flat-history priors.** When the history is completely flat (no refresh
ever observed, as on launch night), the data-driven estimates do not exist
and stated priors take over: gap 5 h, player multiplier 5x per refresh,
new players holding about one trophy each, spread over trophies in
proportion to (rate)^2 — which puts ~all of a new player's trophies on the
near-universal trophy and almost none on the rare ones. Staleness S then
counts the observed flat window plus 1 h for the staleness already present
at the first probe. These priors are the only place the launch-night shape
is assumed; once the history shows real refreshes they wash out.

## Backtest (measured locally, 2026-11-19)

The kit ships no practice answers, so the practice answers were
**reconstructed** from the two aggregates the competition docs publish
for the 04:30Z refresh (players 638 → 3,868; trophies earned 943 → 4,276):
old holders h_i = round(rate_i × 638 / 100) (sums to 943, as published);
the trophy at 100% stayed 100%, so all 3,230 new players hold it; the
remaining 103 new holds were distributed three ways to test sensitivity:
(A) proportional to old holders, (B) pure dilution (none), (C) on the
five most-held trophies. Mean pinball loss on the logit scale, both
practice cases (identical numbers — the two cases share the same history
shape and the same reconstructed answer):

| sigma_extra | A: mine vs persistence | B: mine vs persistence | C: mine vs persistence |
|---|---|---|---|
| 0.00 | 0.220 vs 1.403 | 0.430 vs 1.687 | 0.425 vs 1.580 |
| 0.15 | 0.249 vs 1.403 | 0.331 vs 1.687 | 0.338 vs 1.580 |
| **0.30** | **0.279 vs 1.403** | **0.321 vs 1.687** | **0.332 vs 1.580** |
| 0.45 | 0.309 vs 1.403 | 0.341 vs 1.687 | 0.354 vs 1.580 |
| 0.60 | 0.339 vs 1.403 | 0.371 vs 1.687 | 0.384 vs 1.580 |

The entry uses sigma_extra = 0.30 (best worst-case across the three
reconstructions; the house baseline's published practice loss is ~1.51,
and my replication of the persistence baseline scores 1.40–1.69 across
the same reconstructions, which brackets 1.51 and corroborates the
reconstruction).

Honest caveat: a within-history truncation backtest (cut the flat history
early, forecast the next read) favours persistence (0.014 vs my 0.092),
because the next read is unchanged and my entry pays for insuring
against a refresh that did not happen in that 30-minute window. That
backtest is uninformative here — the history is perfectly flat — and the
decision-relevant comparison is the one against the refreshed answers
above, where the entry wins by ~4–5x.

## Local verification (measured locally, 2026-11-19)

- Ran on both practice cases (`MAKEFUN_INPUT_DIR`/`MAKEFUN_OUTPUT_DIR`
  stand-ins): valid output for p00 and p01 — 55 rows, each id once, five
  finite non-decreasing quantiles in [0, 100], 2,804 bytes per file
  (limit 65,536).
- Determinism: two runs write byte-identical outputs (`cmp` clean).
- Runtime: ~0.17 s for both cases together (limit 8 s per case).
- Also exercised on a synthetic final-like case (6 distinct refreshes,
  N 638 → 100,000, 6,510-minute horizon): valid format, sane values
  (the 100% trophy stays ~99.99, early trophies dilute mildly).
- Kit check (`node cli/makefun.mjs check --kit . --repo <repo>
  --worktree`, run before the competition opened): **pass** snapshot,
  license_osi (MIT), entrypoint (main.py, python3.13); **fail**
  competition_open (check ran at 09:16 UTC, opening is 11:30 UTC —
  a timing artifact, not a code problem) and transcripts_present (no
  transcripts bundled yet — a submission step for the coordinator).
  The remaining checks are skipped or decided at submission
  (repo public/owner/created-after-open/commit).

## Known limitations

- The practice answers above are reconstructions, not the kit's answers
  (the kit ships none); the backtest numbers depend on that
  reconstruction, though all three variants agree the entry beats
  persistence by a wide margin.
- The flat-history priors (gap 5 h, multiplier 5x, one trophy per new
  player) are guesses stated in the code; they matter only while the
  history shows no refresh.
- The future player multiplier is assumed to decay 0.9x per refresh and
  per-refresh holder growth is assumed scale-invariant in N; if the real
  influx stays hot late into the week, the final's N growth will be
  understated.
- No server score exists yet — the practice is graded by the server on
  submission, and the final is graded after 2026-11-26.

## Run

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```
