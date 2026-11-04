# Phase 6 forecast evaluation (synthetic data)

600 series (train lengths [12, 18, 24, 36, 48]), 3-month holdout, seed 7. **Synthetic, same-author archetypes: a check of behaviour under assumptions, not a measure of real-world accuracy.** `gbm_eval_only` is pooled over other synthetic series from the same archetypes (in-distribution, so it is flattered) and is never used for real users.

## Mean MASE over the holdout (lower is better; 1.0 = in-sample 'repeat last month')

| method | series | mean MASE | median MASE |
|---|---:|---:|---:|
| ets_seasonal | 240 | 1.055 | 0.8524 |
| ets_ann | 600 | 1.097 | 0.8156 |
| auto | 600 | 1.1067 | 0.7946 |
| gbm_eval_only | 600 | 1.1358 | 0.8786 |
| moving_average_3 | 600 | 1.1922 | 0.874 |
| ets_damped_trend | 600 | 1.1964 | 0.8419 |
| naive | 600 | 1.2036 | 0.9057 |
| moving_average_6 | 600 | 1.2559 | 0.9371 |
| drift | 600 | 1.2643 | 1.0009 |
| median_12 | 600 | 1.3249 | 0.9539 |
| seasonal_naive | 600 | 1.7309 | 1.2143 |

*Series counts differ because a method only runs when the history is long enough (e.g. `ets_seasonal` needs 36 training months). Compare methods with different counts through the by-length table or the paired comparisons, not this column alone.*

Hindsight oracle (best eligible fixed method per series, unattainable): **0.7268**

## Paired differences (negative = first method better)

| a | b | n | mean diff | 95% bootstrap CI | a better on |
|---|---|---:|---:|---|---:|
| auto | naive | 600 | -0.0969 | [-0.1518, -0.0405] | 53% |
| auto | moving_average_3 | 600 | -0.0855 | [-0.1376, -0.0331] | 46% |
| auto | median_12 | 600 | -0.2183 | [-0.2955, -0.143] | 40% |
| auto | ets_ann | 600 | 0.0097 | [-0.0297, 0.0516] | 49% |
| auto | ets_seasonal | 240 | -0.0775 | [-0.1565, 0.0012] | 54% |
| gbm_eval_only | auto | 600 | 0.0291 | [-0.0226, 0.0778] | 44% |
| gbm_eval_only | naive | 600 | -0.0678 | [-0.1234, -0.0154] | 55% |

## Mean MASE by archetype

| archetype | naive | moving_average_3 | median_12 | auto | gbm_eval_only |
|---|---:|---:|---:|---:|---:|
| stationary | 1.0724 | 0.8643 | 0.8056 | 0.7865 | 0.8594 |
| trend | 0.9869 | 0.8832 | 0.9894 | 0.8714 | 0.8946 |
| seasonal | 1.2967 | 1.4745 | 1.2362 | 1.0314 | 1.2332 |
| level_shift | 1.1233 | 1.0679 | 1.5407 | 1.2535 | 1.1676 |
| random_walk | 1.4093 | 1.5126 | 2.4292 | 1.6067 | 1.5134 |
| spiky | 1.3329 | 1.3506 | 0.9485 | 1.0904 | 1.1465 |

## Mean MASE by training length

| train months | naive | median_12 | auto | gbm_eval_only |
|---:|---:|---:|---:|---:|
| 12 | 1.3412 | 1.5899 | 1.3074 | 1.3382 |
| 18 | 1.2688 | 1.5644 | 1.2495 | 1.2771 |
| 24 | 1.0623 | 1.2916 | 1.0213 | 1.0367 |
| 36 | 1.1402 | 1.1407 | 0.9283 | 1.0509 |
| 48 | 1.2055 | 1.0381 | 1.0268 | 0.976 |

## Interval coverage (nominal 80%)

| step | intervals | observed coverage |
|---:|---:|---:|
| 1 | 600 | 83.0% |
| 2 | 600 | 81.8% |
| 3 | 600 | 79.5% |

| train months | intervals | observed coverage |
|---:|---:|---:|
| 12 | 360 | 84.4% |
| 18 | 360 | 84.2% |
| 24 | 360 | 79.7% |
| 36 | 360 | 81.4% |
| 48 | 360 | 77.5% |

## Methods the pipeline selected

median_12: 209, moving_average_3: 99, naive: 96, ets_damped_trend: 48, seasonal_naive: 45, moving_average_6: 43, ets_ann: 26, ets_seasonal: 18, drift: 16

## Mean pipeline latency (ms, this machine, one series)

12 months: 1, 18 months: 83, 24 months: 127, 36 months: 231, 48 months: 411
