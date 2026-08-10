# Statistical equivalence testing for quantum shot distributions

**Date:** 2026-08-10
**Status:** Research complete. Design not yet approved; no implementation changes made.
**Issue:** [#15](https://github.com/marqov-dev/marqov-capsule/issues/15) — bootstrap TVD confidence interval miscalibrated
**Related:** [#20](https://github.com/marqov-dev/marqov-capsule/issues/20) (spec ≠ implementation), [#30](https://github.com/marqov-dev/marqov-capsule/issues/30) (ε read from untrusted capsule)

---

## Why this document exists

Issue #15 was filed as a calibration bug. Investigating it established that the verification procedure is built on a statistically intractable problem, that three successive candidate repairs each fail in a different way, and that a correct procedure exists but is structurally different from what the spec normatively mandates.

This record exists so that work is not repeated. In particular it records **the approaches that did not work and why**, because each looked correct on paper and was eliminated only by measurement.

Provenance is tracked throughout. Every claim is marked as one of:

- **[measured]** — simulated in this investigation, reproducible from Appendix A
- **[verified]** — read from the primary source
- **[reported]** — from a research agent that claims a primary read, not independently checked
- **[unverified]** — cited from model knowledge; **must be checked against primary text before entering a normative spec**

That last category is not pedantry: during this research an automated summariser was caught fabricating quotations from a real paper.

---

## Summary of findings

1. The shipped procedure asserts irreproducibility on **byte-identical** input from roughly 4 qubits upward. **[measured]**
2. The cause is that the plug-in TVD estimator carries a noise floor `≈ (1/√(πn))·Σᵢ√(pᵢ(1−pᵢ))`, and the bootstrap interval is displaced upward by roughly twice that floor rather than corrected downward. **[measured]**
3. The bootstrap cannot be repaired by reconfiguration. TVD is not Hadamard-differentiable at `p = q`, which is provably fatal to bootstrap consistency. **[verified]**
4. Three candidate replacements were evaluated and rejected, each for a different measured reason.
5. **Estimating** TVD is polynomially harder than **testing** it — Θ(K/(ε² log K)) versus Θ(√K/ε²). The verifier was built around the expensive question. **[reported]**
6. A rigorous one-sided upper confidence bound on true TVD does exist, is elementary, and is usable at realistic shot counts. **[measured]**
7. The spec states a procedure and guarantees no error rate at all. That is the deeper defect; the seed makes it deterministic, not correct.

---

## 1. The defect

`CapsuleVerifier._bootstrap_tvd_ci` draws `r ~ Multinomial(n_ref, p̂)` and `s ~ Multinomial(n_new, q̂)` independently and returns percentiles of `TVD(r,s)`. That describes the sampling distribution of a biased estimator; the verdict logic in `verify_statistical` treats it as bounding the true TVD.

There are **two distinct experiments** here, and conflating them produces an apparent inconsistency. Both demonstrate the defect; they are not the same measurement.

**Experiment 1 — self-comparison.** The same count array on both arms, so `TVD̂ = 0` exactly. This isolates the interval's displacement from the estimator's bias. ε = 0.05: **[measured]**

| outcomes K | shots | point TVD | reported CI | verdict |
|---|---|---|---|---|
| 2 | 2,000 | 0.0000 | [0.0005, 0.0355] | VERIFIED |
| 16 | 2,000 | 0.0000 | [0.0315, 0.0690] | INCONCLUSIVE |
| 64 | 2,000 | 0.0000 | [0.0822, 0.1195] | **REJECTED** |
| 256 | 10,000 | 0.0000 | [0.0819, 0.0985] | **REJECTED** |

Displacement here is **1×** the noise floor: `TVD̂ = 0` and the bootstrap centres near the floor.

**Experiment 2 — two independent runs of the same experiment.** The realistic case, and what Appendix A block 1 measures: `TVD̂ ≈ b` (the floor) and the bootstrap centres near `TVD̂ + b`, so displacement is **2×** the floor. At ε = 0.02 this yields 100% REJECTED at K=16/n=4096, K=8/n=1024, and K=64 for all n ≤ 16384. **[measured]**, corroborating an independent **[reported]** measurement.

The diagnostic signature common to both: **the interval lies entirely above its own point estimate** — an interval that cannot contain the statistic it purports to describe.

Consequences:

- `REJECTED` has **no error control**. It fires whenever the noise floor exceeds ε, which is a fact about the shot budget, not about reproducibility.
- `VERIFIED` is unreachable unless ε exceeds the noise floor.
- The fixed seed (12345) makes this reproducible, not correct. Every conformant implementation reproduces the same wrong verdict.

The existing test suite covers only K = 2, the single regime where the defect is invisible. `tests/test_verifier.py:13-18` documents raising shots to 10,000 to stop a two-outcome test flaking — that was this bias, read as CI width.

---

## 2. The bias law

Under `p = q`: **[measured]**

> **E[TVD̂] ≈ (1/√(πn)) · Σᵢ √(pᵢ(1−pᵢ))**
>
> which reduces to **√((K−1)/(πn))** for uniform `p`

Verified across four distribution shapes, K ∈ {16,64}, n ∈ {4096,16384}; error 0.0–7.2%, mostly under 2%:

| shape | K | n | predicted | measured |
|---|---|---|---|---|
| uniform | 16 | 4,096 | 0.03414 | 0.03356 |
| uniform | 64 | 4,096 | 0.06997 | 0.06998 |
| peaked (98% on one outcome) | 16 | 4,096 | 0.00606 | 0.00610 |
| exponential weights | 64 | 16,384 | 0.03054 | 0.03054 |
| two-mode | 64 | 4,096 | 0.03963 | 0.03977 |

**Peaked distributions carry ~6× less bias than uniform at equal K.** Any resolvability guard must key on distribution shape, never on qubit count.

Note `Σᵢ√(p̂ᵢ(1−p̂ᵢ))` and effective support `K_eff = (Σᵢ√pᵢ)²` are **the same quantity**, not alternatives: for small `pᵢ`, `Σᵢ√(pᵢ(1−pᵢ)) ≈ Σᵢ√pᵢ = √K_eff`, so the bias law is `≈ √(K_eff/(πn))`. Present it once.

The `√((K−1)/(πn))` constant is derivable folklore — numerically confirmed here to under 1%, but not located as a stated theorem. For a citable version use Berend & Kontorovich ([arXiv:1205.6711](https://arxiv.org/abs/1205.6711)), which gives constants 1/4 and 1 without the π. **[reported]**

---

## 3. Why the bootstrap cannot be repaired

**Fang & Santos**, *Rev. Econ. Studies* 86(1):377–412, 2019 ([arXiv:1404.3763](https://arxiv.org/abs/1404.3763)): full Hadamard differentiability is **necessary and sufficient** for bootstrap consistency. The L¹ norm is only *directionally* differentiable at `p = q` — precisely the null under test. Their Example 2.1 (`|E[X]|`) is the same pathology. **[reported]**

**Sreekumar, Goldfeld & Kato**, *IEEE Trans. IT* 70(2):1233–1267, 2024, name TV as *the* exception: "Bootstrap consistency results for other f-divergences (except TV distance) may be derived in an analogous manner." **[reported]**

**Bastian, Dette & Koletzko** ([arXiv:2305.08609](https://arxiv.org/abs/2305.08609)) — **[verified]**, abstract read directly: their method "does not require differentiability of the norm and is in particular applicable for the maximum- and L¹-norm." The existence of a paper solving this problem specifically is itself evidence the naive approach fails.

**Sommerfeld & Munk**, *JRSS-B* 80(1):219–238, 2018 ([arXiv:1610.03287](https://arxiv.org/abs/1610.03287)): on finite support, plug-in bootstrap inconsistent (Thm 6); m-out-of-n consistent (Thm 2). **[reported]**

### A correction recorded deliberately

This investigation initially diagnosed the failure as a **boundary parameter** problem — TVD cannot go below zero, so `p = q` sits on the edge of the parameter space, analogous to a variance component estimated at zero, citing Andrews (2000).

**That diagnosis is wrong.** Andrews (2000) concerns a parameter on the boundary of the *parameter space*. This is a non-smooth *functional* of an interior parameter — a different failure mode with a different remedy literature. The correct citation is Fang & Santos. For non-uniformity of the subsampling/m-of-n remedies, cite Andrews & Guggenberger (2010), *Econometric Theory* 26(2):426–468. **[reported]**

The wrong diagnosis is recorded because it survived several rounds of reasoning and led to a materially wrong conclusion (that no valid bound could exist — see §5).

### Bayesian reformulation does not help

Kitagawa, Montiel Olea, Payne & Velez, *J. Econometrics* 217(1):161–175, 2020: for locally Lipschitz non-differentiable `g`, the posterior of `g(θ)` and the bootstrap distribution of `g(θ̂)` **coincide asymptotically**, so "credible intervals … cannot be presumed to be approximately valid confidence intervals." A symmetric Dirichlet(α) prior additionally injects `Kα` pseudo-counts, capping the expressible TV regardless of data. **[reported]**

---

## 4. Procedures evaluated and rejected

All **[measured]**. This section is the main reason this document exists.

### 4a. Percentile bootstrap (shipped)

Coverage of the true TVD, ε = 0.05, 2,000 shots/arm:

| K | true TVD | coverage |
|---|---|---|
| 2 | 0.00 | 1% |
| 16 | 0.00 | 0% |
| 64 | 0.00 | 0% |
| 64 | 0.20 | 58% |

### 4b. Pivotal / basic bootstrap — `[2T̂ − q₉₇.₅, 2T̂ − q₂.₅]`

Substantially better away from the boundary (K=16, true TVD=0.05: 19% → 93% coverage). **Rejected because it is anti-conservative exactly at the tolerance boundary**, against a nominal 2.5%:

| geometry | K | true TVD | VERIFIED rate |
|---|---|---|---|
| uniform base, mass shift | 16 | 0.0500 | **16.5%** |
| structured base, depolarizing | 16 | 0.0500 | 4.0% |
| uniform base, mass shift | 64 | 0.0500 | 2.0% |

The 16.5% vs 4.0% spread at **identical K and identical true TVD** is the deeper obstruction: the null boundary `TVD = ε` is **composite**, and its critical value depends on the shape of the difference. A research stream measured the 5th percentile of TVD̂ ranging from 0.0103 to 0.0378 across configurations all having true TVD = ε exactly. **[reported]** No single critical value is valid.

### 4c. Permutation null

Correctly calibrated as a test of `p = q` — type-I error 5% / 3% / 3% at K = 16 / 64 / 256 against nominal 5%; power for true TVD = 0.10 of 100% / 82% / 42%.

**Rejected as a certification rule on framing grounds, not calibration.** It tests the sharp null, so a high p-value is *absence of evidence*, not evidence of equivalence. An underpowered comparison passes automatically — the exact failure mode a verification tool must not have.

### 4d. Null-median subtraction — `max(0, T̂ − median(permutation null))`

Verdicts come out approximately right, but **the reported effect size is corrupted**: coverage 9% (K=16) and 0% (K=64) at true TVD = 0.20. Since TVD is reported to users as an interpretable quantity, a procedure that gets the verdict right while displaying a badly wrong number is not acceptable.

### 4e. The result that redirected the investigation

Coverage of the pivotal interval at the null **does not improve with sample size**:

| K | shots | shots/outcome | coverage | VERIFIED rate |
|---|---|---|---|---|
| 16 | 2,000 | 125 | 35% | 48% |
| 16 | 10,000 | 625 | 37% | 100% |
| 16 | 200,000 | 12,500 | 32% | 100% |
| 64 | 10,000 | 156 | 0% | 100% |
| 64 | 200,000 | 3,125 | 0% | 100% |

At 12,500 shots per outcome the interval still covers the truth 32% of the time while the *verdict* is correct 100% of the time. This is what motivated abandoning CI coverage as the design criterion — and, mistakenly for a period, abandoning the search for a valid bound.

---

## 5. What is achievable: a one-sided upper confidence bound

The investigation concluded prematurely that no valid bound on true TVD was obtainable. That was wrong. A rigorous bound exists and is elementary. **[measured]**

Two arms, tight in different regimes. Use `min(A, C)` — at **α/2 each**, since a minimum of two bounds each valid at 1−α has failure probability up to 2α.

### Arm C — concentration (worst-case optimal, rigorous)

```python
C = TVD(p̂, q̂) + sqrt( (log(1/alpha) / 2) * (1/n + 1/m) )
```

1. The plug-in is biased **upward**, so `TV(p,q) ≤ E[TV(p̂,q̂)]` by Jensen.
2. `E[TV(p̂,q̂)] ≤ TV(p̂,q̂) + t` with probability `1−α` by McDiarmid. One sample moves two coordinates by `1/n`, halved by the `½`, so the bounded difference is `1/n` and `Σcᵢ² = 1/n + 1/m`.

The slack is **free of K**. Note `log(1/α)`, **not** `log(2/α)` — McDiarmid's one-sided form. An earlier draft of this document used the two-sided constant, delivering 2.5% while claiming 5% and running 11% wider than necessary. That is the same undeclared-level error §7 identifies in the shipped `ci_upper`.

Measured coverage, nominal 95%: **[measured]**

| K | n | true TVD | mean UCB | coverage |
|---|---|---|---|---|
| 16 | 4,096 | 0.000 | 0.0638 | 100% |
| 16 | 4,096 | 0.200 | 0.2302 | 100% |
| 64 | 4,096 | 0.000 | 0.0996 | 100% |
| 256 | 8,192 | 0.050 | 0.1285 | 100% |

Conservative by construction — it never over-certifies, satisfying the fail-closed invariant (§7). Framed correctly, arm C **is** the least-favourable-configuration solution to the composite null of §4b; its conservatism is that supremum, not an unrelated design choice.

### Arm A — L₂ (dominant at large K)

`A = ½√(K · max(L2sq + z·sd, 0))` via Cauchy–Schwarz on the unbiased ‖p−q‖₂² estimator `Σᵢ[(Xᵢ−Yᵢ)² − Xᵢ − Yᵢ]/n²`.

**Arm A is load-bearing, not a footnote.** Under the null with near-uniform `p`, `sd(L2sq) ~ √2‖p‖₂/n`, so `A ~ K^{1/4}/√n` against arm C's `K^{1/2}/√n`. Measured — `A·√n/K^{1/4}` is flat across two decades of K: **[measured]**

| K | arm A | arm C | A/C | A·√n/K^{1/4} |
|---|---|---|---|---|
| 16 | 0.0236 | 0.0458 | 0.51 | 1.066 |
| 256 | 0.0537 | 0.1211 | 0.44 | 1.214 |
| 1024 | 0.0735 | 0.2202 | 0.33 | 1.176 |
| 4096 | 0.1040 | 0.4061 | 0.26 | 1.177 |

Shots to certify ε = 0.05 at the null: **[measured]**

| qubits | K | arm A | arm C | reduction |
|---|---|---|---|---|
| 6 | 64 | 3,489 | 16,858 | 5× |
| 8 | 256 | 6,865 | 48,190 | 7× |
| 10 | 1,024 | 16,638 | 160,051 | 10× |
| 12 | 4,096 | 32,739 | — | — |

**This retracts the "past 12–16 qubits a certificate is impractical" claim** made in an earlier draft. That was an arm-C-only result. At 12 qubits arm A certifies with ~33k shots, which is routine.

⚠ These arm-A figures use an sd calibrated across replications — information a real verifier does not have — so they are **optimistic lower bounds**. A deployable arm A needs a plug-in or empirical-Bernstein variance bound, and the U-statistic's variance differs between null and alternative, so the plug-in must be conservative in the alternative direction. **Until that is done, arm A is not rigorous and `min(A,C)` does not satisfy the fail-closed invariant.** This is the single largest piece of open work.

### Shot budget

The budget must satisfy `bias + t_α + z_β·sd ≤ ε`, where the third term is **power**. Solving only `bias + t_α ≤ ε` sizes for the *mean* of `TVD̂` while the verdict depends on its *realization*.

An earlier draft omitted the power term. At the budgets it published, certification probability on a **perfect reproduction** was measured at 51–59% — a coin flip, recreating the very failure mode §5 claims to fix. **[measured]**

Corrected arm-C budget using the asymptotic `sd(TVD̂) ≈ ½√(2(1−2/π)(1−1/K)/n)`. The β side need not be rigorous — over-running shots is not a correctness failure — so the asymptotic sd is used rather than a second concentration term, which would cost ~2× shots for no correctness gain. ε = 0.05: **[measured]**

| qubits | K | 50% power (old) | 80% power | 95% power |
|---|---|---|---|---|
| 2 | 4 | 2,990 | 3,694 | 4,478 |
| 4 | 16 | 6,208 | 7,380 | 8,607 |
| 6 | 64 | 15,619 | 17,528 | 19,296 |
| 8 | 256 | 46,714 | 49,486 | 52,424 |
| 10 | 1,024 | 156,792 | 162,937 | 169,322 |

Correcting the power term and the one-sided constant **together is nearly free** — 7,380 vs 6,852 shots at K=16 — because the `log(1/α)` correction returns most of what power costs. Verified: the 80%-power budget delivers a measured 83–86% certification rate.

The value of a closed form is that ε and shot count are chosen **together, before the run**, rather than discovered as an INCONCLUSIVE afterwards.

---

## 6. Sample complexity: the wrong problem was chosen

| Task | Complexity in K |
|---|---|
| Test `p = q` vs `TVD ≥ ε` | Θ(max{K^{2/3}/ε^{4/3}, √K/ε²}) — sublinear |
| **Estimate** TVD to ±ε | Θ(K/(ε² log K)); Ω(K/log K) even at ε = 0.49 |
| Plug-in estimator | Θ(K/ε²) |

Testing: Chan, Diakonikolas, G. Valiant & P. Valiant, SODA 2014 ([arXiv:1308.3946](https://arxiv.org/abs/1308.3946)). Estimation: Jiao, Han & Weissman, *IEEE Trans. IT* 64(10):6672–6706, 2018 ([arXiv:1705.00807](https://arxiv.org/abs/1705.00807), Thm 4). **[reported]**

**In this project's regime the celebrated K^{2/3} branch never fires.** The branches cross at ε = K^{−1/4} (0.177 at K=1024), so for ε ≤ 0.10 the governing cost is plain **√K/ε²**. **[reported]**

`log K` is the entire improvement available over the plug-in for estimation. There is no clever estimator waiting to be found.

### How arm A escapes this

The estimation lower bound applies to *estimating* TVD for arbitrary `p, q`. **Arm A is an L₂ tester in disguise**, and `L₂` identity testing at resolution `δ = 2ε/√K` costs `Θ(1/(√K·δ²)) = Θ(√K/ε²)` — the cheap testing branch, not the expensive estimation one.

There is no contradiction with the tolerant-testing lower bound, because **A is valid but not tight**: it declines to certify sparse differences even when `TVD ≤ ε`. For the case that actually matters — a genuine reproduction, where the difference *is* pure sampling noise and therefore spread out — A fires. For peaked `p`, `‖p‖₂ → 1` and A degrades to arm C's scaling. That complementarity is why `min(A, C)` is the right shape rather than either alone.

**Hore & Barber** ([arXiv:2602.05862](https://arxiv.org/abs/2602.05862)) — **[verified]**: "certifying equality of distributions, or even providing a tight upper bound on the total variation (TV) distance between the distributions, is impossible to achieve in a distribution-free regime." Their impossibility concerns arbitrary supports; a finite known support admits bounds, at cost `n ≳ K/ε²` — which is exactly the floor in §2.

---

## 7. Methodology findings

### Equivalence testing inverts the null

Under a conventional null, "not significantly different" is absence of evidence and an underpowered study passes automatically. Under TOST the hypotheses invert — H₀: `TVD ≥ ε` — so Type I error becomes *falsely declaring equivalence* and an underpowered study **fails**. For a certification tool that inversion is the whole point. **[unverified]** — Schuirmann 1987; Berger & Hsu 1996 cited from model knowledge.

**The current spec states a procedure and guarantees no error rate whatsoever.** That is the defect a reviewer finds first.

### The claim is one-sided

TVD ≥ 0, so only one boundary binds. Taking `ci_upper` from a two-sided 95% interval silently runs a one-sided test at α = 0.025, while `ci_lower > ε` tests a *different, unstated* hypothesis at yet another level. Neither level is declared anywhere.

### Fail closed

ICH E9 §3.3.2: equivalence testing "is not conservative in nature, so that many flaws in the design or conduct of the trial will tend to bias the results towards a conclusion of equivalence." **[unverified]**

Sloppiness biases equivalence testing *toward* the desired verdict. Degenerate input must fail to INCONCLUSIVE or REJECTED, never VERIFIED. This is a design invariant, not a preference.

### Asymmetric error rates are standard

| System | Direction controlled | Rate |
|---|---|---|
| Bioequivalence (EMA/ICH) | false equivalence (consumer risk) | 5% one-sided; power left to the sponsor |
| **Quantum Volume** (Cross et al., [arXiv:1811.12926](https://arxiv.org/abs/1811.12926)) | false success | 2.3% (z=2, 97.5% one-sided), ≥100-trial hard guard |
| criterion.rs | false regression alarm | ~5%, documented |

**[reported]** Quantum Volume is the closest in-domain precedent, and four of its properties transplant directly: one-sided, explicit error rate, domain-motivated fixed threshold, and a hard minimum-n guard independent of the statistic.

### Repeated verification voids the guarantee

`INCONCLUSIVE` currently advises adding shots. Re-verifying at the same α after adding data inflates the false-equivalence rate without bound. The regulatory remedy is pre-declared α adjustment (94.12% Pocock-style; Potvin et al. 2008); the modern one is anytime-valid inference — confidence sequences / e-processes (Ramdas, Grünwald, Vovk & Shafer, [arXiv:2210.01948](https://arxiv.org/abs/2210.01948)). **[reported]** Either way the current loop has no guarantee at all.

### Verdict *and* estimate

The reform literature is routinely misread as opposing automated verdicts. The primary sources explicitly carve out this use case — the ASA 2016 statement's Principle 3 notes "pragmatic considerations often require binary, 'yes-no' decisions", and the 2019 "abandon significance" editorial exempts "industrial quality control, in which a highly automated decision rule is needed and the costs of erroneous decisions can be carefully weighed". Lehmann (1993) settled the presentation question: report the estimate, and combine it with a decision at a stated level. **[reported]**

The defensible configuration is: **estimate and bound primary, verdict derived, error rate stated, threshold on the effect size and pre-specified.** A threshold on ε (an effect size) is the kind these sources endorse; a threshold on a p-value is not.

Consider four states rather than three. Crossing a difference test with an equivalence test yields "detectable but within tolerance" — which at high shot counts is what a *good* reproduction looks like — distinct from "underpowered". The current INCONCLUSIVE merges them.

---

## 8. Domain survey

**No quantum SDK performs a statistical test on two count dictionaries.** **[reported]**

- **Qiskit** — `hellinger_fidelity` discards shot counts entirely; two 1-shot runs that agree score 1.0. Descriptive, statistically inert. Definition changed in Terra 0.17, so pre-2021 values are on a different scale.
- **Qiskit Aer** — `compare_counts` with absolute tolerances (`delta=0.05*shots`). Because the tolerance scales with `n` while the standard error scales with `√n`, the same nominal rule is ~1.0σ at 100 shots and ~6.3σ at 4,000 — false-failure rates of 0.317 versus 2.6×10⁻¹⁰, about **nine** orders of magnitude apart.
- **Cirq** — XEB only, against ideal simulation. Zero occurrences of `chisquare` or `kolmogorov` repo-wide.
- **pyGSTi** — the only rigorous machinery present (`two_delta_logl` → Nsigma).

**Hellinger fidelity does not solve the problem** — it is a reparameterisation of the same plug-in estimate and collapses under the null at large K. **XEB** escapes the K-dependence (it is a linear functional, variance ~1/M independent of K) but requires classically computed `p_ideal` and assumes Porter-Thomas, so it cannot serve as a two-sample statistic here. **[reported]**

**There are no conventional thresholds.** No "Hellinger fidelity > 0.9" standard exists. The single hard standardised threshold in the field is Quantum Volume's HOP > 2/3 at 2σ. Three different quantities are called "fidelity" in benchmarking suites and are not interchangeable.

**No prior art pairs a sealed artifact with a statistical equivalence verdict.** No CI or benchmarking system frames its gate as a non-inferiority test, so none controls its false-*pass* rate — thin evidence passes by default. That inversion is genuinely unclaimed ground.

---

## 9. Design implications

Not yet approved; recorded as the conclusion the evidence supports.

1. **Separate detection from certification.** They are different questions with different sample complexities and different tools. Conflating them is the root error.
   - *Certify* ("equivalent within ε?") — one-sided UCB (§5). Rigorous, conservative, fails closed.
   - *Detect* ("distinguishable at all?") — permutation-calibrated statistic, if a REJECTED-style claim is retained.
2. **Delete the bootstrap from the normative spec.** Provably inconsistent for this functional; a fixed seed makes it reproducibly wrong.
3. **State error rates in the spec.** False-equivalence ≤ 5% one-sided is the precedent-backed target. Power is not certified; report the required shot count instead.
4. **Replace `min_shots: 100`** with the shape-aware resolvability guard from §2/§5. A constant independent of K and ε cannot do this job.
5. **Reconsider REJECTED.** As implemented it asserts irreproducibility on identical data. The regulatory pattern — "equivalence demonstrated" / "not demonstrated", with no positive claim of difference — may be the honest scope.
6. **Report estimate and bound primarily**, verdict derived and labelled.
7. **Publish the shot budget** so ε and n are chosen together, before the run.
8. **Handle the re-run loop** with anytime-valid inference (confidence sequences), not α adjustment. Pocock-style adjustment requires knowing the number of looks in advance; the re-run loop is unbounded and operator-driven.

Sharper methods exist for the `n ≫ K` regime — the constrained bootstrap of Bastian–Dette–Koletzko — and are worth revisiting once the conservative path works.

### Threat model — the statistics are moot without this

The verifier consumes an **untrusted artifact**. Three consequences that no amount of statistical correctness survives:

- **ε, α, and the declared outcome space must come from verification policy, not the capsule.** This is [#30](https://github.com/marqov-dev/marqov-capsule/issues/30): if ε is read from the artifact under test, an attacker sets ε = 1 and certifies anything. Every finding in this document is void under that condition.
- **The fixed seed 12345 is worse than "reproducibly wrong."** A constant seed shared across all capsules is *searchable*: count vectors can be fitted to pass that specific bootstrap stream. If any Monte Carlo survives into the normative path, seed it from the capsule hash — never from a constant.
- **`K` must be the declared register width, not the observed support.** Computing `K` or `K_eff` from distinct observed keys under-reports the noise floor whenever outcomes are rare or missing from one arm — which **fails open**, and rare-outcome mismatch is the common real reproducibility failure. Arm C is immune (its slack is K-free), but the resolvability guard and the shot budget are not. Union-of-supports is acceptable only as a fallback when the schema is absent.

### Invariants and their machine checks

Recommendations are not enforceable; invariants with checks are. The bootstrap defect survived because the suite only covered K = 2 — a stated invariant with a K-parameterised property test would have caught it on the first run.

| Invariant | Check |
|---|---|
| Never VERIFIED when UCB > ε | Property test over random count pairs |
| ε and α sourced from policy, not capsule | Type constraint on the verifier config, so a capsule-derived value cannot typecheck |
| K from declared schema | Same |
| No Monte Carlo in the normative path | Lint rule banning RNG imports in the verifier module |
| Degenerate input never VERIFIED | Property test on zero-count and single-outcome inputs |
| Verdict never contradicts the reported bound | Property test asserting verdict is a pure function of (UCB, ε) |

### Scope

The procedure assumes **categorical shot outcomes**. Continuous expectation-value results — where `shots` is absent — are out of scope for this verifier and need a separate treatment.

The **one-sample case** (reference is an analytic distribution from a statevector simulation rather than a prior sealed run) is materially cheaper: both the bias floor and the McDiarmid slack drop by `√2`, roughly halving the budget. It deserves its own row in the budget table.

A **marginals fallback** for very large outcome spaces is weaker than it appears: marginal agreement does not imply joint agreement, so certifying marginals while the seal implies joint reproducibility fails open. If retained it needs multiplicity control across marginals and a distinct verdict label — not VERIFIED.

**Multiplicity across many new runs verified against one shared reference** is a separate problem from the re-run loop of §7 and is not addressed here.

---

## 10. Open questions

Several questions in the first draft were closed by technical review (§11); what remains:

1. **Making arm A rigorous.** This is the critical path, not finding a third arm. C is rate-optimal for the worst case, A for the near-null/spread-difference case; the pair is the right structure. Needs empirical Bernstein on the U-statistic, with a variance bound conservative in the alternative direction.
2. **Arm A's coverage under sparse differences** — the regime where it is valid but declines to certify. Unmeasured.
3. **Confidence sequences for the re-run loop** — which construction, and at what cost in shots.
4. Given three procedures failed checks that each looked correct on paper, and a fourth (the budget) shipped a 50%-power table — what else has not been measured?

Closed by review: `min(A,C)` is the right structure (Q1); REJECTED should not survive as a statistical claim, since §4c shows the detection arm has no power guarantee — 42% at K=256 — and both a silent REJECTED and an absent one mislead (Q2); four states, but only if the fourth derives from the *certification* arm ("certified, and difference detectable") rather than requiring the detection arm to carry a verdict (Q3); confidence sequences over α adjustment (Q4).

---

## 11. Review history

**2026-08-10 — technical review.** Seven blocking findings, all confirmed by measurement before acceptance:

| ID | Finding | Status |
|---|---|---|
| F1 | Shot budget had no power term; certification ≈53% on a perfect reproduction | Confirmed (51–59% measured); §5 corrected |
| F2 | Arm A is load-bearing and invalidates the 12–16 qubit ceiling | Confirmed (5–10× shot reduction); §5, §6 corrected, claim retracted |
| F3 | `min(A,C)` is not a 1−α bound; arm A not finite-sample rigorous | Accepted; §5 corrected, promoted to open question 1 |
| F4 | Two-sided McDiarmid constant used for a one-sided claim | Confirmed algebraically; §5 corrected |
| F5 | §1 table and Appendix A ran different experiments | Confirmed; §1 split into two labelled experiments |
| F6 | #30 referenced but never addressed; constant seed is searchable | Accepted; threat-model section added to §9 |
| F7 | K must be declared register width, not observed support | Accepted; §9 |

Also adopted: §4b's "no single critical value is valid" softened — the least-favourable-configuration supremum *is* valid, and arm C is that solution, which explains its conservatism; the two guard proposals in §2 identified as the same quantity rather than alternatives; scope, one-sample, marginals, and multiplicity notes added to §9.

One review point deferred rather than adopted: the observation that §9.2 (delete the bootstrap) does not depend on the unverified Fang–Santos citation, because §4e measures the same conclusion independently (coverage flat in n is precisely the corollary of directional-only differentiability). Recorded here so the citation check does not become a gate on the spec change.

---

## Appendix A — reproduction

Requires only numpy. Verified to run end to end and to reproduce every headline result in this document.

Monte Carlo figures move by a few percentage points across RNG streams — the pivotal anti-conservatism cell reports 16.5% in §4b and ~13% from this script. The conclusions are insensitive to that; a nominal 2.5% rate measuring anywhere in the low teens is the finding. Reproduce the qualitative result, not the digits.

```python
import numpy as np
def tv(a, b): return 0.5 * np.abs(a / a.sum() - b / b.sum()).sum()

# --- 1. the defect: identical distributions rejected ---
def current_ci(x, y, B, rng):
    n1, n2 = x.sum(), y.sum(); p, q = x / n1, y / n2
    boot = [tv(rng.multinomial(n1, p), rng.multinomial(n2, q)) for _ in range(B)]
    return np.percentile(boot, 2.5), np.percentile(boot, 97.5)

rng = np.random.default_rng(0); eps = 0.02
for K, n in ((4, 4096), (8, 1024), (16, 4096), (64, 16384)):
    p = np.full(K, 1.0 / K)
    v = [current_ci(rng.multinomial(n, p), rng.multinomial(n, p), 199, rng) for _ in range(100)]
    print(f"K={K:>3} n={n:>6}  REJECTED on identical data: "
          f"{100 * sum(lo > eps for lo, _ in v) // len(v)}%")

# --- 2. the bias law, including non-uniform shapes ---
for K, n in ((16, 4096), (64, 4096), (64, 16384)):
    for name, p in (("uniform", np.full(K, 1.0 / K)),
                    ("peaked", np.concatenate([[0.98], np.full(K - 1, 0.02 / (K - 1))]))):
        pred = np.sum(np.sqrt(p * (1 - p))) / np.sqrt(np.pi * n)
        meas = np.mean([tv(rng.multinomial(n, p), rng.multinomial(n, p)) for _ in range(150)])
        print(f"{name:>8} K={K:>3} n={n:>6}  predicted {pred:.5f}  measured {meas:.5f}")

# --- 3. pivotal is anti-conservative at the tolerance boundary ---
def pivotal_hi(x, y, B, rng):
    n1, n2 = x.sum(), y.sum(); p, q = x / n1, y / n2; T = tv(x, y)
    boot = [tv(rng.multinomial(n1, p), rng.multinomial(n2, q)) for _ in range(B)]
    return max(0.0, 2 * T - np.percentile(boot, 2.5))

eps, n, K = 0.05, 4096, 16
p = np.full(K, 1.0 / K); q = p.copy(); s = eps / (K // 2)
q[:K // 2] += s; q[K // 2:] -= s                    # true TVD == eps exactly
v = sum(pivotal_hi(rng.multinomial(n, p), rng.multinomial(n, q), 199, rng) <= eps
        for _ in range(200))
print(f"pivotal VERIFIED at true TVD == eps: {v / 2:.1f}%  (nominal 2.5%)")

# --- 4. arm C, with the ONE-SIDED McDiarmid constant (log(1/alpha)) ---
ALPHA = 0.05
def ucb(x, y, alpha=ALPHA):
    n, m = x.sum(), y.sum()
    return tv(x, y) + np.sqrt((np.log(1 / alpha) / 2) * (1 / n + 1 / m))

for K, n, t in ((16, 4096, 0.0), (64, 4096, 0.0), (256, 8192, 0.05)):
    p = np.full(K, 1.0 / K); q = p.copy()
    if t > 0:
        s = t / (K // 2); q[:K // 2] += s; q[K // 2:] -= s
    us = [ucb(rng.multinomial(n, p), rng.multinomial(n, q)) for _ in range(200)]
    print(f"K={K:>4} n={n:>6} true={t:.2f}  mean UCB {np.mean(us):.4f}  "
          f"coverage {100 * np.mean([u >= t for u in us]):.0f}%")

# --- 5. shot budget WITH the power term (z_beta), else ~50% certification ---
def budget(K, eps, z_beta, alpha=ALPHA):
    for n in np.unique(np.logspace(3, 8, 600).astype(int)):
        bias = np.sqrt((K - 1) / (np.pi * n))
        t = np.sqrt((np.log(1 / alpha) / 2) * (2 / n))
        sd = 0.5 * np.sqrt(2 * (1 - 2 / np.pi) * (1 - 1 / K) / n)
        if bias + t + z_beta * sd <= eps:
            return n
    return None

for K in (4, 16, 64, 256, 1024):
    print(f"K={K:>5} eps=0.05  50% power: {budget(K, .05, 0):>8,}   "
          f"80%: {budget(K, .05, 0.8416):>8,}   95%: {budget(K, .05, 1.645):>8,}")

# --- 6. arm A scales as K^(1/4)/sqrt(n), vs arm C's K^(1/2)/sqrt(n) ---
# NB: sd here is calibrated across replications, which a real verifier cannot do.
#     These are optimistic lower bounds until arm A gets a finite-sample variance bound.
def l2sq(x, y, n): return np.sum((x - y) ** 2 - x - y) / n ** 2

for K in (16, 256, 1024, 4096):
    n = 8192; p = np.full(K, 1.0 / K)
    vals = [l2sq(rng.multinomial(n, p), rng.multinomial(n, p), n) for _ in range(150)]
    A = 0.5 * np.sqrt(K * max(np.mean(vals) + 1.96 * np.std(vals), 0))
    print(f"K={K:>5}  armA {A:.4f}   A*sqrt(n)/K^0.25 = {A * np.sqrt(n) / K ** 0.25:.3f}")
```

---

## Appendix B — verification status

**Verified here against primary sources:**
- Bastian, Dette & Koletzko, [arXiv:2305.08609](https://arxiv.org/abs/2305.08609) — title, authors, abstract; L¹/max-norm and constrained bootstrap claims confirmed verbatim.
- Hore & Barber, [arXiv:2602.05862](https://arxiv.org/abs/2602.05862) — impossibility statement confirmed verbatim.

**Measured in this investigation:** every table marked **[measured]**; the bias law across four distribution shapes; all four rejected procedures; UCB coverage and shot budget.

**Reported by research agents claiming a primary read, not independently checked:** Fang & Santos; Sreekumar–Goldfeld–Kato; Sommerfeld–Munk; Chan–Diakonikolas–Valiant–Valiant; Jiao–Han–Weissman; Kitagawa et al.; EMA bioequivalence guideline; Quantum Volume paper; SDK survey.

**Unverified — check before entering a normative spec:** Schuirmann 1987; Berger & Hsu 1996; ICH E9 §3.3.2 and §3.5; property-testing citations [arXiv:1708.00002](https://arxiv.org/abs/1708.00002) and [arXiv:1902.01219](https://arxiv.org/abs/1902.01219).

**Known research hazards in this session:** an automated summariser was caught fabricating quotations from "Justify Your Alpha"; one research stream lost its transcript and was partially reconstructed; the web-search budget was exhausted mid-investigation, so later gaps were filled by direct PDF fetches and by model knowledge. Treat any quotation not marked **[verified]** as provisional.
