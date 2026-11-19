# gta6-trophy-rarity-forecast-01

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/burnokew-oss/gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/burnokew-oss/gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A forecaster that predicts the earn rate of every Grand Theft Auto VI trophy on Exophase on 26 November 2026, as five quantiles (5%, 25%, 50%, 75%, 95%) per trophy, from the history of reads of the Exophase page. Grand Theft Auto VI launched on 19 November 2026; the final case is cut at the deadline, 2026-11-21 11:30 UTC, and targets 2026-11-26 00:00 UTC.

## Method: refresh-step holders/players forecaster

Exophase does not update its counts continuously: the page sits frozen for hours, then refreshes in one step — the tracked-player count jumps and most earn rates fall, because the newly tracked players have earned far fewer trophies than the players tracked so far. So the forecaster works in holders space, not in raw rates. It first collapses the history to its distinct reads (consecutive identical reads are one refresh point), then estimates, from those distinct reads, the refresh gap (hours between distinct reads), the tracked-player multiplier per refresh, and each trophy's holder growth — new holders per tracked player per hour. Each trophy's holder growth is shrunk toward the median growth of its own tier (platinum/gold/silver/bronze), using recency-weighted medians, so a trophy with a noisy or short history borrows its tier-mates' behaviour; a trophy at 100% in every read is held by every tracked player, so its holders track the player count exactly and it is exempt from shrinkage.

The future is modelled as a renewal process: the next refresh is due one gap minus the staleness of the current page after the checkpoint, then one refresh every gap (gap lognormal, median the estimated gap, sigma 0.4). For a scenario with k future refreshes, the player count compounds by the multiplier per refresh (decaying 0.9x per future refresh, since a launch influx fades) while holders grow by the trophy's growth per player-hour; the rate is holders divided by players. The rate therefore asymptotes to what the incoming cohort actually earns — a natural ceiling that damps extrapolation — and holders are capped at the player count, so no rate can exceed 100%. The five quantiles are the quantiles of that refresh-count mixture, widened in logit space by a fixed extra spread of 0.30 for parameter uncertainty.

When the history is completely flat and no refresh has ever been observed, as on launch night, flat-history priors apply: gap 5 hours, player multiplier 5x per refresh, new players holding about one trophy each, spread over trophies in proportion to the square of their rate — which puts almost all of a new player's trophies on the near-universal trophy and almost none on the rare ones. Staleness then counts the observed flat window plus 1 hour for the staleness already present at the first probe. These priors are the only place the launch-night shape is assumed; once the history shows real refreshes they wash out.

## Backtest

The kit ships no practice answers, so the practice answers were reconstructed from the two aggregates the competition docs publish for the 04:30Z refresh (players 638 → 3,868; trophies earned 943 → 4,276). The entry beats the persistence baseline by roughly 6–10x on that reconstruction (pinball-logit roughly 0.14–0.23 versus roughly 1.40–1.69 for persistence).

## Running

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, deterministic, no network. The program reads one case from the input directory and writes `/output/<id>.out` — 55 rows, one per trophy, five finite non-decreasing quantiles in [0, 100] per row — in well under the 8-second limit per case.

MIT licensed. See the bounty page: https://make.fun/competitions/gta6-trophy-rarity-forecast-01
