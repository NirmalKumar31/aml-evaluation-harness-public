# Limitations

Everything here came out of a council audit on 2026-09-10 and a rebuttal round
against it. It is kept as one document so the caveats cannot be read separately
from the results they qualify.

---

## 1. ⛔ RETRACTED: the pooled budget metrics, and the linear-baseline reading <!-- historical -->

> **A pooled budget level on this window is barely above chance.** On the
> HI-Medium **ring-aware test split** a uniformly random ranker scores
> `precision@50` between **0.45392 and 0.49147** (hypergeometric sd 0.009078
> at the low bound, 0.008194 at the high one).
> The published logistic figure of 0.57060 therefore beats chance by
> **1.16×–1.26×**, and the GBDT's 0.88079 by **1.79×–1.94×**. <!-- derived: 0.57060/0.49147; 0.57060/0.45392; 0.88079/0.49147; 0.88079/0.45392 -->
>
> Restricted to the seven volume days, where the null is
> **0.00243–0.00244**, the same comparison is **17.6×** and **310.3×**.  <!-- derived: 0.04286/0.00244; 0.75714/0.00244 -->
> That is the result. The pooled number never was one.
>
> Measured by `scripts/budget_null.py`,
> `results_archive/derived/budget_null.json`.

### ⛔ And the first version of that null was computed on the wrong population

The script initially read every post-cut transaction from the raw CSV and
applied only the date cut. The models are evaluated on the **ring-aware** split,
which drops **736 of 1,265** test rings to keep ring participants out of both
sides. Against `results_archive/gold/splits_Medium/manifest.json`:

| quantity | raw date-cut | evaluated split |
|---|---:|---:|
| positive account-days | 30,867 | **18,130** |
| total account-days | 6,208,448 | **6,204,374** |
| alert slots at k=50 | 876 | **864** |
| ceiling count at k=50 | 876 | **858** |

A 70% inflation of the positive class inflates a prevalence-weighted null, so
that artifact reported a null well above the published logistic figure, and
this section concluded that the headline sat below chance. **It is above
chance.** That null, the two lifts derived from it and the below-chance claim
are all retracted; the withdrawn values are recorded in
`results_archive/RETRACTED.json` and are deliberately **not** restated here,
because the artifact they came from has been regenerated and they exist
nowhere else — a number with no artifact behind it does not belong in prose. The regression test guarding the null asserted only that it
existed and was positive — it proved presence, not population identity, and now
asserts the per-day positives sum to the split manifest's own count.

### Why a random ranker does so well here

AMLworld's generator **winds down**: it emits background traffic and then
stops, leaving its remaining laundering patterns to play out against almost
nothing.

| day | transactions | laundering | prevalence |
|---|---:|---:|---:|
| 2022-09-16 | 3,021,866 | 2,416 | **0.0008** |
| 2022-09-17 | 2,020 | 1,199 | **0.5936** |
| 2022-09-28 | 7 | 3 | 0.4286 |

Account-day prevalence across the evaluated window runs **0.001926 to 1.0**, <!-- derived: 0.001926 = the minimum daily account-day prevalence in the evaluated window, read off the per-day table in budget_null.json rather than stored as a field -->
and the tail null is **0.76135–0.82447** against a head null of 0.00243. A
random ranker's expected `precision@k` is a slot-weighted mean of daily
prevalence, so a window holding both regimes hands it almost half the alerts.

### On three days the estimand does not exist

`nonbinding_day_list@50` = **2022-09-26, 2022-09-27, 2022-09-28**. Those days
hold fewer account-days than the budget, so the top-50 *is* the whole day and
`precision@50` equals the day's prevalence for **every** ranker, including a
constant. A budget metric presupposes a binding budget.

### A non-binding day biases a LIFT toward 1 and a SPREAD upward

The same defect, in opposite directions, and this is the most transferable
thing this project has measured. A ring or account-day on a non-binding day is
caught by *every* ranker, so it carries no information about any model. What
that does to a statistic depends entirely on the statistic's shape:

- **A lift** — observed ÷ null — gets a 1 added to both sides. It is dragged
  **toward 1**, so a lift below 1 is *understated*. On HI-Large 57 of 668
  rings touch a non-binding day at k=200, with observed recall exactly 1.0000
  and a permutation null of exactly 1.0; excluding them moves the published
  `ring_recall_lift@200` further below 1, not closer to it. The sign reversal
  this project calls its central finding is therefore **conservative**.
- **A spread** — max ÷ min across groups — is dragged **upward**, because the
  maximum is whichever group is most saturated. On HI-Medium all 14 rings that
  end on a non-binding day belong to **one** typology, GATHER-SCATTER, which
  is the numerator of the 3.05× spread that has now been withdrawn.

So the same days that made one finding look worse than it is made another one
exist at all. Any capacity-constrained metric on a non-stationary window needs
this checked in the direction its own shape implies — reporting a level, a
lift and a spread from one window means three different biases at once.

### The stage cache's change detection is weaker inside the release image

`io.fingerprint` identifies a directory by (relative path, size, mtime_ns) and
says plainly that it is a proxy. Measured on amd64 inside the shipped
container: **two immediate writes to the same path receive the identical
`st_mtime_ns`** — a delta of 0 ns on overlayfs, against APFS on the
development machine where they differ. So a rewrite that lands in the same
tick and produces the same byte count is invisible to the cache *there*, and
the stage would be skipped against changed data.

What that does and does not mean: the pipeline never relies on the cache for
correctness of a published number — the manifest's output inventory records
what was actually written, and every derived artifact is checked against its
generator hash. This is a performance shortcut with a known blind spot, it is
platform-dependent, and it is **deferred rather than fixed**: closing it means
reading content, which is the cost the proxy exists to avoid.

It was found by running the suite inside the image on the cloud VM rather than
on the laptop, which is the only way it could have been found.

### And the ceiling is two quantities, not one

`sum_d min(P_d, k)` is **budget-limited** where `P_d > k` and
**positive-limited** where `P_d < k`. At k=50 that is **800 + 58 = 858** on the
evaluated split. So `recall_efficiency@k` is a ratio whose denominator changes
meaning mid-window, and the single figure 858 sums two different things.

### What is retracted

- **"A linear baseline is already strong here"** — this file's self-declared <!-- historical -->
  biggest finding. 97.0% of the logistic model's true positives come from days
  holding 0.056% of the transactions, and the pooled level it rested on beats
  chance by 15%.
- **Every pooled budget level** as a model comparison. They remain correctly
  computed pooled values; they are not comparisons.
- **"The budget-binds framing survives and arguably strengthens"**, which an <!-- historical -->
  earlier version asserted. It is false on the three non-binding days.

### And an unacknowledged train/test shift, which is worse than the pooling

The HI-Medium cut is 2022-09-10. The nine days before it hold exactly
**19,487,126** transactions — the published training row count — and **not one
is thin**. The model is fit on 100% volume-regime data and scored on a window
whose thin days supply **65.2%** of its top-50 true positives. That is
covariate shift between train and test, not merely pooling within test.

### What must be published instead

**Lift over the random-ranker null, on the volume segment, with the
non-binding days excluded**, and bracketed rather than pointed: the split's
per-day totals are bounded here, not materialised, because
`data/gold/splits_Medium` is not in this checkout. On that basis the finding is
stronger and survives — the linear baseline is **17.6×** chance and the boosted  <!-- derived: 0.04286/0.00244 -->
model **310×**. Levels must not be published for this window at all.

The verdict differs **by metric family**. Seven volume days × 50 = 350 alert
slots is a sound denominator for *precision*. It is not for *recall*: the head
recall ceiling is 350/14,748 = **2.37%**,
so `recall@k`, `recall_efficiency@k` and `ring_recall@k` are near-zero and
seed-chaotic on the volume segment and cannot be rescued by restriction.

---

## 1b. The original section, retained as the record

> ⚠️ **This section was headed "The benchmark is near-saturated" and that was an <!-- historical -->
> overclaim.** "Saturated" asserts closeness to a maximum, and no ceiling on
> achievable `precision@50` was ever established — only that one linear model
> reaches 0.5706 (pooled, and 1.16x-1.26x a random ranker) and one boosted model reaches more. A strong baseline is
> evidence that a linear model does well *on this representation* — not that
> the benchmark is solved, and not that any particular share of the
> separability is linear. That share has no measured denominator here. The word is removed from every current document; the <!-- historical -->
> measured statement below is what survives it.

```text
logistic regression, 32 features, HI-Medium:   precision@50 = 0.5706  <-- RETRACTED as a comparison; 1.16x-1.26x a random ranker
                                               ring_recall@200 = 0.4405
gradient boosting, same features, SEED 0:      precision@50 = 0.7940
                                               ring_recall@200 = 0.6938
  (the eight-seed mean is 0.82480, range 0.59144-0.89815; this single fit is
   the like-for-like comparator, and the README headline quotes the mean)
```

A **linear model** puts 57% genuine laundering in the top 50 daily alerts, at
`ring_recall@200 = 0.4405`.

⚠️ Earlier versions of this section compared that to a 1–5% alert-to-SAR
conversion rate in production. That comparison was **uncited and not
like-for-like** — filed-SAR conversion is an outcome after human review, while
this is precision against synthetic ground truth — and has been removed. What
the baseline supports on its own is narrower and still worth stating: on this
benchmark, this feature set and this operating point, a linear model is already
strong.

⚠️ Both this paragraph and the one below said **"most of the separability is <!-- historical -->
linear"** — an undefined fraction with no measured denominator, which §5b of
this same file then contradicted. One baseline and one comparator cannot
apportion separability. (Not "the benchmark is linear" —
see §5b on the hashed categorical encoding, which a linear model can exploit
as an arbitrary ordinal. It **has** been ablated on HI-Medium — the headline
`precision@50` does not depend on the encoding — but collision counts are
still not measured.) Part of it is visible directly — laundering rate
by payment format, measured over all 31,898,238 HI-Medium rows:

```text
ACH           3,868,410 rows   30,746 pos   0.7948%    12.1% of rows, 87.3% of positives
Bitcoin         689,038           244       0.0354%
Cash          3,217,531           666       0.0207%
Cheque       12,280,058         2,220       0.0181%
Credit Card   8,777,816         1,354       0.0154%
Wire          1,119,774             0       0.0000%    9.6% of rows can be
Reinvestment  1,945,611             0       0.0000%    excluded with CERTAINTY
```

Real layering runs through wires. Here wires are provably clean.

**Honest scope:** format is a free 7.2× prior, not the whole story — ranking all
ACH first yields 0.79% precision, so it cannot carry a 90% headline. The
indictment is the logistic baseline, not the format table.

**Consequence:** every detection number in this repository is a claim about
IBM's generator. The evaluation-methodology findings are unaffected.

---

## 2. `ring_recall` is not `recall`, and the gap is large

```text
same predictions, HI-Medium seed 0:
  recall@200       0.1248     account-day
  ring_recall@200  0.6938     ring
  inflation          5.6x
```

A ring counts as caught if **any** of its ~17 account-days reaches the top k on
its day, so it gets ~17 independent draws. Two further inflation channels:

- an account-day's score is the **max over all that account's transactions that
  day**, including entirely legitimate ones — so a ring can be credited because
  the model ranked an unrelated legitimate transaction of a member account;
- a ring's hit probability is monotone in (accounts × active days), i.e. in its
  size and duration, independent of skill.

`evaluate()` emits `ring_recall_null@k` and `ring_recall_lift@k` at every
budget, including the saturated ends, beside every ring number.

### ⛔ The null was wrong, and so was the conclusion drawn from it

The published null was the **size-matched independence expectation**
`mean(1 - (1-r)^m_i)` over actual per-ring sizes, with `r = recall@k`. On
HI-Large that gave lift **1.43** and the sentence "the model spreads its hits
across distinct rings rather than piling them into a few."

**That sentence is retracted.** Against a within-day permutation null on the
canonical lineage (`large_sorted_lgbm_s{0,1,2}`) the lift is **0.9497**, the
upper-tail p-value for *more* rings than chance is **1.000** on all three
seeds, the lower-tail p-value is **< 0.001** — `1/(b+1)` with b=1,000 draws,
so it is the smallest value this many permutations can express rather than a
measured magnitude; `ring_recall_null_p_resolution@k` now publishes that floor
beside it — and the observed value sits *below*
the null's 95% interval.
The model covers slightly **fewer** distinct rings than a ring-blind assignment
of the same scores.

| null | HI-Large value | lift |
|---|---:|---:|
| pooled recall, independent draws (retracted) | 0.61165 | 1.429 <!-- historical --> |
| ring-eligible rate, independent draws | 0.98886 | 0.884 <!-- historical --> |
| **within-day permutation (shipped)** | **0.91492** | **0.9497** |

The first two rows are from `large_eval3_lgbm_s*`, the superseded unsorted
lineage, where that comparison was run. The shipped row is the three-seed mean
of the canonical `large_sorted_lgbm_s{0,1,2}`.

Two errors, in opposite directions:

1. **Wrong reference population — the large one.** `r` was pooled over *all*
   positive account-days, but **87% of HI-Large's positives carry no ring
   label**. The rate at which ring-member account-days are actually alerted is
   `ring_eligible_recall@200 = 0.61989`, seven times the pooled `recall@200`.
2. **Wrong independence.** A ring's account-days are not independent draws: one
   transaction yields a sender and a receiver account-day with the same max
   score, and same-day account-days compete for a fixed budget. This document
   named that mechanism and correctly reasoned it makes an independence null
   too generous — while applying the reasoning to a null whose base rate was
   already wrong by 7×, and concluding 1.43 was a *lower* bound.

**The lesson is not about arithmetic.** 1.43 was computed by code, from
artifacts, and published under a checker that verified it traced to a manifest.
Provenance discipline cannot detect a wrong estimand. What caught it was a
**negative control**: a null must report "no effect" on scores drawn
independently of ring membership. The first attempted replacement failed that
control (lift 0.497 where the truth is 1.0) and was discarded.

⚠️ Earlier corrections to this figure, kept on the record:

| rung | recall@200 | mean m | old null | observed | old lift |
|---|---:|---:|---:|---:|---:|
| HI-Large | 0.09177 | median 10.0 | 0.61148 | 0.87375 | 1.43 <!-- historical --> |
| HI-Medium (seed 0) | 0.12482 | 17.1 | 0.89628 | 0.69376 | 0.77 <!-- derived: 0.12482 = a withdrawn HI-Medium recall@200 from the corrected-away closed-form null, quoted as a record; 0.89628 = the withdrawn analytic null beside it --> |

1. The HI-Large lift was published as **1.08** using `m=17` — HI-Medium's mean
   ring size — then hand-corrected to **1.28** with a scalar `m=12`, then
   measured at **1.43** from per-ring sizes. A quantity defined over a
   distribution of ring sizes is not recoverable from any single summary of it.
2. It claimed the null "reverses the ordering". It does not — both metrics rank
   HI-Large above HI-Medium. What flips is the *sign of interpretation*: a high
   ratio reads as bad, a high lift reads as good.

**HI-Medium HAS now been re-evaluated under the new null, and it agrees.**
Fresh end-to-end run on the cloud VM from a re-downloaded dataset whose sha256
matched the pin:

| rung / model | ring_recall@200 | null | lift | p |
|---|---:|---:|---:|---:|
| HI-Large, lgbm (3 seeds, canonical) | 0.86876 | 0.91492 | **0.9497** | 1.000 |
| HI-Medium, gbdt (canonical, sorted) | 0.69376 | 0.76453 | **0.907** | 1.000 |

**Two independent generator runs, three model configurations, every lift below
1 and no p-value near significance.** The retraction does not rest on one rung.
Its old closed-form lift of 0.77 on HI-Medium should not be quoted.

**Read 12%, not 70%, as "laundering caught".**

---

## 3. The split protects rings, not positives

### What "ring-participant-disjoint" does and does not mean

It was called an **entity-disjoint** split until the external audit pointed out
that the name claims more than the code delivers. Precisely, the split
guarantees:

- no account that **participates in a ring** appears on both sides;
- no ring appears on both sides;
- no transaction crosses the cut in the wrong direction;
- no tail of a training ring survives into test.

It does **not** guarantee:

- that a test account has no pre-cut history in training. An account's clean
  earlier activity is in the training set whenever it has any, and only its
  ring-participating identity is disjoint;
- anything at all about positives carrying no ring label — see below.

"Entity-disjoint" reads as the first of those being false. It is not, and the
name is now `ring-participant-disjoint` everywhere current.

~**38%** of positive account-days on HI-Medium, and **87%** on HI-Large, carry
no ring label. They are neither dropped for account overlap nor counted in
`ring_recall`'s denominator — they bypass the discipline entirely.

`pct_positive_acct_days_without_ring` is now reported. ⚠️ The first version of
this metric computed the fraction over **transactions**, which made it exactly
`100 - typology_coverage_pct` — algebraically the negation of a metric that
already existed, adding no information, while its own comment claimed to
describe account-days. Account-days is the correct denominator, because that is
what `ring_recall` is denominated in.

And the dropping is **not at random**: a test ring dies *because* it shares an
account with a train ring, so the rings removed are the connected, hub-and-mule
ones. What survives is the isolated, one-off end of the distribution.

```text
HI-Medium   58.18% of test rings dropped
HI-Large    87.45% dropped   -> the estimand is "the ~13% least-connected rings" <!-- derived: 87.45 = gold/large_splits/manifest.json `dropped_pct`. That manifest records code_git_sha "unknown" -- the HI-Large split predates the provenance gate -- and the figure cannot be re-derived without the 179.7M-row dataset. It is published on an unprovenanced artifact and that is a disclosed limitation, not an oversight -->
```

#### And the split's own manifest records contamination it never published

`splits_*/manifest.json` carries
`unlabeled_positive_acct_days_touching_train_rings` — positive account-days
whose accounts sit in a *training* ring, admitted into the test half anyway:

```text
HI-Small     11 of  4,308 test positives   0.26%
HI-Medium   135 of 18,130                  0.74%
HI-Large  4,985 of 61,698                  8.08%   <- the rung with the headline
```

It scales by a factor of eleven between rungs and appears in **no document**
before this one. It sits in the same manifest whose `assertions_passed` lists
`accounts_disjoint`, because the disjointness rule is about *ring* accounts and
this is the unlabelled residue the rule does not cover — so both statements are
true and, read together, misleading. On HI-Large it means roughly one test
positive in twelve belongs to an account the model trained on.

This does not invalidate `ring_recall@200`, which counts rings rather than
account-days, but it does bound how clean the account-day metrics on that rung
can be claimed to be, and it should have been published with the split.

`paper/PREREGISTRATION_split_inflation.md` was the experiment that would settle
whether this discipline is worth its cost. **It has now been run** — see
[`paper/RESULTS_split_inflation.md`](../paper/RESULTS_split_inflation.md). The
short version, on HI-Small:

- A naive temporal split reports average precision **40% higher**,
  `precision@50` 19% higher — and `recall@50` **4% lower**. Which protocol
  looks better depends on which metric you quote.
- **About half that AP gap is associated with composition and about half with
  the readmitted positives' score distribution.** The filter keys on `ring_id`,
  non-null only on laundering rows, so it removes *only positives* — all 966.
  Rescoring those 966 from the retained positives' distribution (a
  counterfactual, not a ratio) splits the gap **0.467 / 0.533** across five
  seeds at 400 draws. The spread [0.439, 0.500] is across seeds, not an
  inferential interval.
- **Neither half is a causal effect**, and the second is not identified as
  leakage. The resample conditions on nothing, so it assumes the excluded and
  retained positives are exchangeable unconditionally — which is false by
  construction, since exclusion tracks ring account reuse. Read the split as a
  sensitivity analysis: how much of the gap survives when the added positives
  are made score-typical.
- ⚠️ This bullet previously said **97% prevalence / 3% detectability**. That was <!-- historical -->
  wrong twice: the ratio arithmetic did not mean what it was reported as
  meaning (allocating the excess gives 89.9%, not 97%), and the division assumed
  AP scales linearly with prevalence, which holds for a random ranker and not
  for a fitted one.
- So the discipline removes rows that score higher, and that is associated with
  roughly half the AP gap — considerably more than the retracted figure
  implied, and still not a demonstration of leakage.

So the split's justification is no longer an assumption, and it is also weaker
than this document used to imply. What it buys is a test set whose prevalence
is not inflated by readmitting known-positive rows; what it costs is 58–87% of
test rings. Whether that trade is worth it is a judgement, but it is now a
judgement made against measurements.

**Not run:** the preregistered HI-Medium confirmation. Everything above is
HI-Small, one cut, one generator run.

*(One thing the audit raised and I rejected: there is no temporal embargo, so a
test row one minute past the cut carries history from the training period. That
is deliberate and correct — at inference you genuinely do know an account's
past. What must not cross is labels, and they do not.)*

---

## 3b. The alert unit is a proxy, and it is asserted rather than validated

Everything budget-scoped here counts **(account, calendar-day)** alerts, on the
stated ground that this is "what an investigator actually opens". That sentence
has no citation behind it, and it is doing a lot of work: it sets the
denominator of `recall@k`, the competitor pool that `precision@k` ranks within,
and the ceiling every efficiency number is divided by.

Real monitoring systems do not agree on the unit. Depending on the vendor and
the programme it may be a **customer** (several accounts merged), a **scenario
alert** (one rule firing, several accounts), a **case** (several alerts merged
by an analyst over days), or an **event**. Those are not rescalings of each
other — merging two accounts of one customer into one review halves the budget
consumed and changes which positives are reachable.

What can be varied here is varied: every metric is reported at **seven budgets**
(10 → 1000), and `recall_ceiling@k` makes the budget's effect explicit rather
than leaving it implicit in the score. What **cannot** be varied is the unit
itself — AMLworld has no customer identifier, so accounts cannot be grouped into
customers, and no case structure to merge alerts into.

So: treat `(account, day)` as **one point in a space this benchmark cannot
explore**, and do not read a budget number as a forecast of review load under a
different unit. The *comparative* findings — that the budget binds and that
`ring_recall` needs a null — do not depend on the unit, because every arm is
measured under the same one. (The linear-baseline comparison used to be listed
here too; §1 retracts it for an unrelated reason — it pools two regimes.)

---

## 3c. One transaction produces two alerts, and the budget counts both

This project treated sender/receiver coupling as **fatal** in one place and did
not check it in another. `ring_recall`'s permutation null exists because "a
sender and a receiver account-day created by the same transaction carry the
same score", and the first null, which ignored that, reported a strong ring
effect on data with none by construction (§2). The same coupling sits
underneath `precision@k`, `recall@k` and the ceiling.

### ⛔ Two attempts to measure it were wrong, in different ways

**Attempt 1 — a score-tie proxy.** Group alerted account-days by exact <!-- historical -->
`(day, score)`, call each group one transaction. Sender/receiver pairs do share
a score; so can unrelated transactions. The group count is therefore a *lower*
bound on distinct transactions and the ratio an *upper* bound on the
over-counting factor. Point-value claims built on it — "about 28 transactions", <!-- historical -->
`ceiling_unit_sensitivity`, an event-unit ceiling — are retracted. <!-- historical -->

**Attempt 2 — an endpoint join with no score filter.** The replacement joined <!-- historical -->
`ring_endpoints` to the alerted account-days on `(day, acct)`. That table holds
one row per *(ring transaction, endpoint)*, so the join attaches an account-day
to **every** ring transaction that touched the account that day, not to the one
that supplied its maximum. `ring_transactions.parquet` carries the
per-transaction score and the script never opened it.

Consequences, all of them published before being caught: the transaction count
was inflated by transactions that did not cause the alert; the per-group
`nunique(rt)` measured *"does this account-day touch several ring
transactions"*, which is a different quantity; and the resulting **14–48%**
"evidence that score groups merge transactions" measured no such thing.
Corrected, that figure is **0% at k=50 on all nine bundles** — and **not** 0%
at every budget: `medium_gbdt_s0` has one such group at k=200 and one at
k=1000. An earlier version of this section said "0% on all nine bundles"
without a budget qualifier, and the test guarding it asserted only k=50, so it
passed while the published claim was false at two budgets out of three. The
factor called *exact* was 1.51–1.89 and is actually 1.624–1.950. All of it is <!-- derived: 1 + 156/250; 1 + 956/1006 -->
retracted and registered.

### The definition now, stated so it can be disagreed with

A ring transaction is the **score source** of an alerted account-day iff its
own score equals that account-day's score. The account-day score *is* a max
over its own transactions, so the source carries a bit-identical float and
exact `==` is the right test rather than a tolerance. Four cases, all reported:

| case | treatment |
|---|---|
| supplies the maximum uniquely | counted |
| ties with another **ring** transaction | all tied sources counted; `ring_account_days_with_tied_max@k` publishes how often — 0 at every budget in every bundle |
| ties with a **non-ring** transaction of the same account | still counted, and this case is **not** covered by the field above. Measured separately from `other_max`: **0.00–0.10%** of attributed endpoints. Small, but an earlier version of this section said "the ambiguity is empty" while checking only the ring-vs-ring half |
| another transaction supplies the maximum | **not** counted; the alert is not attributable to it (153–382 endpoints per bundle **at k=50**; 606–1,761 at k=1000) |
| only one endpoint alerted | counted once; `alerting_ring_txns_with_both_endpoints@k` reports the pairs separately |

### Two published ratios are identities on purpose, and are named as such

`scripts/alert_unit_coupling.py` publishes two quantities that are exact
functions of counts beside them. Both are deliberate, and the gate
`test_no_published_ratio_is_an_identity_on_two_published_counts` requires them
to be named here or it fails:

| ratio | identity | why it is published anyway |
|---|---|---|
| `both_endpoint_share@k` | `alerting_ring_txns_with_both_endpoints@k / alerting_ring_txns@k` | it *is* the quantity. The earlier field `account_days_per_alerting_ring_txn` was 1 plus this, published as though it were an independent mean |
| `tie_account_days_per_group@k` | `alerted_account_days@k / tie_groups@k` | a bound on the over-counting factor, reported with both operands so a reader can see it is a bound |
| `total_gap` | `prevalence_effect / prevalence_share` and `score_distribution_contrast / detectability_share` | the split-inflation decomposition's own algebra: the shares are *defined* as effect ÷ gap, so the gap is recoverable from either pair. Publishing all of them is redundant, not independent evidence |
| `SUPERSEDED_ap_ratio_net_of_prevalence` | `ap_ratio / prevalence_ratio_naive_over_ring_aware` | ⛔ the **retracted** ratio-of-ratios behind the withdrawn "97% is prevalence" claim. <!-- historical --> Retained under a `SUPERSEDED_` prefix as the record of the arithmetic that was wrong; it must never be quoted |
| `precision_head@k`, `precision_tail@k`, `precision_pooled@k` | `true_positives_* / alerts_*` | the **definition** of precision, published beside its own numerator and denominator on purpose. An identity of this kind is transparency, not redundancy — but it is declared here because the gate requires every one to be, and a rule with exceptions nobody wrote down is how the last three rounds went |
| `share_after_cliff` | `n_after_cliff / n_rings` | per-typology wind-down exposure, published beside both operands so a reader can see the ring counts it rests on — and so they can be checked against the split's 529 rings, which the first version of this measurement failed |
| `after_cliff_share` | `n_after / n_rings`, pooled | the same identity at the window level. It is the `s` in the feasibility algebra below, so it has to be visible |
| `max_feasible_tail_rate` | `pooled_rate / after_cliff_share` | not a measurement at all — an **arithmetic bound**. It is published precisely because it is recoverable: it exists to show that the withdrawn assumed rates of 0.80/0.90/0.95 lie outside it, and a reader must be able to redo that division |
| `p_floor` | `1 / (draws + 1)` | the smallest p-value the simulation can express, published so a reader can see when a reported p is AT it rather than below it. `p_exposure_blind` currently is |

⚠️ **The gate that demands this table found two of these rows in artifacts
nobody had examined, and three more the moment the typology null was
rewritten.** Its first version asserted a blanket sentence and was
defeated by injecting new identities; it now names each offender and scans
every derived artifact.

### What that measures — and it is one proportion, not a mean

The published figure was `account_days_per_alerting_ring_txn`, and it is
**exactly `1 + both/n`** — an identity, not an independent measurement:

```text
(2 x both_endpoints + 1 x single_endpoint) / n_txns  ==  1 + both/n
```

verified to four decimals on every bundle at every budget. So the honest
quantity is the underlying proportion, **the share of alert-causing ring
transactions whose both endpoints alerted**, published with its denominator.
All nine bundles, k=50:

| bundle | both / n | share | factor (= 1 + share) | attributable share of alerted account-days |
|---|---:|---:|---:|---:|
| `large_sorted_lgbm_s0` | 956 / 1006 | **0.950** | 1.9503 | 47.7% <!-- derived: 1 + 956/1006; 47.7 = the attributable subset's share of alerted account-days on HI-Large, counted in alert_unit_coupling.json --> |
| `large_lgbm_s2` | 989 / 1052 | **0.940** | 1.9401 | — <!-- derived: 1 + 989/1052 --> |
| `medium_baseline_s0` | 207 / 267 | **0.775** | 1.7753 | — <!-- derived: 1 + 207/267 --> |
| `medium_gbdt_s0` | 324 / 432 | **0.750** | 1.7500 | 87.5% |
| `small_gbdt_s0` | 156 / 250 | **0.624** | 1.6240 | — <!-- derived: 1 + 156/250 --> |

⚠️ **That proportion swings 0.624 → 0.950, a 52% relative range — wider than <!-- historical -->
the seed spread this project reports as a headline finding — and it was
published as "about 1.6 to 1.95 review slots" as if it were a stable <!-- derived: 1 + 956/1006 -->
constant.** It moves because the *population* moves: the attributable subset is
47.7% of alerted account-days on HI-Large and 87.5% on HI-Medium, selected for <!-- derived: 47.7 = the attributable subset's share of alerted account-days on HI-Large, counted in alert_unit_coupling.json -->
being ring endpoints and therefore selected toward pairing. **The variation in
the population is the finding, not the value of the ratio.**

Stated on the population it was measured on — ring transactions that supplied
an alerted account-day's score at k=50 — and **not** the full alerted set.

That zero multi-transaction groups survive the score filter is mild evidence
*for* the tie proxy on this subset, not against it. It does not show that
unrelated non-ring transactions never tie; nothing here measures that.

### What is still out of reach

Ring transactions are the only ones whose identity **and** score these bundles
record. So the factor for the full alerted set — mostly non-ring account-days —
is not measurable from them, and neither is a transaction-level precision,
recall or ceiling.

`argmax_txn_id` alone does not close that, and an earlier version of this
section implied it would. It names one score source per account-day, chosen by <!-- historical -->
`idxmax`, which picks arbitrarily among ties; the account-day label is
`max(y)` over all its transactions rather than that transaction's own label;
and the bundle records per-day positive *account-day* counts, not per-day
positive *transaction* counts. A transaction-level metric needs a
transaction-level table: score, label, day, opaque index.
`make_replay_bundle.py` now emits one. Every bundle in the archive predates it.

**What is untouched either way.** Every arm is measured under the same unit, so
the *comparative* findings — that `ring_recall` needs
a null — do not depend on any of this. What it bears on is reading a budget
number as a forecast of review load. (The linear-baseline comparison is
retracted in §1 on separate grounds.)

The consistent next step, still not taken, is a null for `precision@k` and
`recall@k` of the kind that exists for `ring_recall`.

---

## 4. This is an FIU model, not a bank model

**40% of transactions are cross-bank.** Of the 10 history features computed per
side, a single institution can compute **one** — the pairwise counterparty
recency, from its own ledger. The other nine require seeing the counterparty's
activity at another bank.

So the stated design rationale — "a mule mostly receives, so aggregate both
sides" — is available only to a financial intelligence unit or a network
operator. **No single bank could build these features.** This does not invalidate
the harness claims; it invalidates the deployment story.

---

## 5. What a model validator (SR 11-7 / OCC 2011-12) would fail

| gap | why it matters |
|---|---|
| **No calibration** | `class_weight="balanced"` up-weights positives ~620×. Scores are not probabilities and cannot support tiering, expected-conversion estimates, or documented thresholds |
| **No reason codes** | you cannot draft a FinCEN SAR narrative from a tree ensemble |
| **No above/below-the-line testing** | the regulatory standard for tuning transaction-monitoring thresholds |
| **No feature-to-typology rationale** | conceptual soundness is assessed before performance |
| **No ongoing monitoring / override tracking / outcome feedback** | |
| **Seed instability** | precision@50 spans 0.591–0.898 across seeds. Ensembling hides it; it does not fix it |

Deeper: real AML labels are **detection** labels (alert → case → SAR), so a
supervised model learns to imitate the incumbent rules. This project never
confronts that, because the generator hands it ground truth no bank has.

---

## 5b. The categorical encoding is an artefact the linear claim rests on

`payment_format` and `receiving_currency` enter the feature vector as
`DuckDB hash(value) % 1000` — a number. Two things follow, and neither has been
ruled out:

- **Collisions are possible and unchecked.** Nothing verifies that two formats
  do not share a bucket.
- **The geometry is arbitrary.** A logistic regression treats bucket 17 as
  between 16 and 18. Those neighbourhoods carry no meaning, but they are not
  noise either: a linear model can fit a real pattern in hash order, and a
  histogram tree can split on it. So part of what the "linear baseline" is
  exploiting may be the *encoding* rather than the data.

This matters specifically because the baseline's strength is this project's
headline. **The supported claim is narrow: this particular 32-feature vector is
strongly separable by this particular linear model.** Whether the benchmark
itself is "largely linear" is not established, and cannot be until the same <!-- historical -->
comparison is run with fixed vocabularies, an explicit unknown category, and
one-hot or native categorical handling — plus an ablation with the categorical
features removed entirely.

### ⛔ It was measured, and the measurement does not support the claim <!-- historical -->

> **This subsection was headed "the headline claim survives".** It cannot: <!-- historical -->
> every arm below is a POOLED level on the two-regime window, and a random
> ranker scores nearly half the alerts there. Three arms agreeing to 1% on a quantity that is
> only 1.16x-1.26x chance is agreement about the window, not about the
> encoding. The
> encoding question is **open**, and closing it needs the arms re-measured on
> the volume segment against the null — which the ablation as committed cannot
> do, because it discards per-arm scores.

Three arms on HI-Medium, same split, same seed, logistic baseline
(`scripts/categorical_ablation.py`,
`results_archive/derived/categorical_ablation_medium.json`):

| arm | average_precision | **precision@50** | recall_efficiency@50 | ring_recall@200 |
|---|---:|---:|---:|---:|
| full (hashed) | 0.02023 | **0.57060** | 0.57459 | 0.44045 |
| no categorical | 0.01022 | 0.57639 | 0.58042 | 0.44991 |
| one-hot (train-only vocabulary + unseen) | 0.02136 | 0.57639 | 0.58042 | 0.45369 |

**What the pooled arms do and do not settle.**
pooled `precision@50` spans 0.5706 to 0.5764 — a 1% range on a quantity that is only 1.16x-1.26x chance — and the hashed arm is the
*lowest* of the three, so on this evidence the hash is not flattering the
linear baseline **pooled**. But a pooled level cannot answer the question that
matters, because it averages the volume days with the wind-down. The claim
"the headline does not depend on the encoding" was asserted from these three
pooled numbers for several rounds. **It is withdrawn, and the segmented
measurement contradicts it.**

#### On the volume days the encoding does matter, and not consistently

`precision@50` on the head segment, against a random ranker on that same
segment (`by_segment` in both ablation artifacts):

| arm | HI-Medium lift | HI-Small lift |
|---|---:|---:|
| categoricals dropped | 26.135 | 34.2174 |
| hashed into 1000 buckets | 33.5965 | 15.204 |
| one-hot, train-only vocabulary | 37.3338 | 19.0135 |

Two things follow, and only two. **The arms are not equivalent**: they span a
43% relative range on HI-Medium where the pooled figures agreed to 1%, so the
pooled agreement was agreement about the window, exactly as suspected. And
**the direction does not replicate**: dropping the categoricals is the *worst*
arm on HI-Medium and the *best* on HI-Small. One seed, one model family, two
rungs that disagree — so this establishes that the encoding affects the
volume-segment headline, and it does **not** establish which encoding to
prefer.

This is what the `--thin-from` path was for, and it could not produce it: the
path crashed on its first line for as long as it existed (`m is slice(None)`,
an identity comparison between two distinct slice objects) and no test ever
called the function. Fixed, tested against a hand-computed frame, and rerun on
the cloud VM.

⚠️ That is **evidence against** the hash-geometry concern; it does not close
it. This paragraph said the concern "is answered: it is not", four paragraphs
above the note explaining that the artifact has partial provenance and must
not be used to close the question — a cross-check pointed out that a document
cannot hold both. One run, one seed, one rung, collisions unmeasured, and no
package-tree hash to show which code produced it. Closing it means the rerun
named in the release checklist. <!-- historical -->

On **average precision** the categoricals matter a great deal — removing them
halves it (1.98×) — and one-hot beats the hash by 5%. So the hashed encoding
*understates* their contribution rather than inventing it.

The claim this supports is therefore the narrow one:
**at the operating point, a linear model on these 32 features reaches
pooled `precision@50 = 0.5706` (1.16x-1.26x a random ranker), and in this run that did not depend on how the two
categorical columns are encoded.**

⚠️ **Provenance is now complete; the encoding question is what remains
open.** `categorical_ablation_medium.json` was regenerated on the cloud VM
inside the release container and records a full 40-character commit, generator
hash, package-tree hash, environment-lock hash, repo-relative input identities
and parameters. `scope_clean` is null because a container has no git checkout.
One caveat that "full provenance" should not paper over: the transformed
feature inputs are identified by path and size, not by content hash — the RAW
dataset files are strongly pinned, but the derived feature table is not. The
older note said the generator blob and full commit SHA verify, and that is
where its provenance stops: it carries **no package-tree hash, no declared
inputs, no parameters, no environment identity and no clean-scope record** —
all of which every other derived artifact here now has. There is therefore no
evidence that the `aml` package imported during that run was the package at the
recorded commit.

The honest status is *supporting evidence, not release-grade*. Closing the
encoding confound properly means rerunning it from the pinned Medium inputs
under the current provenance rules — which is possible while the VM exists and
not afterwards. The claim above is scoped to "in this run" for that reason. <!-- historical -->

⚠️ Also still true: collisions are unchecked, and this is one rung, one seed,
one model family. Two of the seven payment formats (Wire, Reinvestment, 9.61% of
rows) carry **zero** positives, which is why the feature is informative at all.

---

## 6. Statistical caveats

- **Seeds are not replicates, and they are narrower than "optimizer
  sensitivity".** This line used to say seeds measure optimizer sensitivity.  <!-- historical -->
  They do not. In the shipped configuration `random_state` has exactly **one**
  live consumer: the 200,000-row subsample the histogram learner uses to
  estimate bin edges. `early_stopping: False` makes every other consumer in
  scikit-learn unreachable (the validation split, `_get_small_trainset`), and
  the config sets no `max_features`; LightGBM is the same, with
  `subsample_for_bin` defaulting to 200,000 and no bagging or feature fraction
  set. Tree construction is deterministic once the bins are fixed. So the 8
  seeds are **8 quantile-estimation draws**, and the A/B sign tests
  (p=0.0078, p=0.0156) use bin-edge resampling as their error term. <!-- derived: 2/2**8; 2/2**7 -->

  That still supports an exact test — the draws are i.i.d., the subsample
  indices depend only on row count, which is identical across arms, so the
  pairing is exact and exchangeability under H0 holds. The estimand is simply
  narrower than it reads: *robust to bin-edge resampling, on one split of one
  dataset*. The generalization estimand still has n=1.

- **The sign test is at its power floor, and that makes the multiplicity
  family determinative.** An exact two-sided sign test on 8 paired
  observations has a **minimum attainable p-value of 0.0078125**; on 7, after
  dropping a tie, it is 0.015625. <!-- derived: 2/2**7 -->
  The two reported p-values are not effect sizes, they are the floor — no
  effect, however large, can do better at this n.

  ⚠️ **This bullet used to prescribe "16 seeds", and that is the wrong fix.** <!-- historical -->
  More seeds buy a smaller floor on the *same* error term — bin-edge
  resampling — which is not a perturbation anyone wants to generalise over. A
  tighter p-value about histogram binning is not a stronger claim about
  detection. It also used to lay out a BH ladder across a declared family;
  that is deleted, because at this n the family size decides the answer before
  the data does.

  **What the design supports, and all of it:** 8 of 8 and 7 of 8 paired arms
  moved in the same direction, effects −5.1% and −6.4%, robust to bin-edge
  resampling on one split of one rung. A direction claim, which stands.

  **And the two floors in this project are not comparable.** The permutation
  null's is `1/(b+1)`, and `--permutations` is a command-line argument — so it
  is *purchasable*. At 100 draws the floor is 0.0099 and the flagship <!-- derived: 1/101 -->
  lower-tail p would fail the same family the sign test fails; at 1000 it
  clears. A multiplicity family whose members have buyable p-values is not a
  family, and treating the two floors as one pathology was an error.
- **The graph-feature A/B ran on HI-Small only**, never replicated on another
  rung, in a project whose finding #5 is that things do not replicate across
  rungs.
- **"Graph features don't help" is NOT established.** Every feature tested was a
  per-account time series. No subgraph, 2-hop, motif, component or flow-tracing
  feature was ever computed — and those are what would detect CYCLE, STACK and
  FAN-IN. The claim that survives is narrow: *counterparty-count features add
  nothing over volume features on this generator*, because they correlate
  0.977–1.000 with them.
- **Finding #5 has now been tested against a null, and this bullet was wrong
  twice.** It first read "the ordering does not replicate" on the strength of
  ρ=0.286, p=0.49 — a test against *zero* correlation, which has no power here.
  It was then corrected to "uninformative", with the assertion that a 3× max/min
  ratio "arises routinely under perfect homogeneity". Simulated from the actual
  per-structure ring counts (`scripts/typology_null.py`), neither holds:

  ```text
  spread, HI-Medium   observed 3.05x   null median 1.58x   p = 0.0008 — RETRACTED
  spread, HI-Small    observed 2.29x   null median 1.83x   p = 0.170
  ordering            observed rho 0.286 vs [0.347, 0.976] under PERFECT
                      replication -> p ~ 0.014 against replication
  ```

  And then wrong a THIRD time, and a FOURTH. The spread null above assumes one
  detection probability per ring, which the wind-down falsifies. The first
  cliff-aware replacement measured exposure on the wrong ring population and
  assumed after-cliff rates that cannot reproduce the observed pooled rate; the
  second measured them, but at budget 200 against a spread defined at budget 50.
  All are withdrawn and registered.

  What the repository's OWN null says, applied to the typology table for the
  first time — the within-day permutation that `ring_recall` has used since its
  own sign reversal:

  ```text
  spread, HI-Medium   observed 3.46875   null median 3.42745   p = 0.46633
                      the observed value is the 53.5th percentile of chance
  ```

  And no per-typology ordering survives either: six of eight
  `ring_coverage_concentration` intervals span 1, none is distinguishable
  after Holm, and P(the two typologies at the ends of the apparent
  "inversion" land that way under H0) is 0.485. An earlier correction read an
  ordering off those ratios without an interval and called it an inversion --
  the same mistake, one level down. 14 of 529
  rings end on a day where the budget exceeds the population — all 14
  GATHER-SCATTER — and this repository has documented that defect for
  `precision@k` since §1 without ever applying it to `ring_recall`.
  Over-correcting is still getting it wrong; so is correcting on the wrong
  population, and so is correcting at the wrong budget.
- **The placebo null was biased; the code is fixed and the numbers have been
  rerun under it.** Permuting leak columns destroys legitimate signal as well
  as the leak (under the corrected placebo the `reversed_window` arm sits at
  0.8834, well below 1.0), so the control is
  "no leak AND no information", not "no leak". Worse, the permutation was
  **global**, moving values across the train/test boundary and across the
  calendar, so the placebo arm carried a distribution shift on top of the
  misalignment being measured.

  `sweep_version 2.0.0` permutes within `(split side, event_date)` and fails on
  a partial leak join instead of filling NaN. **It has been rerun, and the
  verdicts changed.**

  ```text
  noise floor   1.1.0 global        21.97%     <!-- historical -->
                2.0.0 stratified    46.10%
  ```

  The corrected placebo's noise floor is **twice as wide**, so the published
  22% understated it. Two of three channel verdicts flipped — `reversed_window`
  from not-detected to detected, `future_counterparty` the other way — while
  neither real arm moved materially. What moved was the null.

  **The positive control separates under both designs** (3.45 against a 0.77
  placebo), so the harness can still see a leak it planted, which is all the
  gate asserts. But at a 46% noise floor a per-channel verdict is not a
  measurement, and the per-channel ladder should not be quoted.
- **Intervals existed at one budget only, and the archived manifests still
  reflect that.** `bootstrap_ci` was called at `budget=50` and nowhere else, so
  six of the seven budgets — including 200, which carries the HI-Large headline
  `recall@200` and `ring_recall@200` — were published as point estimates with
  no uncertainty at all. Everything costly in the bootstrap is
  budget-independent, so the omission bought nothing. It now emits `ci_lo@k` /
  `ci_hi@k` for every requested budget, with the unsuffixed pair still meaning
  `budget` so existing manifests stay comparable. **Every manifest in
  `results_archive/` predates that change** and carries an interval at 50 only;
  the per-budget intervals appear on the next run, which for HI-Large means the
  next cloud run.

- **The bootstrap holds the ranking fixed** and resamples only positive
  clusters, so it cannot see seed variance — the dominant source, and now known
  to be bin-edge sampling rather than optimizer noise. 500 resamples puts ~12
  replicates in each 95% tail; 2000+ would be better. It is also
  **anti-conservative**, and for TWO separate reasons, only one of which the
  code's own docstring names.

  The named one: unringed positives get one cluster each, and with 87% of
  HI-Large positives unringed that is most of the sample treated as independent
  when it is not.

  The unnamed one: a transaction emits a sender and a receiver account-day that
  carry the same score and the same label (§3c). The connected-component
  clustering merges them **incidentally** when they are ringed, because both
  endpoints share the ring — but for unringed positives it counts each endpoint
  as an independent draw. On the alerted set that stratum is 8–14% of positives
  and is inflated roughly 1.5–1.8× within itself, so the interval is narrowed
  by perhaps a third on that fraction. Small, but it is a *different* cause
  from the one documented, and fixing the ring gap would not fix it.

  **Not fixed here, deliberately.** Doing it properly needs a transaction →
  (sender, receiver) map for *every* transaction, and `to_account_days` keeps
  that map only for ring transactions precisely because carrying it for all of
  them costs a multi-gigabyte column at HI-Large. Doing it with the
  same-score proxy §3c uses for measurement would put a heuristic inside a
  published confidence interval, which is worse than a documented gap. It is
  recorded here and in the release checklist instead.
- **Between-generator-run variance is unestimated, and cannot be estimated from
  this dataset.** Every interval here — bootstrap SE, seed SD, the dispersion
  statistics, the sign tests — is a *within-run* nuisance component. The
  component the claims are actually about is the variation between independent
  runs of the generator.

  An earlier version of this document called the fix "cheap: HI-Small at ≥3
  independent generator seeds, or the LI-*variants as a second draw". **That
  was wrong on both counts.** IBM publishes six fixed files, not a seeded
  generator, so there is no way to draw HI-Small again; and LI-* differs in
  illicit ratio, so using it as a replicate confounds run-to-run variance with
  a configuration change. HI-Small, HI-Medium and HI-Large *are* independent
  runs, which is what makes the typology replication test above possible — but
  they differ in scale and window length too, so they bound the component
  rather than isolating it.

  The honest statement is that this is a **limitation of the benchmark**, not a
  step that was skipped. Isolating it needs a generator one can re-seed.

---

## 7. What the reproducibility result does and does not establish

> ⛔ **This section used to say "predictions are bitwise identical across arm64
> macOS and amd64 Linux", and the committed evidence does not support it.** The
> arm64 manifest predates `predictions_sha256`, so what was actually compared
> across architectures was a set of printed metrics. Equal metrics do not
> establish byte-identical prediction arrays — and the 15 "matching metrics"
> were deterministic functions of the predictions anyway, so reporting them as
> fifteen agreements inflated one bit of evidence into fifteen.

What IS established, and it is narrower:

1. **Deterministic repeatability on one architecture, at scale.** Two HI-Medium
   fits of the same data on amd64 Linux produced identical
   `train_matrix_sha256`, identical `predictions_sha256` and identical metrics;
   ⚠️ those archived digests were computed under the field's **old** definition
   — a float32 quantisation, i.e. agreement to a precision any metric could
   see, not bitwise identity of the stored file. The field now hashes the
   ordered `(txn_id, dtype, score)` payload exactly as written, and the
   quantised form moved to `predictions_tolerance_sha256`. Values across that
   boundary are not comparable; <!-- historical -->
   and the three canonical HI-Large seeds produced a byte-identical
   124,992,128-row training matrix. `docs/RESULT_LINEAGE.md`.
2. **Metric agreement across architectures**, from the older run: the same
   pipeline on arm64 macOS and amd64 Linux reported the same figures to full
   printed precision, with differing `model_artifact_sha256` (joblib embeds
   platform detail).

The stronger cross-platform claim needs a rerun of the *current* code on arm64
with a committed `predictions_sha256` to compare against. That has not been
done, and the claim is withdrawn until it is.

It is build hygiene, not a scientific result — **a bug reproduces perfectly
too.** It is still worth having, and `predictions_sha256` is the honest way to
state it.

---

## 8. Honest claim boundary

**Claimable:**

- metric instability exceeds effect sizes on this benchmark
- leak harnesses need placebo controls and a calibrated noise floor
- `recall@k` is uninterpretable without its ceiling
- `ring_recall` inflates over account-day recall by a large, measurable factor
- the pipeline reproduces **bitwise on one architecture** (two HI-Medium fits,
  three HI-Large seeds), and reported **matching metrics** across arm64 and
  amd64 in an older run. Bitwise-identical predictions ACROSS architectures <!-- historical -->
  is **not** claimable on current evidence
- ⛔ **removed from this list.** It read "a linear baseline already <!-- historical -->
  reaches precision@50 = 0.5706 at the top of the ranking" — a pooled level. That is a
  pooled level on a two-regime window and beats a random ranker by only
  1.16x-1.26x; §1 retracts it. What is claimable is the volume-segment lift:
  **17.6x** for the linear baseline and **310.3x** for the boosted model, both  <!-- derived: 0.04286/0.00244; 0.75714/0.00244 -->
  against a null of 0.00243-0.00244.
- anything about detecting money laundering in the real world
- that graph features do not help AML
- that any typology is harder than another
- that more training data improves detection
