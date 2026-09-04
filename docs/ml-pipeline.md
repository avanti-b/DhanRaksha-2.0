# ML pipeline

How the model is trained, why each step is there, and what the numbers mean.

---

## The problem

283,726 transactions after cleaning. 473 are fraud — 0.167%.

This shapes everything. A classifier that always predicts "legitimate" achieves
99.83% accuracy. Accuracy is therefore never reported here as a headline figure,
and the training objective is not "be right most of the time" but "find a useful
operating point on the precision/recall curve".

---

## Pipeline

```
data/creditcard.csv
      │
      ▼  load_dataset()        validate columns exist
      │
      ▼  clean_dataset()       drop nulls, drop 1,081 exact duplicates
      │
      ▼  train_test_split()    stratified 80/20, random_state=42
      │                        train 226,980 (378 fraud)
      │                        test   56,746 ( 95 fraud)   ← never touched again
      │
      ▼  FeaturePipeline.fit(X_train)      ← TRAINING SPLIT ONLY
      │     standardise Time and Amount
      │     V1–V28 pass through
      │
      ▼  SMOTE.fit_resample(X_train)       ← TRAINING SPLIT ONLY
      │     378 fraud → 226,602 fraud
      │
      ▼  RandomForestClassifier.fit()
      │     100 trees, class_weight='balanced', random_state=42
      │
      ▼  evaluate on X_test                ← real distribution, no SMOTE
      │
      ▼  ml/artifacts/
            fraud_model.pkl          the forest
            feature_pipeline.pkl     the fitted scaler + column contract
            model_metadata.json      metrics, thresholds, risk reference
```

Reproduce with:

```bash
python -m ml.train --data data/creditcard.csv --version rf-v1
```

Fixed seed (42) throughout — split, SMOTE and forest — so the run is repeatable.

---

## Step-by-step reasoning

### Cleaning

1,081 exact duplicate rows are removed. These are byte-identical records across
all 31 columns. Keeping them would let the same transaction appear in both
training and test, which is leakage of the most direct kind.

Nulls: the dataset has none, but the check runs anyway.

### Splitting before anything else

The split happens **before** the scaler is fitted and before SMOTE. Both of those
learn from data, and both must learn only from training data.

Stratified, so the test split holds 95 fraud cases rather than whatever an
unstratified draw happens to produce. With a 0.167% positive rate, a random split
could vary the test fraud count substantially and make metrics unstable between
runs.

### Scaling only Time and Amount

`V1`–`V28` are PCA components produced by the dataset authors — already centred
and scaled, with the variance structure carrying the information. Re-standardising
each component independently would rescale them relative to each other and
destroy that structure.

`Time` (0–172,792 seconds) and `Amount` (0–25,691) are raw and on scales that
dwarf the components. Both are standardised with `StandardScaler`.

**The scaler is fitted on `X_train` only.** The original project fitted it on the
full frame before splitting. That leaks test-set statistics into training. The
practical effect for two columns is small — reproduced precision, recall and F1
came out identical to four decimals — but the previous claim that the test set
was untouched was not strictly true, and now it is.

### SMOTE, on training data only

With 378 fraud rows against 226,602 legitimate ones, a decision tree gains almost
nothing from splitting on fraud: nearly every leaf is pure-legitimate by default.
SMOTE (Synthetic Minority Over-sampling Technique) creates synthetic fraud
examples by interpolating between a minority point and its nearest minority
neighbours, balancing the training set to 226,602 per class.

**Why it must never touch the test set.** Synthetic points are interpolations of
real ones. If they appeared in the test set, the model would be scored on rows
derived from data it trained on. Every metric would inflate, and the result would
be meaningless. In `ml/train.py`, `smote.fit_resample` is called on
`X_train_scaled` only; `X_test_scaled` goes straight to evaluation. There is no
code path that can resample the test set.

**What SMOTE costs.** Interpolating between fraud cases can produce feature
combinations that never occur in reality, and can blur the boundary in regions
where fraud and legitimate points sit close together. It helps materially here,
but it is a modelling assumption rather than free improvement.

### Random Forest

```python
RandomForestClassifier(
    n_estimators=100,
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
)
```

Chosen and retained because it handles non-linear interactions among 28
anonymous components without feature engineering, is robust to their differing
scales, exposes feature importances that make risk explanations concrete, and
trains on CPU in minutes.

`class_weight='balanced'` on top of SMOTE is belt and braces — mild, and
preserved from the original configuration deliberately so measured differences
are attributable to the pipeline fix rather than confounded by retuning.

The predicted probability is the fraction of the 100 trees voting fraud. It is a
real quantity from a real model. Nothing in the application ever synthesises,
adjusts or defaults a probability.

---

## Results

Test split: 56,746 transactions, 95 fraud. Threshold 0.5. Model `rf-v1`.

| Metric | Random Forest | Logistic Regression |
|---|---|---|
| Precision | **0.9114** | 0.0530 |
| Recall | **0.7579** | 0.8737 |
| F1 | **0.8276** | 0.1000 |
| ROC-AUC | **0.9662** | 0.9619 |
| PR-AUC | **0.8040** | — |

**Confusion matrix (Random Forest):**

|  | Predicted legitimate | Predicted fraud |
|---|---|---|
| Actually legitimate | 56,644 | 7 |
| Actually fraud | 23 | 72 |

Read plainly: of 95 real frauds, 72 caught and 23 missed. Of 56,651 legitimate
transactions, 7 wrongly flagged.

### Why the baseline matters

Logistic regression scores a ROC-AUC of 0.9619 — barely below the forest's
0.9662 — and catches *more* fraud (recall 0.87 against 0.76). By those two
numbers alone it looks competitive.

It produced 1,479 false positives against 83 true positives. **Nineteen out of
twenty of its alarms are wrong.** In deployment that means 1,479 customers
declined to catch 83 frauds.

This is the clearest possible demonstration of why ROC-AUC is misleading on
severely imbalanced data: the false positive rate is computed against a
denominator of 56,651, so 1,479 false alarms is only 2.6% — which barely dents
the curve while being operationally catastrophic. PR-AUC and raw FP/FN counts
are reported precisely because they do not hide this.

### Feature importances

Top six: `V14`, `V10`, `V12`, `V4`, `V17`, `V11`. These same components are what
the risk engine monitors for outliers — the choice is driven by measured
importance, not intuition.

Their real-world meaning is unknown, since the original features were removed for
confidentiality. This limits how useful an explanation like "V14 is anomalous"
can be to a human reviewer.

---

## Threshold analysis

| Threshold | Precision | Recall | F1 | FP | FN |
|---|---|---|---|---|---|
| 0.30 | 0.7700 | 0.8105 | 0.7897 | 23 | 18 |
| 0.40 | 0.8736 | 0.8000 | **0.8352** | 11 | 19 |
| 0.50 | 0.9114 | 0.7579 | 0.8276 | 7 | 23 |
| 0.60 | 0.9324 | 0.7263 | 0.8166 | 5 | 26 |
| 0.70 | 0.9714 | 0.7158 | 0.8242 | 2 | 27 |

**The trade-off.** Lowering the threshold catches more fraud and flags more
legitimate customers. Raising it does the reverse. There is no setting that
improves both.

**Reading the table.** F1 peaks at 0.40, where the model catches 76 of 95 frauds
with 11 false alarms. Moving to 0.50 trades four caught frauds for four fewer
false alarms. At 0.70 false alarms nearly vanish (2) but 27 frauds get through.

**Which to choose** depends on the relative cost of a missed fraud against a
declined customer — a business question, not a statistical one. A bank absorbing
large average fraud losses should sit lower; one where declines drive churn
should sit higher.

**How to change it.** `FRAUD_THRESHOLD` in `.env`. It flows through `Config` into
`FraudService` and is recorded on every stored transaction as `threshold_used`,
so historical decisions remain interpretable after the setting changes. The value
0.5 is a default, not a finding.

---

## Original versus reproduced metrics

Three sets of numbers exist and should not be conflated.

| Source | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|
| Original project paper | 0.934 | 0.844 | 0.887 | 0.971 |
| Original `metrics.json` (shipped artifacts) | 0.9114 | 0.7579 | 0.8276 | 0.9543 |
| **This rebuild (`rf-v1`)** | **0.9114** | **0.7579** | **0.8276** | **0.9662** |

The rebuild reproduces the committed `metrics.json` exactly on precision, recall
and F1, with ROC-AUC slightly higher.

The paper's figures match neither. They appear to come from a different run than
the one that produced the shipped model — a different seed, split, or
configuration. **The paper should be corrected before submission.** Quote the
rebuild figures; they are reproducible with a single documented command.

---

## Known limitations

**One split, one seed.** No cross-validation and no repeated runs, so there are
no confidence intervals. With 95 fraud cases in the test set, a single
reclassification moves recall by 1.05 percentage points. Differences under
roughly 2% should be treated as noise.

**`Time` is approximated at inference.** Training uses the dataset's true `Time`
(seconds since the first transaction, spanning two days). The API accepts
hour-of-day, because that is what a person can supply, and maps it to
`hour × 3600` — the first day of the timeline. A 14:00 transaction is scored as
though it were 14:00 on day one. `Time` has low feature importance so the effect
is small, but it is a genuine train/serve mismatch and is documented rather than
hidden.

**Unsupplied PCA components default to 0.** Zero is the mean of a centred
component, so this is the least-informative choice available — but a request
supplying only `amount` and `hour` is being scored on 28 assumed-average
features, and its probability should be read accordingly.

**The data is from 2013.** Two days of European card transactions. Fraud
techniques have moved on considerably. Nothing here should be expected to
generalise to current payment traffic.

**No calibration check.** The forest's vote fraction is treated as a probability.
Random Forests are typically reasonably calibrated but not guaranteed to be; no
reliability diagram was produced.

---

## Retraining

```bash
# Full pipeline, both models, all artifacts
python -m ml.train --data data/creditcard.csv --version rf-v1

# Skip the logistic baseline
python -m ml.train --no-baseline

# Constrain memory on a small machine
TRAIN_N_JOBS=1 python -m ml.train

# Re-score existing artifacts without retraining
python -m ml.evaluate --data data/creditcard.csv --threshold 0.4
```

Bump `--version` when hyperparameters or data change. The version is written into
`model_metadata.json`, surfaced at `/api/v1/model-info`, and stamped on every
stored transaction, so any historical decision can be traced to the model that
made it.
