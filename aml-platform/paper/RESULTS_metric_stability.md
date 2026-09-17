# Results: metric stability under implementation nondeterminism

> ⛔ **READ THIS FIRST — every pooled budget metric below averages two
> regimes.** AMLworld's generator winds down: HI-Medium goes from 3,021,866
> transactions a day at 0.0008 laundering to 2,020 at 0.5936 overnight, and
> HI-Small does the same at 2022-09-11. A uniformly random ranker therefore
> scores `precision@50` = 0.45392-0.49147 on the HI-Medium ring-aware test
> split, so a pooled level near that is near chance. On three of the nineteen
> days the budget exceeds the population entirely and no ranking is being
> tested.
>
> Read pooled levels here as descriptions of a window, never as model
> comparisons. The decomposition and the null are in
> [`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1,
> `results_archive/derived/window_decomposition.json` and
> `results_archive/derived/budget_null.json`.

**Run:** `data/gold/eval_Medium/seed{0..7}/` · 2026-08-24
**Setup:** HI-Medium, cut `2022-09-10`, 19,487,126 train / 12,402,530 test rows, 10,935 test positives. GBDT, 300 iterations, full sample — the production configuration. 8 seeds. Nothing else varies: same data, same split, same features, same hyperparameters.

---

## 1. The result

| metric | mean | min | max | spread | relative |
|---|---|---|---|---|---|
| ROC-AUC | 0.9826 | 0.9822 | 0.9828 | 0.0006 | **0.1%** <!-- derived: 0.9828-0.9822 --> |
| average precision | 0.2906 | 0.2547 | 0.3039 | 0.0492 | **16.9%** |
| ring_recall@200 | 0.6815 | 0.6030 | 0.7089 | 0.1059 | **15.5%** |
| recall@50 | 0.0393 | 0.0282 | 0.0428 | 0.0146 | **37.2%** |
| **recall_efficiency@50** | **0.8306** | **0.5956** | **0.9044** | **0.3089** | **37.2%** |
| precision@50 | 0.8248 | 0.5914 | 0.8981 | 0.3067 | **37.2%** |
| alerts per true positive@50 | 1.2329 | 1.1134 | 1.6908 | 0.5774 | **46.8%** <!-- derived: 1.6908-1.1134 --> |

Per seed:

```text
seed        AP    recall@50   recall_eff@50   precision@50   ring_recall@200
0       0.2824      0.0378         0.7995         0.7940            0.6938
1       0.3006      0.0428         0.9044         0.8981            0.7089
2       0.3039      0.0426         0.9009         0.8947            0.6919
3       0.2965      0.0427         0.9021         0.8958            0.7070
4       0.2547      0.0282         0.5956         0.5914            0.6030
5       0.3015      0.0395         0.8357         0.8299            0.6900
6       0.2919      0.0402         0.8497         0.8438            0.6786
7       0.2935      0.0405         0.8566         0.8507            0.6786
```

## 2. Stability is inversely related to usefulness

This is the finding.

```text
ROC-AUC              0.1% spread   -- rock solid, and SATURATED / uninformative
average precision     17%          -- usable, needs a range
ring recall@200       16%          -- usable, needs a range
budget-constrained
top-k metrics         37-47%       -- the operationally meaningful ones,
                                      and the LEAST reproducible
```

The metrics an investigator actually cares about — *how many of my 50 daily alerts are real* — are the least reproducible on this benchmark. The one metric that is perfectly stable is the one this project already relegated to a footnote for being saturated.

**Consequence: a single-run `precision@50` on AMLworld is not a result.** The same code, data and configuration yields 59% or 90% depending on nothing but the seed.

## 3. Why the budget metrics move so much

A 50-alert/day budget over the 19-day test window offers at most **858** attainable positives (`sum_d min(P_d, 50)`, not `50 x 19 = 950`: the window is strongly non-stationary and the last three days hold fewer than 50 positive account-days each). The reported number depends entirely on the composition of a ~858-row slice at the extreme head of a 6,204,374-row ranking. Small perturbations in the fit reshuffle that head; they barely move an integral over the whole ranking like AP, and they do not move a saturated rank statistic like ROC-AUC at all.

### 3b. The perturbation has a name, and it is not the optimizer

This document and `docs/LIMITATIONS.md` both used to attribute the spread to  <!-- historical -->
"optimizer sensitivity", and `models/config.py` named `class_weight="balanced"`
as the likely cause. Neither is right.

In the shipped configuration `random_state` has exactly **one** live consumer.
`early_stopping: False` makes scikit-learn's validation split and
`_get_small_trainset` unreachable, and no `max_features` is set, which leaves
`_BinMapper`'s **200,000-row subsample** used to estimate bin edges. Tree
construction is deterministic once the bins are fixed. `class_weight="balanced"`
is a deterministic function of `y` and cannot vary anything between runs at all
— though by up-weighting each positive ~620x it plausibly *amplifies* how much
the bin edges matter.

So the eight seeds are **eight quantile-estimation draws**, each from ~220
positives at 0.11% prevalence. Two observations pin it: below 200,000 rows the
bin mapper uses every row and different seeds give **byte-identical**
predictions; above it they diverge. `test_the_seed_varies_only_the_bin_edges`
asserts both.

### 3c. It is not a scikit-learn artefact — a second library reproduces it

The obvious objection is that this is a bug report about one library's default.
It is not. The canonical HI-Large lineage (`large_sorted_lgbm_s{0,1,2}`) runs
**LightGBM** with `deterministic=True`, no bagging fraction and no feature
fraction, so its only stochastic element is the same 200,000-row
`subsample_for_bin`:

| metric | s0 | s1 | s2 | relative spread |
|---|---:|---:|---:|---:|
| `recall@50` | 0.03238 | 0.02374 | 0.02973 | **30.2%** <!-- derived: (0.03238-0.02374)/((0.03238+0.02374+0.02973)/3) --> |
| `average_precision__txn` | 0.09229 | 0.07052 | 0.08257 | 26.6% |

⚠️ **This table used to list `precision@50` and `recall_efficiency@50` at <!-- historical -->
"30.2%" as well, as if they were three pieces of evidence. They are one.** <!-- derived: (0.03238-0.02374)/((0.03238+0.02374+0.02973)/3) -->
Within a run the alert count and the ceiling are fixed, so
`precision@50 = recall@50 × 14.9862` and
`recall_efficiency@50 = recall@50 × 19.3471` — the ratios are constant to four
decimals across all three seeds. Reporting all three inflated an n=3
measurement into an apparent triple confirmation. One quantity, measured once,
three seeds, one library, one rung.

⚠️ **And the replication is not thread-controlled** — so thread count is
excluded from the lower-bound argument above rather than counted in it, which
an earlier version of this page got both ways within six lines.
`models/config.py` sets
`deterministic=True` but also `n_jobs=-1`, and LightGBM's determinism is
conditional on a fixed `num_threads`. So thread count is a second uncontrolled
nuisance factor here, and this spread is **not** a clean attribution to
bin-subsample sensitivity alone. It is consistent with the sklearn mechanism
and does not isolate it.

Two independent implementations, a different dataset rung, 179.7M rows against
19.5M — the same mechanism and the same order of magnitude. The finding is
therefore stronger than "budget metrics are noisy": **at 0.11% prevalence,
histogram bin-edge estimation alone swings the operationally meaningful metric
by about a third.**

And because these seeds vary *only* the bin subsample — never row order or
platform, both of which are separately known to move results here — the
measured 30–37% is a **lower bound** on the nondeterminism of the
procedure as shipped.

**Related, measured separately:** with training row order held fixed, repeated fits are bit-identical. The pipeline is reproducible. The variance is sensitivity to nuisance factors — the bin subsample, and training row order — not irreproducibility.

## 4. Seed 4

Seed 4 is a genuine tail, not a crash: AP 0.2547 (vs 0.28–0.30) and ROC-AUC 0.9822, so the model ranks competently overall and merely orders the top 950 worse. It is **reported, not excluded.** Dropping it would move `recall_efficiency@50` from a mean of 0.831 to 0.865 and shrink the range from 31pp to 10pp, which is precisely the sort of quiet improvement this project exists to make impossible.

🔬 **Open question:** is the distribution bimodal (7 fits near 0.85, one near 0.60) or is 8 seeds simply too few to see the shape? **Test:** 30+ seeds on HI-Small, where fits are cheap.

## 5. What this corrects

| claim | status |
|---|---|
| "83% of attainable recall at a 50/day budget" (documented headline) | **a point estimate for a quantity spanning 0.596–0.904.** The mean happens to be 0.831, so 83% was not a lucky pick — but it was reported with unearned precision |
| "80–90%", written into the docs on 2026-08-23 from three runs | **too narrow.** Three runs happened to miss the lower tail |
| any single-run `precision@50` / `recall@50` / alerts-per-TP figure | **not interpretable alone** |
| AP ≈ 0.30, ~15× the logistic floor | **holds**, as 0.291 mean [0.255, 0.304], ~14.5× <!-- derived: 14.5 = the ratio of this row's AP mean to the logistic floor quoted in the claim, both rounded --> |

## 5b. How many seeds to buy — the ensemble-size curve

The reported model is an ensemble, so at 182M rows we pay for one feature build
plus N training runs. N was chosen from the curve, not from feel.

| n_seeds | AP (mean over 12 orderings) | AP range | Δ AP | eff@50 | eff@50 range | Δ eff |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.2942 | 0.2547–0.3039 |  | 0.8487 | 0.5956–0.9044 | |
| 2 | 0.3097 | 0.3045–0.3158 | +0.0155 | 0.9073 | 0.8765–0.9137 | +0.0587 <!-- derived: 0.0587 = the change from the previous row of this table, which a per-line marker cannot see --> |
| 3 | 0.3116 | 0.3087–0.3149 | +0.0019 | 0.9141 | 0.9044–0.9207 | +0.0068 |
| 4 | 0.3133 | 0.3106–0.3156 | +0.0018 | 0.9131 | 0.9033–0.9266 | -0.0011 <!-- derived: 0.0018 = the change from the previous row of this table, which a per-line marker cannot see --> |
| 5 | 0.3137 | 0.3113–0.3173 | +0.0003 | 0.9118 | 0.9033–0.9207 | -0.0013 |
| 6 | 0.3144 | 0.3129–0.3174 | +0.0007 | 0.9145 | 0.9079–0.9207 | +0.0027 <!-- derived: 0.0007 = the change from the previous row of this table, which a per-line marker cannot see --> |
| 7 | 0.3146 | 0.3134–0.3163 | +0.0003 | 0.9143 | 0.9114–0.9196 | -0.0002 |
| 8 | 0.3149 | 0.3149–0.3149 | +0.0003 | 0.9126 | 0.9126–0.9126 | -0.0018 <!-- derived: 0.0018 = the change from the previous row of this table, which a per-line marker cannot see --> |

Averaged over **12 random seed orderings**, with the observed min–max across
those orderings beside each mean
(`results_archive/gold/typology_Medium/stability.json`).

**The plateau rule, stated numerically instead of by eye:** the curve has
plateaued at the first `n` where every subsequent step in AP is smaller than
the spread across orderings at that `n`. Here the spread at `n=3` is **0.0062**
and every step from 3 onward is **≤ 0.0019** — so the plateau is at **3**, and
the steps beyond it are smaller than the noise introduced by which seeds you
happen to average first.

⚠️ **This table replaces one that should not have been used for a decision.**
The old version printed a single arbitrary seed ordering, and the paragraph
under it said so: its `n=1` row was seed 0, the worst of the eight fits
(eff@50 0.7995 against a per-seed mean of 0.8306), which inflated the 1→2 step.
The corrected artifact — 12 orderings with min/max — already existed and the
displayed decision table had never been regenerated from it. Note what the
correction does to the reading: at `n=1` the AP range across orderings is
**0.2547–0.3039**, wider than the entire 1→8 gain. <!-- historical -->

**Decision: the plateau is at 3, and the HI-Large run used 3.**

An earlier version of this line said "N = 4 for the 182M-row run" — the
plateau plus one, as margin against the curve's own imprecision. The released
HI-Large result uses **three** seeds, under the cost exception named in the
reporting rule below: each fit is 26 minutes and 30 GB of 31 on a 4-vCPU quota
a trial subscription cannot raise. So the plan said 4, the run did 3, and the
documents recorded both without reconciling them. Three is the plateau this
table identifies; the fourth was never bought, and the three-seed range is
published rather than hidden. <!-- historical -->

## 6. Reporting rule adopted, and scoped

**Stochastic HI-Medium and HI-Small results**, where eight fits cost minutes:
every budget-constrained metric is reported as **mean over ≥8 seeds with the
observed range**, never as a point. AP likewise. ROC-AUC stays in a footnote.

**Named exceptions, each with its reason stated where the number appears:**

| case | seeds | why not eight |
|---|---:|---|
| HI-Large | **3** | 26 minutes and 30 GB of 31 per fit, on a 4-vCPU quota that a trial subscription cannot raise. Eight fits is 3.5 hours of compute for a range this project already knows is wide; the three-seed range is published instead of hidden <!-- derived: 3.5 = the HI-Large lineage's wall-clock estimate in RUNBOOK_cloud.md, not a measured artifact field --> |
| the logistic baseline | **1** | a convex fit with a fixed solver and no sampling — it has no seed to vary. Reporting a range over a deterministic estimator would be theatre |
| the cloud HI-Medium reproduction | **1** | it exists to show that the pipeline produces the same numbers on another architecture, not to estimate a distribution |

⚠️ **This section used to state the rule with no exceptions at all, one screen
after the sentence "a single-run `precision@50` on AMLworld is not a result" —
and the README headline then compared a single logistic fit against a single
GBDT fit.** The rule as written forbade the project's own headline and its most
expensive result. A categorical rule that the author violates in the next
document is not a standard; it is a sentence. The headline now quotes the
eight-seed mean and range, and the exceptions are named here rather than taken
silently. <!-- historical -->

## 7. Limitations

- One rung (HI-Medium), one cut, one model family, 8 seeds.
- Seeds vary `random_state`; training row order is a second nuisance factor measured separately (15.5% on AP, HI-Small). Their interaction is not characterised.
- The logistic baseline is order- and seed-invariant on ranking metrics, so this variance is specific to the tree ensemble.
