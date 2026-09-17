# Related work, and what is actually new here

Until an eight-way audit pointed it out, this repository cited **exactly one**
external work — the AMLworld dataset paper — and it appeared only in
`CITATION.cff` and `DATA_LICENSE.md`, as attribution rather than scholarship.

That is a problem beyond etiquette. Several of this project's methods have
established literatures, and reinventing them silently makes the novelty claim
*unstated*, which reads as unaware. It also forfeits the credibility of
standing on known ground. This file fixes that, and in doing so narrows what
may be claimed as a contribution.

---

## 1. The dataset

- **Altman, Blanuša, von Niederhäusern, Egressy, Anghel, Atasu (2023).**
  *Realistic Synthetic Financial Transactions for Anti-Money Laundering
  Models.* NeurIPS Datasets and Benchmarks. <https://arxiv.org/abs/2306.16424>

  Source of HI-Small / HI-Medium / HI-Large. Every detection number in this
  repository is a claim about this generator, not about money laundering.

---

## 2. Budget-constrained evaluation — **not novel, and the claim is withdrawn**

The README's framing device is that reviewers see a fixed number of alerts a
day, so `recall@k` must be reported beside `recall_ceiling@k`. This is
precision/recall-at-k under a capacity constraint, and it is standard in at
least three fields:

- **Information retrieval.** Precision@k, recall@k and their ceilings are
  textbook — Manning, Raghavan & Schütze, *Introduction to Information
  Retrieval* (2008), ch. 8. The "ceiling" is R-precision's close relative.
- **Screening.** Capacity-constrained screening is the classical problem of the
  screening literature — Wald, *A Guide to Screening for Disease* (1984) and
  the ROC/yield trade-off treatments that follow it. Youden (1950), *Index for
  rating diagnostic tests*, is the early formalisation of operating-point
  choice.
- **Cost-sensitive and class-imbalanced learning.** Elkan (2001), *The
  Foundations of Cost-Sensitive Learning*; Provost & Fawcett (2001), *Robust
  Classification for Imprecise Environments*, on evaluating under an
  operating-point constraint rather than a single threshold.
- **Fraud and alert management.** Alert-volume constraints, alert-to-case
  conversion and analyst capacity are the operational vocabulary of the field.
  ⚠️ This bullet is the one with no citation attached: it reflects industry
  practice as the author understands it, and no source is offered. Treat it as
  an assertion, not a reference.

**What is therefore NOT claimed:** that alert-budget-aware evaluation is a new
idea. An earlier framing here presented it as a gap in the literature, on the
strength of an impression from reading rather than a survey, and no survey was
conducted. That framing is withdrawn.

**What is still worth stating:** this repository *instruments* the constraint —
`recall_ceiling@k`, `recall_efficiency@k` and seven budgets emitted beside
every number — and then shows what changes when you do. The contribution is the
harness and the measurements, not the concept.

---

## 3. Seeds, variance and reporting ranges — **prior art exists**

The finding that budget metrics swing 30–37% across seeds, and that a
single-run number is not a result, sits on top of an existing literature:

- **Bouthillier, Delaunay, Bronzi, Trofimov, Nichyporuk, Szeto, Sepah, Raff,
  Madan, Voleti, Kahou, Michalski, Serdyuk, Arbel, Pal, Varoquaux, Vincent
  (2021).** *Accounting for Variance in Machine Learning Benchmarks.* MLSys.
  Treats seeds and other nuisance sources as variance components to be budgeted
  rather than fixed.
- **Dodge, Gururangan, Card, Schwartz, Smith (2019).** *Show Your Work:
  Improved Reporting of Experimental Results.* EMNLP. Report distributions, not
  best-run point estimates.
- **Reimers & Gurevych (2017).** *Reporting Score Distributions Makes a
  Difference.* EMNLP. Score distributions over seeds change published
  conclusions.
- **Henderson, Islam, Bachman, Pineau, Precup, Meger (2018).** *Deep
  Reinforcement Learning That Matters.* AAAI. Seed sensitivity large enough to
  reverse method rankings.

**What this project adds** — stated as its own finding rather than as a novelty
claim, because no systematic search of the literature was conducted and
"nobody has shown this" is exactly the kind of assertion this repository
spends its time withdrawing — is narrower and mechanical: we identify *which*
nuisance factor is doing the work. In this configuration `random_state` has exactly one
live consumer — the 200,000-row subsample used to estimate histogram bin edges
— and the same spread reproduces in a second library whose only stochastic
element is the same subsample. So the instability is attributable to bin-edge
estimation at 0.11% prevalence, not to "seeds" as an undifferentiated bucket.
See `paper/RESULTS_metric_stability.md` §3b–3c.

---

## 4. Negative controls — **an established method this project reinvented**

The strongest methodological claim here is that *a null without a negative
control is an assertion*: the ring-recall null was replaced only after a
candidate null returned a strong effect on scores drawn independently of ring
membership. This is the negative-control idea, and it has a literature:

- **Lipsitch, Tchetgen Tchetgen & Cohen (2010).** *Negative Controls: A Tool
  for Detecting Confounding and Bias in Observational Studies.* Epidemiology
  21(3):383–388. The canonical statement.
- **Arnold, Ercumen, Benjamin-Chung & Colford (2016).** *Negative controls to
  detect selection bias and measurement bias in epidemiologic studies.*
  Epidemiology.
- **Permutation and randomisation tests**: Good, *Permutation, Parametric and
  Bootstrap Tests of Hypotheses* (2005); Phipson & Smyth (2010) on why the
  add-one estimator `(1+r)/(n+1)` is the correct permutation p-value — which is
  what `metrics.py` uses, and why `p = 1/(b+1)` is a resolution floor rather
  than a measurement.
- **Placebo/permuted-outcome arms** are standard in genomics
  (Storey & Tibshirani 2003) and in causal inference as placebo tests.

**What is new here** is not the tool but the demonstration: a published number
that was traceable to a manifest, recomputable, and covered by a provenance
checker was *still wrong by a sign*, and only a control caught it. The
negative-control literature argues for controls against confounding; this is a
case study of controls against a **misspecified null** inside an otherwise
rigorous reproducibility pipeline.

---

## 5. Reproducibility and provenance tooling — **the thing being argued against**

- **Experiment trackers**: MLflow, Weights & Biases, DVC, Sacred. All track
  runs, parameters and artifacts.
- **Model documentation**: Mitchell et al. (2019), *Model Cards*; Gebru et al.
  (2021), *Datasheets for Datasets*.
- **Reproducibility checklists**: Pineau et al. (2021), *Improving
  Reproducibility in Machine Learning Research*.

**The argument this project makes against all of them:** none can detect a
wrong estimand. `ring_recall_lift@200 = 1.43` was emitted by code, from
artifacts, at a recorded commit, under a checker that verified it traced to a
manifest — and it was wrong by a sign. Provenance answers *"did this number
come from that code and that data?"*. It cannot answer *"is this number
measuring the thing the sentence says it measures?"*. Only a control can.

---

## 6. Model risk management

- **Board of Governors of the Federal Reserve System / OCC.** *SR 11-7 /
  OCC 2011-12: Supervisory Guidance on Model Risk Management* (2011).
  `docs/LIMITATIONS.md` §5 is a self-assessment against it.

---

## 7. Summary of what may be claimed

| claim | status |
|---|---|
| Budget-aware evaluation is a new idea | **withdrawn** — standard in IR, screening and fraud ops |
| Seed variance matters and ranges should be reported | **not new** — Bouthillier 2021, Dodge 2019, Reimers 2017 |
| *Which* nuisance factor drives it here, reproduced across two libraries | **this project's finding**, stated narrowly. No systematic search was run, so novelty is not asserted — the body of this file says so and the summary used to contradict it |
| Negative controls detect bias | **not new** — Lipsitch 2010 |
| A negative control caught a sign error that full provenance discipline did not | **the contribution** |
| Verifiable published metrics without redistributing licensed data (replay bundles) | **plausibly new packaging**; no survey conducted, so stated as a claim about this repository only |
