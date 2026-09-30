# Token benchmark

Jev for Codex 0.1.6 was calibrated on one task set and evaluated on a separate holdout. The public result is deliberately scoped to this experiment:

> In a 22-task holdout, calibrated Jev routing used about 23% fewer total Codex execution tokens than `gpt-5.6-sol/medium`, with 22/22 exact-quality passes in both arms.

## Design

- Control: `gpt-5.6-sol/medium`.
- Treatment: a fresh live Jev decision for each task, using the calibrated router.
- Holdout: 22 objective repository-analysis tasks never used for calibration—8 LOW, 8 MEDIUM, and 6 HIGH.
- Executions: 44 unique, counterbalanced runs; each task ran once per arm.
- Quality: exact deterministic fields, scored before token analysis. No holdout answer required manual adjudication.
- Primary metric: paired geometric change in total execution tokens reported by Codex (`input_tokens + output_tokens`).
- Decision gate: exact quality in every run, point reduction of at least 15%, and a paired bootstrap 95% interval excluding zero.

## Results

| Metric | Control | Calibrated Jev | Difference |
|---|---:|---:|---:|
| Exact-quality passes | 22/22 | 22/22 | Equal |
| Total execution tokens | 2,353,254 | 1,645,344 | -30.082% aggregate |
| Paired geometric total-token change | — | — | **-22.978%** |
| Paired bootstrap 95% interval | — | — | -32.893% to -12.402% |
| Output tokens | 17,945 | 11,468 | -27.763% paired geometric |
| Uncached input tokens | 382,541 | 448,596 | +21.750% paired geometric |

Both predeclared gates passed. Uncached input was noisy and its interval crossed zero (-16.228% to +75.167%), so no uncached-input savings claim is supported.

### By task tier

| Tier | Pairs | Paired geometric total-token change | Bootstrap 95% interval |
|---|---:|---:|---:|
| LOW | 8 | -5.934% | -6.141% to -5.777% |
| MEDIUM | 8 | -35.616% | -49.966% to -17.513% |
| HIGH | 6 | -25.071% | -39.342% to -1.252% |

### Treatment routes

| Model / effort | Runs |
|---|---:|
| `gpt-5.6-luna/low` | 8 |
| `gpt-5.6-terra/medium` | 2 |
| `gpt-5.6-sol/medium` (inheritance) | 4 |
| `gpt-6-sol/medium` | 8 |

Astra was not selected: none of the holdout tasks produced evidence that Sol was insufficient.

## Integrity and reproducibility

- Candidate commit: `40ca1b7e8f79a2ac5d767fcb39e72348c3d00fee`.
- Codex version: `codex-cli 0.158.0-alpha.2.1`.
- Seed: `20260930`.
- Protocol SHA-256: `7b3a77c85dbec4c9c80351225070bc18f748c5703b18ac91151165cb0350c915`.
- Schedule SHA-256: `f857591a599b9d6ae9ce5664ee72fe1de3e088fed2124b8467c9c16ec0bd6661`.
- Router SHA-256: `d557d3209860eaf06e032a3fcbabd353512260192be78820850b8bc0e4cceceb`.
- Raw reconciliation: 44/44 streams had exactly one terminal event, no error event, and usage matching the recorded result.

The compact public artifact is [benchmarks/holdout-2026-09-30.json](../benchmarks/holdout-2026-09-30.json).

## Limitations

This is a repository-analysis workload on one plugin, one Codex build, and one control. It does not guarantee the same reduction for every repository, prompt, cache state, model catalog, or future model family. The benchmark supports a scoped total-execution-token claim; it does not establish lower uncached input or lower monetary cost in every environment.
