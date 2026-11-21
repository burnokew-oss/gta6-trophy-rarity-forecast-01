# gta6-trophy-rarity-forecast-01

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/burnokew-oss/gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/burnokew-oss/gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A forecaster that predicts the earn rate of every Grand Theft Auto VI trophy on Exophase on 26 November 2026, as five quantiles (5%, 25%, 50%, 75%, 95%) per trophy, from the history of reads of the Exophase page. Grand Theft Auto VI launched on 19 November 2026; the final case is cut at the deadline, 2026-11-21 11:30 UTC, and targets 2026-11-26 00:00 UTC.

## Method

Round 2 replaces the round-1 estimator with a two-regime forecaster that works in holders and players, never in raw rates. The history is first collapsed to its distinct reads: a read that repeats the previous kept read exactly is the same Exophase page seen again and drops out, and a missing rate inherits the trophy's last seen rate (0.0 if it has never shown one). A trophy sitting at 100% in every distinct read is pinned to [99.97, 99.99, 99.99, 99.99, 99.99], and every other forecast is a sample quantile spread in logit space at the end.

With at most one distinct read, no refresh has ever been observed, so a tuned launch-night prior takes over. Refresh gaps are lognormal (median 3.306 hours, sigma 0.303), with the first refresh due after what is left of the median gap once the page's staleness (the flat window plus 0.709 hours) is subtracted, floored at 0.2 hours. Each refresh multiplies the tracked-player count by a lognormal step (median 5.509, sigma 0.112) that fades by 0.951 per refresh. One thousand seeded scenarios give a distribution of the final player count; each trophy then claims a share of the newcomers through a cohort weight mixing its last rate linearly and as a power (0.209 * r + 0.791 * r^1.844, rescaled by 1.008), so newcomers overwhelmingly hold the common trophies and almost none of the rare ones. The five quantiles of the resulting rates are widened in logit space with sigma 0.142.

With several distinct reads, each trophy is fitted on two channels at once: holders arriving with each new tracked player, and holders arriving per hour from tracked players who do not hold the trophy yet. The fit is a recency-weighted two-regressor regression over the intervals between distinct reads (weights 0.85 per step back, a small ridge for stability), clipped to sane ranges and then shrunk toward the median behaviour of the trophy's own tier, with the shrinkage weight set by how many holders the trophy already has — a trophy with no holders stays at zero. Player growth itself is modelled as a log rate that decays exponentially toward a fraction of its last value; the decay constant and the floor fraction come from a small grid search over the last few intervals. Six hundred seeded scenarios then step the horizon in six-hour steps, jittering the growth level, the decay constant and every trophy's two channels, and the scenario rates are widened in logit space with sigma 0.15. Because holders can never exceed players, no rate can pass 100%, and as growth fades each rate settles toward what incoming players actually earn instead of extrapolating a launch-night slope forever.

## Backtest

The kit ships no practice answers, so the 04:30Z refresh page was reconstructed from the two aggregates the competition documents publish for it: 638 -> 3,868 players tracked and 943 -> 4,276 trophies earned. The universal trophy (100% at launch) is held by all 3,230 newcomers; the remaining new holders were spread three ways — in proportion to the launch rates, in proportion to their squares, and concentrated on the five most-held trophies — always keeping holders non-decreasing, non-universal rates non-rising, and the total at exactly 4,276. Scored with the competition's pinball loss on the logit scale, this entry gets 0.067 / 0.064 / 0.158 under the three reconstructions (mean 0.096) on both practice cases, against 1.49 / 1.51 / 1.67 for the persistence forecast that repeats the last rate — roughly a ten-to-twenty-fold improvement, and the practice outputs are byte-identical across repeated runs at about a tenth of a second per case.

## Running

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, deterministic, no network. The program reads one case from the input directory and writes `/output/<id>.out` — 55 rows, one per trophy, five finite non-decreasing quantiles in [0, 100] per row — in well under the 8-second limit per case.

MIT licensed. See the bounty page: https://make.fun/competitions/gta6-trophy-rarity-forecast-01
