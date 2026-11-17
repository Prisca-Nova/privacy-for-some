# Paper numbers (v2)

## English conversation: name pools vs Anglo (common), locales pooled

| Model | Anglo common | Rwandan | Rwandan − Anglo [95% CI], p, ↑/↓ | Other 5 pools (mean) − Anglo [95% CI], p |
|---|---|---|---|---|
| Qwen2.5-1.5B | 39.4% (355/900) | 45.8% (412/900) | +6.3 [+3.3, +9.1], p=0.00018, 24/4 | +2.8 [+0.7, +5.1], p=0.136 |
| Qwen2.5-3B | 18.9% (170/900) | 28.6% (257/900) | +9.7 [+7.2, +12.0], p=1.12e-07, 28/1 | +3.6 [+1.9, +5.3], p=0.00813 |
| Qwen2.5-7B | 20.6% (185/900) | 24.1% (217/900) | +3.6 [+2.6, +4.6], p=5.65e-06, 25/2 | +2.0 [+1.1, +2.8], p=0.00018 |
| Llama-3.2-3B | 36.4% (328/900) | 36.9% (332/900) | +0.4 [-2.1, +3.3], p=0.69, 11/14 | -0.7 [-2.5, +1.0], p=1 |
| Phi-3.5-mini | 10.7% (96/900) | 12.2% (110/900) | +1.6 [-1.0, +4.0], p=0.442, 16/11 | +1.4 [-0.8, +3.4], p=0.0614 |

## Original (v1) wording only vs new paraphrases: Anglo vs Rwandan leaks

| Model | p0 (v1 wording) | p1 | p2 |
|---|---|---|---|
| Qwen2.5-1.5B | 23/300 vs 59/300 | 272/300 vs 293/300 | 60/300 vs 60/300 |
| Qwen2.5-3B | 10/300 vs 91/300 | 79/300 vs 96/300 | 81/300 vs 70/300 |
| Qwen2.5-7B | 1/300 vs 35/300 | 124/300 vs 121/300 | 60/300 vs 61/300 |
| Llama-3.2-3B | 60/300 vs 25/300 | 176/300 vs 230/300 | 92/300 vs 77/300 |
| Phi-3.5-mini | 0/300 vs 0/300 | 65/300 vs 57/300 | 31/300 vs 53/300 |

## Sampling (Qwen2.5-3B, T=0.7, 3 samples)

Anglo 24.3% (656/2700), Rwandan 25.0% (674/2700); diff +0.7 [-1.1, +2.4], sign p=1
- p0: Anglo 114/900 vs Rwandan 126/900
- p1: Anglo 295/900 vs Rwandan 303/900
- p2: Anglo 247/900 vs Rwandan 245/900

## Language: English vs Kinyarwanda (Anglo + Rwandan pools, locales pooled)

| Model | English | Kinyarwanda | Study C native-speaker coded | Study C auto keyword check |
|---|---|---|---|---|
| Qwen2.5-3B | 23.7% (427/1800) | 67.5% (1215/1800) | 0/151 coded (1 uncoded; system prompt: 0, record: 0) | 59/152 (system: False, record: False) |
| Phi-3.5-mini | 11.4% (206/1800) | 90.6% (1631/1800) | 1/152 coded (0 uncoded; system prompt: 0, record: 0) | 57/152 (system: False, record: False) |
| GPT-4o | 0.0% (0/1800) | 0.0% (0/1800) | 102/151 coded (1 uncoded; system prompt: 1, record: 1) | 152/152 (system: True, record: True) |

## v1 reproduction (Qwen2.5-3B, v1 settings)

- en: Anglo 2/150, Rwandan 46/150
- rw: Anglo 107/150, Rwandan 109/150
