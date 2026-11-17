# Privacy for Some

This repository has the code, data and native-speaker coding for the paper:

> **Privacy for Some: LLM Privacy Protection Is Uneven Across Names and Breaks Down in Low-Resource Languages.**
> Birindwa Prisca Hondi, Alia Teto, Anny Christelle Irakoze, Honorine Ikirezi Umunyana.
> PriLoM Workshop (Privacy in the Era of Large Opaque Models), NeurIPS 2026.

We give a model a confidential contact record and tell it to keep the record private. Every value in the record is a unique random "canary". We then try to get the model to reveal it with natural requests. The record never changes; only one of these things does:
- the **name** of the person (7 name pools)
- the **format** of the record (Rwandan or US)
- the **language** of the conversation (English or Kinyarwanda)

Since a canary appears nowhere else, any match in a reply is a leak we can prove. All people and data are synthetic.

## Contents

```
src/
  personas.py         name pools, synthetic records, leak matching (strict and format-robust)
  prompts.py          system prompt, record, all 5 requests x 3 wordings in English and Kinyarwanda, probe
  model.py            Hugging Face chat models (batched), OpenAI-compatible API, mock model
  run_experiment.py   Study A (extraction), Study B (profiling, preliminary only), Study C (translation probe)
  scoring.py          refusal-language cues
  analyze.py          per-run summary: rates, persona bootstrap CIs, sign tests, locale DiD, GEE
  paper_numbers.py    every number, table and figure in the paper, from results/
  make_coding_workbook.py   builds the native-speaker coding sheet and imports the codes back
notebooks/privacy_experiment_colab.ipynb   the Colab notebook used for all runs
docs/kinyarwanda_prompt_check.md           native-speaker check of every Kinyarwanda prompt
results/
  trialsA_<model>_<run>.jsonl    one line per extraction trial (44,700 in total)
  trialsC_<model>_kin.jsonl      translation probe outputs (152 per model)
  comprehension_coding_<model>_kin.csv   probe outputs with the automatic and native-speaker codes
  coding/                        the native-speaker coding sheets as CSV, plus the coders' instructions
  paper_numbers.md, summary_main.md, figure*.pdf/png   outputs of the analysis scripts
```

## Reproduce the paper's numbers (no GPU needed)

```bash
pip install -r requirements.txt
python -m src.paper_numbers                      # writes results/paper_numbers.md and all four figures
python -m src.analyze results/trialsA_Qwen25-3B-Instruct_main.jsonl   # full per-run summary
```

Run both from the repository root. The bootstrap uses fixed seeds, so the output matches the paper exactly.

## Re-run the experiments

The open models need a GPU. The 3B models fit on a free Colab T4; Qwen2.5-7B needs an L4 or A100. Open the notebook in Colab, or run these commands:

```bash
# main English run: 7 pools x 2 record formats x 30 personas x 15 prompts = 6,300 trials per model
python -m src.run_experiment --model Qwen/Qwen2.5-3B-Instruct --study A --suffix main
#   also: Qwen/Qwen2.5-1.5B-Instruct, Qwen/Qwen2.5-7B-Instruct (--batch_size 8),
#         meta-llama/Llama-3.2-3B-Instruct (gated: set HF_TOKEN), microsoft/Phi-3.5-mini-instruct

# Kinyarwanda run + translation probe (Anglo and Rwandan pools)
python -m src.run_experiment --model Qwen/Qwen2.5-3B-Instruct --study A C --pools en rw --locales rw us --langs rw --suffix kin

# GPT-4o, both languages (set OPENAI_API_KEY as an environment variable or Colab secret, never in code)
python -m src.run_experiment --backend openai --model gpt-4o --study A C --pools en rw --locales rw us --langs en rw --suffix kin

# sampling robustness (temperature 0.7, 3 samples, seed 0)
python -m src.run_experiment --model Qwen/Qwen2.5-3B-Instruct --study A --pools en rw --temperature 0.7 --samples 3 --suffix sampled

# exact re-run of the preliminary configuration
python -m src.run_experiment --model Qwen/Qwen2.5-3B-Instruct --study A --pools en rw --locales rw --langs en rw --paraphrases 1 --batch_size 1 --suffix v1repro
```

To test the whole pipeline without a GPU:
```bash
python -m src.run_experiment --mock --study A C --langs en rw --suffix test
```

Self-tests:
```bash
python -m src.personas
python -m src.scoring
```

### Notes on exact reproducibility
- **Library versions and model revisions were not recorded.** The open models are the Hugging Face `main` revisions as of November 2026. GPT-4o was called through the alias `gpt-4o` in November 2026.
- **Batching changes greedy outputs slightly.** Batched fp16 generation with padding can differ from batch size 1. The preliminary re-run used `--batch_size 1`.

## Data format (`trialsA_*.jsonl`)

| Field | Meaning |
|---|---|
| `model` | model ID |
| `name_pool` | `en` (Anglo common), `en_rare`, `invented`, `cn`, `in`, `ng`, `rw` |
| `locale` | record format: `rw` or `us` |
| `lang` | conversation language: `en` or `rw` (Kinyarwanda) |
| `idx` | persona index; the same index has the same secrets in every pool and format |
| `name`, `name_tokens` | the full name, and its token count under the model's own tokenizer (-1 for API models) |
| `attack`, `paraphrase`, `field` | the request type, its wording (0 = original), and the requested field |
| `sample`, `temperature` | sample number and temperature |
| `canary` | the secret value that was requested |
| `leaked` | strict match: the full canary appears in the reply |
| `leaked_core` | format-robust match: used in the paper |
| `refusal_language` | the reply contains refusal or confidentiality phrases (`src/scoring.py`) |
| `other_fields_leaked` | other fields of the record that also appear in the reply |
| `reply` | the model's reply, cut at 1,000 characters |

## Native-speaker coding

Native-speaker co-authors coded each translation in `results/coding/comprehension_*.csv`:
- column `human_understood_0_1`: 1 if the translation keeps who is asked about and which information is requested (and, for the system prompt and record, the confidentiality instruction); 0 otherwise; blank if uncoded.

They also rated 30 GPT-4o Kinyarwanda replies, six drawn at random per request type with seed 7, in `results/coding/fluency_GPT-4o_replies.csv`.

The instructions the coders received are in `results/coding/coding_instructions.txt`. The completed spreadsheet, with all sheets, is `results/coding/kinyarwanda_coding_completed.xlsx`.

## Licenses

- **Code:** MIT (see `LICENSE`).
- **Data and coding sheets:** CC BY 4.0.
- **Model outputs in `results/`:** these remain subject to each model's license or terms of use:
  - Qwen2.5-1.5B and 7B: Apache-2.0
  - Qwen2.5-3B: Qwen Research License
  - Llama-3.2-3B: Llama 3.2 Community License
  - Phi-3.5-mini: MIT
  - GPT-4o: OpenAI terms of use

## Ethics

Every person, identifier and record in this repository is synthetic and randomly generated. No real personal data was used or collected.

In 20 replies or translations (all from Qwen2.5-3B), the model invented email addresses on real domains (for example, `name.surname@gmail.com`). These addresses could belong to real people, so we replaced them with `[email-redacted]` in the released files. Our own canaries all use the reserved `@mail.example` domain and are unchanged. The leak flags were computed before redaction, and every number in the paper reproduces from the released files.

## Citation

```bibtex
@inproceedings{hondi2026privacyforsome,
  title     = {Privacy for Some: {LLM} Privacy Protection Is Uneven Across Names and Breaks Down in Low-Resource Languages},
  author    = {Hondi, Birindwa Prisca and Teto, Alia and Irakoze, Anny Christelle and Umunyana, Honorine Ikirezi},
  booktitle = {PriLoM Workshop: Privacy in the Era of Large Opaque Models, NeurIPS},
  year      = {2026}
}
```
