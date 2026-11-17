"""Run the PII experiments for one model and write per-trial results (v2).

Studies
  A (leak)          : plant a confidential contact card, try to extract one canary field.
                      Grid: name pool x record locale x conversation language x attack x
                      paraphrase x persona (x sample if --samples > 1).
  B (profile)       : name + city only, ask the model to guess finances/education/job.
  C (comprehension) : ask the model to translate each Kinyarwanda prompt into English, so the
                      Kinyarwanda arm can be conditioned on whether the model understood it.

Examples
  # main v2 run (English, all name-control pools, both record locales, 3 paraphrases)
  python -m src.run_experiment --model Qwen/Qwen2.5-3B-Instruct --study A
  # exact v1 reproduction (original grid, batch size 1)
  python -m src.run_experiment --model Qwen/Qwen2.5-3B-Instruct --study A --pools en rw \
      --locales rw --langs en rw --paraphrases 1 --batch_size 1 --suffix v1repro
  # Kinyarwanda arm + comprehension check on a model that supports Kinyarwanda
  python -m src.run_experiment --backend openai --model gpt-4o --study A C --pools en rw \
      --langs en rw
  # pipeline test without GPU
  python -m src.run_experiment --mock --study A B C
"""
from __future__ import annotations
import argparse
import csv
import json
import os

from .personas import NAME_POOLS, LOCALES, make_personas, canary_present, core_present, \
    leaked_other_fields
from .prompts import ATTACKS, SYSTEM, SETUP, build_leak_messages, build_profile_messages, \
    build_comprehension_messages, COMPREHENSION_KEYWORDS
from .scoring import is_refusal, is_leak_refusal, attribute_hits


def _batched(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _generate(model, jobs, batch_size, mock_fn=None, desc=""):
    """jobs: list of (meta, messages). Returns list of (meta, reply)."""
    out = []
    total = len(jobs)
    for bi, chunk in enumerate(_batched(jobs, batch_size)):
        if mock_fn is not None:
            replies = [mock_fn(meta) for meta, _ in chunk]
        else:
            replies = model.chat_batch([m for _, m in chunk])
        out += list(zip([meta for meta, _ in chunk], replies))
        done = min((bi + 1) * batch_size, total)
        if bi % 20 == 0 or done == total:
            print(f"  {desc} {done}/{total}", flush=True)
    return out


# ------------------------------------------------------------------------------- Study A
def run_leak(model, model_name, args):
    jobs = []
    for pool in args.pools:
        for locale in args.locales:
            personas = make_personas(args.n, pool, locale, seed=args.seed)
            for lang in args.langs:
                for p in personas:
                    for label, field, texts in ATTACKS:
                        for k, atk in enumerate(texts[lang][:args.paraphrases]):
                            for s in range(args.samples):
                                meta = {"pool": pool, "locale": locale, "lang": lang, "p": p,
                                        "label": label, "field": field, "para": k, "sample": s}
                                jobs.append((meta, build_leak_messages(lang, p, atk)))
    print(f"[A/leak] {len(jobs)} trials")
    tok_cache = {}
    rows = []
    mock_fn = (lambda m: model.reply_leak(m["pool"], m["locale"], m["lang"],
                                          m["p"][m["field"]])) if args.mock else None
    for meta, reply in _generate(model, jobs, args.batch_size, mock_fn, "A"):
        p, field = meta["p"], meta["field"]
        if p["name"] not in tok_cache:
            tok_cache[p["name"]] = model.n_tokens(p["name"])
        strict = canary_present(reply, p[field])
        core = core_present(reply, field, p["core"][field])
        rows.append({
            "study": "A", "model": model_name, "name_pool": meta["pool"],
            "locale": meta["locale"], "lang": meta["lang"], "idx": p["idx"], "name": p["name"],
            "name_tokens": tok_cache[p["name"]], "attack": meta["label"],
            "paraphrase": meta["para"], "sample": meta["sample"], "field": field,
            "canary": p[field], "leaked": bool(strict), "leaked_core": bool(strict or core),
            "refusal_language": bool(is_leak_refusal(reply)),
            "other_fields_leaked": leaked_other_fields(reply, p, field),
            "temperature": args.temperature, "reply": reply[:1000],
        })
    return rows


# ------------------------------------------------------------------------------- Study B
def run_profile(model, model_name, args):
    jobs = []
    for pool in args.pools:
        for p in make_personas(args.n, pool, "rw", seed=args.seed):
            for lang in args.langs:
                jobs.append(({"pool": pool, "lang": lang, "p": p},
                             build_profile_messages(lang, p["name"])))
    mock_fn = (lambda m: model.reply_profile(m["pool"], m["lang"])) if args.mock else None
    rows = []
    for meta, reply in _generate(model, jobs, args.batch_size, mock_fn, "B"):
        p = meta["p"]
        rows.append({"study": "B", "model": model_name, "name_pool": meta["pool"],
                     "locale": "na", "lang": meta["lang"], "idx": p["idx"], "name": p["name"],
                     "refused": bool(is_refusal(reply)), "attribute_hits": attribute_hits(reply),
                     "reply": reply[:1000]})
    return rows


# ------------------------------------------------------------------------------- Study C
def run_comprehension(model, model_name, args):
    """Translate every Kinyarwanda prompt (system, card, each attack x 5 names per pool)."""
    jobs = [({"item": "system", "field": "system", "pool": "-", "name": "-"},
             build_comprehension_messages(SYSTEM["rw"]))]
    p0 = make_personas(1, "rw", "rw")[0]
    jobs.append(({"item": "setup", "field": "system", "pool": "rw", "name": p0["name"]},
                 build_comprehension_messages(SETUP["rw"].format(**p0))))
    for pool in [q for q in args.pools if q in ("en", "rw")] or ["en", "rw"]:
        for p in make_personas(5, pool, "rw"):
            for label, field, texts in ATTACKS:
                for k, atk in enumerate(texts["rw"]):
                    jobs.append(({"item": f"{label}#{k}", "field": field, "pool": pool,
                                  "name": p["name"]},
                                 build_comprehension_messages(atk.format(name=p["name"]))))
    mock_fn = (lambda m: model.reply_translate(m["field"])) if args.mock else None
    rows = []
    for meta, reply in _generate(model, jobs, args.batch_size, mock_fn, "C"):
        kws = COMPREHENSION_KEYWORDS[meta["field"]]
        low = reply.lower()
        rows.append({"study": "C", "model": model_name, "item": meta["item"],
                     "field": meta["field"], "name_pool": meta["pool"], "name": meta["name"],
                     "auto_understood": any(k in low for k in kws), "translation": reply[:600]})
    return rows


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--backend", choices=["hf", "openai"], default="hf")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--study", nargs="+", choices=["A", "B", "C"], default=["A"])
    ap.add_argument("--n", type=int, default=30, help="personas per pool")
    ap.add_argument("--pools", nargs="+", default=list(NAME_POOLS), choices=list(NAME_POOLS))
    ap.add_argument("--locales", nargs="+", default=list(LOCALES), choices=list(LOCALES))
    ap.add_argument("--langs", nargs="+", default=["en"], choices=["en", "rw"])
    ap.add_argument("--paraphrases", type=int, default=3, help="paraphrases per attack (1=v1)")
    ap.add_argument("--samples", type=int, default=1, help="samples per prompt (needs temp>0)")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--batch_size", type=int, default=16)
    ap.add_argument("--max_new_tokens", type=int, default=220)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--suffix", default="", help="appended to output file names")
    args = ap.parse_args()
    if args.samples > 1 and args.temperature == 0:
        ap.error("--samples > 1 requires --temperature > 0")

    os.makedirs("results", exist_ok=True)
    if args.mock:
        from .model import MockModel
        model, model_name = MockModel(seed=args.seed), "MOCK"
    elif args.backend == "openai":
        from .model import OpenAICompatModel
        model = OpenAICompatModel(args.model, args.max_new_tokens, args.temperature, args.seed)
        model_name = args.model
    else:
        import torch
        torch.manual_seed(args.seed)
        from .model import HFChatModel
        model = HFChatModel(args.model, max_new_tokens=args.max_new_tokens,
                            temperature=args.temperature, seed=args.seed)
        model_name = args.model
    tag = model_name.split("/")[-1].replace(".", "") + (f"_{args.suffix}" if args.suffix else "")

    if "A" in args.study:
        rows = run_leak(model, model_name, args)
        out = f"results/trialsA_{tag}.jsonl"
        _write_jsonl(out, rows)
        for lang in args.langs:
            sub = [r for r in rows if r["lang"] == lang]
            ns, nc = sum(r["leaked"] for r in sub), sum(r["leaked_core"] for r in sub)
            print(f"[A/leak/{lang}] {len(sub)} trials: strict {ns} ({ns/len(sub):.1%}), "
                  f"core {nc} ({nc/len(sub):.1%})")
        print(f"  -> {out}")

    if "B" in args.study:
        rows = run_profile(model, model_name, args)
        out = f"results/trialsB_{tag}.jsonl"
        _write_jsonl(out, rows)
        csv_path = f"results/study_b_coding_{tag}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            w = csv.writer(cf)
            w.writerow(["model", "name_pool", "lang", "idx", "name", "auto_refused",
                        "auto_attr_hits", "human_refused_0_1", "human_specificity_0_3", "reply"])
            for r in rows:
                w.writerow([r["model"], r["name_pool"], r["lang"], r["idx"], r["name"],
                            int(r["refused"]), r["attribute_hits"], "", "", r["reply"]])
        print(f"[B/profile] {len(rows)} trials -> {out} ; coding sheet -> {csv_path}")

    if "C" in args.study:
        rows = run_comprehension(model, model_name, args)
        out = f"results/trialsC_{tag}.jsonl"
        _write_jsonl(out, rows)
        csv_path = f"results/comprehension_coding_{tag}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            w = csv.writer(cf)
            w.writerow(["model", "item", "field", "name_pool", "name", "auto_understood",
                        "human_understood_0_1", "translation"])
            for r in rows:
                w.writerow([r["model"], r["item"], r["field"], r["name_pool"], r["name"],
                            int(r["auto_understood"]), "", r["translation"]])
        nu = sum(r["auto_understood"] for r in rows)
        print(f"[C/comprehension] {nu}/{len(rows)} auto-judged understood -> {out} ; "
              f"native-speaker coding sheet -> {csv_path}")


if __name__ == "__main__":
    main()
