# Cosine clustering threshold

The default cosine-similarity threshold is **0.91** for the configured
`intfloat/multilingual-e5-base` embeddings.

## How it was selected

`evaluation/cluster_threshold.py` contains a reproducible Vietnamese finance
benchmark with 12 concrete events, three independently phrased headlines per
event, and 12 hard negatives. The hard negatives deliberately reuse the same
company or topic while describing another event; unrelated random text would
overstate clustering quality.

Each headline is held out in turn and compared with the centroid of the other
two headlines from its event. It is also compared with all other event
centroids. This produces 36 positive and 408 negative centroid comparisons.
The script evaluates thresholds from 0.90 through 0.99 in 0.01 increments and
selects the threshold with the highest F1 score. Precision and the higher
threshold break ties.

Measured on 2026-07-19 with the configured model:

| Threshold | Precision | Recall | Specificity | F1 | False merges | False splits |
|---:|---:|---:|---:|---:|---:|---:|
| 0.90 | 0.878 | 1.000 | 0.988 | 0.935 | 5 | 0 |
| **0.91** | **0.973** | **1.000** | **0.998** | **0.986** | **1** | **0** |
| 0.92 | 0.972 | 0.972 | 0.998 | 0.972 | 1 | 1 |
| 0.93 | 1.000 | 0.917 | 1.000 | 0.957 | 0 | 3 |
| 0.94 | 1.000 | 0.778 | 1.000 | 0.875 | 0 | 8 |
| 0.95 | 1.000 | 0.750 | 1.000 | 0.857 | 0 | 9 |

The observed positive centroid range was 0.9145–0.9875; the negative range was
0.7544–0.9203. Because those ranges overlap, no threshold can be claimed to be
universally perfect. The selected value is evidence-backed for this model and
benchmark, and should be recalibrated when the embedding model or a sufficiently
large human-labeled production dataset changes.

Reproduce the measurement from the repository root:

```shell
python -m evaluation.cluster_threshold
```

Production can override the default with the
`CLUSTER_SIMILARITY_THRESHOLD` environment variable.

## Centroid update proof

If a cluster contains `n` embeddings and its stored centroid is
`μₙ = (x₁ + ... + xₙ) / n`, adding embedding `x` gives:

```text
μₙ₊₁ = μₙ + (x - μₙ) / (n + 1)
     = (nμₙ + x) / (n + 1)
     = (x₁ + ... + xₙ + x) / (n + 1)
```

Therefore the implementation only needs the stored centroid and article count;
it does not need to retain every historical embedding. The unit suite also
checks the incremental result against `numpy.mean` over the full input.
