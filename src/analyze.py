"""Aggregate trial results into rates, contrasts, persona-level tests, breakdowns, figures (v2).

Reads v1 and v2 trial files (v1 rows get locale='rw', paraphrase=0, leaked_core=leaked).

Study A, per model and conversation language:
  1. Leak rate per (name pool x record locale): Wilson CI (trial level) and a persona-cluster
     bootstrap CI (personas resampled, all their attacks kept together).
  2. Each pool vs the common-Anglo reference, same locale: trial-level McNemar exact test AND a
     persona-level test (per-persona leak proportions, exact sign test + cluster bootstrap CI).
     The persona-level test is the primary one: the 5 attacks per persona are not independent.
  3. Record-locale effect within each pool (Rwandan vs US phone/address) and the
     name x locale interaction (difference-in-differences) -> tests the "+250 mismatch" story.
  4. Per-name, per-attack x paraphrase breakdowns; refuse-but-echo share among leaks;
     name token count as a familiarity covariate (+ optional GEE logistic regression).
  5. Kinyarwanda arm: rates overall AND restricted to prompts the model understood (Study C;
     uses native-speaker coding from results/comprehension_coding_*.csv when filled in).
Study B: refusal/engagement per pool x language (kept for the appendix).

Outputs: results/summary.md, results/summary.json, results/figure_leak_v2.png
Usage:   python -m src.analyze                        (all results/trials*_*.jsonl)
         python -m src.analyze --metric strict         (default: core = format-robust)
"""
from __future__ import annotations
import argparse
import csv
import glob
import json
import math
import os
import random
from collections import defaultdict

from .personas import POOL_LABEL
from .scoring import is_leak_refusal

REF_POOL = "en"
POOL_ORDER = ["en", "en_rare", "invented", "cn", "in", "ng", "rw"]
BOOT = 5000


# ------------------------------------------------------------------------------ stats utils
def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, max(0.0, (c - half) / d), min(1.0, (c + half) / d))


def binom_two_sided(b, c):
    """Exact two-sided sign/McNemar test on discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def cluster_boot_mean(clusters, seed=0):
    """clusters: list of per-persona values. Returns (mean, lo, hi) by bootstrap over personas."""
    if not clusters:
        return (float("nan"),) * 3
    r = random.Random(seed)
    n = len(clusters)
    m = sum(clusters) / n
    bs = sorted(sum(clusters[r.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    return (m, bs[int(0.025 * BOOT)], bs[int(0.975 * BOOT)])


def pct(x):
    return "n/a" if x != x else f"{100 * x:.1f}%"


def pval(p):
    return "<0.001" if p < 0.001 else f"{p:.3f}"


# ------------------------------------------------------------------------------ loading
def load(paths):
    rows = []
    for pat in paths:
        for path in sorted(glob.glob(pat)):
            with open(path, encoding="utf-8") as f:
                rows += [json.loads(line) for line in f if line.strip()]
    for r in rows:  # v1 back-compat
        r.setdefault("locale", "rw")
        r.setdefault("paraphrase", 0)
        r.setdefault("sample", 0)
        if r.get("study") == "A":
            r.setdefault("leaked_core", r["leaked"])
            r.setdefault("name_tokens", -1)
            if "refusal_language" not in r:
                r["refusal_language"] = bool(is_leak_refusal(r.get("reply", "")))
    return rows


def trial_key(r):
    return (r["idx"], r["attack"], r["paraphrase"], r["sample"])


# ------------------------------------------------------------------------------ Study A
def by_persona(rows, outcome):
    d = defaultdict(list)
    for r in rows:
        d[r["idx"]].append(outcome(r))
    return {k: sum(v) / len(v) for k, v in d.items()}


def cell_stats(rows, outcome):
    k, n = sum(outcome(r) for r in rows), len(rows)
    p, lo, hi = wilson(k, n)
    _, clo, chi = cluster_boot_mean(list(by_persona(rows, outcome).values()))
    return {"k": k, "n": n, "rate": p, "wilson": [lo, hi], "cluster_ci": [clo, chi]}


def paired_contrast(rows_a, rows_b, outcome):
    """b - a. Trial-level McNemar + persona-level sign test and cluster bootstrap CI."""
    A = {trial_key(r): outcome(r) for r in rows_a}
    B = {trial_key(r): outcome(r) for r in rows_b}
    keys = A.keys() & B.keys()
    if not keys:
        return None
    b = sum(1 for k in keys if not A[k] and B[k])
    c = sum(1 for k in keys if A[k] and not B[k])
    pa = by_persona([r for r in rows_a if trial_key(r) in keys], outcome)
    pb = by_persona([r for r in rows_b if trial_key(r) in keys], outcome)
    diffs = [pb[i] - pa[i] for i in pa.keys() & pb.keys()]
    pos, neg = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    m, lo, hi = cluster_boot_mean(diffs)
    return {"diff": m, "ci": [lo, hi], "p_persona_sign": binom_two_sided(pos, neg),
            "personas_up_down": [pos, neg], "p_trial_mcnemar": binom_two_sided(b, c),
            "discordant_trials": [b, c], "n_trials": len(keys), "n_personas": len(diffs)}


def did_contrast(rows, pool, outcome):
    """Name x locale interaction: (pool-ref | rw locale) - (pool-ref | us locale), persona level."""
    def persona_gap(locale):
        a = by_persona([r for r in rows if r["name_pool"] == REF_POOL and r["locale"] == locale],
                       outcome)
        b = by_persona([r for r in rows if r["name_pool"] == pool and r["locale"] == locale],
                       outcome)
        return {i: b[i] - a[i] for i in a.keys() & b.keys()}
    g_rw, g_us = persona_gap("rw"), persona_gap("us")
    ids = g_rw.keys() & g_us.keys()
    if not ids:
        return None
    m, lo, hi = cluster_boot_mean([g_rw[i] - g_us[i] for i in ids])
    return {"did": m, "ci": [lo, hi], "n_personas": len(ids)}


def comprehension_map(model):
    """(attack, paraphrase) -> understood? Prefer filled-in human coding, else auto score."""
    tag = model.split("/")[-1].replace(".", "")
    votes = defaultdict(list)
    for path in glob.glob(f"results/comprehension_coding_{tag}*.csv"):
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if "#" not in row["item"]:
                    continue
                h = row.get("human_understood_0_1", "").strip()
                if h in ("0", "1"):
                    votes[row["item"]].append(int(h))
    source = "human"
    if not votes:
        source = "auto"
        for path in glob.glob(f"results/trialsC_{tag}*.jsonl"):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    if "#" in r["item"]:
                        votes[r["item"]].append(int(r["auto_understood"]))
    if not votes:
        return None, None
    out = {}
    for item, v in votes.items():
        label, k = item.split("#")
        out[(label, int(k))] = sum(v) / len(v) >= 0.5
    return out, source


def analyze_A(rows, outcome, md, model):
    res = {}
    pools = [p for p in POOL_ORDER if any(r["name_pool"] == p for r in rows)]
    pools += sorted({r["name_pool"] for r in rows} - set(pools))
    locales = [l for l in ("rw", "us") if any(r["locale"] == l for r in rows)]
    for lang in [l for l in ("en", "rw") if any(r["lang"] == l for r in rows)]:
        L = [r for r in rows if r["lang"] == lang]
        lres = res.setdefault(lang, {})
        md.append(f"\n### Conversation language: {'English' if lang == 'en' else 'Kinyarwanda'}\n")
        if lang == "rw":
            md.append("> Kinyarwanda rates are only interpretable on prompts the model understood "
                      "(see the comprehension-restricted table below).\n")

        # 1. cells
        md.append("| Name pool | Record locale | Leak rate | Wilson 95% CI | "
                  "Persona-cluster 95% CI | k/n | mean name tokens |")
        md.append("|---|---|---|---|---|---|---|")
        cells = {}
        for pool in pools:
            for loc in locales:
                sub = [r for r in L if r["name_pool"] == pool and r["locale"] == loc]
                if not sub:
                    continue
                c = cell_stats(sub, outcome)
                toks = [r["name_tokens"] for r in sub if r["name_tokens"] >= 0]
                c["name_tokens"] = sum(toks) / len(toks) if toks else None
                cells[f"{pool}|{loc}"] = c
                tok_txt = "" if c["name_tokens"] is None else f"{c['name_tokens']:.1f}"
                md.append(f"| {POOL_LABEL.get(pool, pool)} | {loc} | {pct(c['rate'])} | "
                          f"[{pct(c['wilson'][0])}, {pct(c['wilson'][1])}] | "
                          f"[{pct(c['cluster_ci'][0])}, {pct(c['cluster_ci'][1])}] | "
                          f"{c['k']}/{c['n']} | {tok_txt} |")
        lres["cells"] = cells

        # 2. pool vs reference
        md.append(f"\n**Each name pool vs {POOL_LABEL[REF_POOL]} (same record locale; "
                  "difference = pool − reference; persona-level test is primary)**\n")
        md.append("| Pool | Locale | Difference | 95% CI (persona bootstrap) | "
                  "p (persona sign test) | personas ↑/↓ | p (trial McNemar) |")
        md.append("|---|---|---|---|---|---|---|")
        contrasts = {}
        for loc in locales:
            ref = [r for r in L if r["name_pool"] == REF_POOL and r["locale"] == loc]
            for pool in pools:
                if pool == REF_POOL:
                    continue
                c = paired_contrast(ref, [r for r in L if r["name_pool"] == pool
                                          and r["locale"] == loc], outcome)
                if c is None:
                    continue
                contrasts[f"{pool}|{loc}"] = c
                md.append(f"| {POOL_LABEL.get(pool, pool)} | {loc} | {c['diff']*100:+.1f} pts | "
                          f"[{c['ci'][0]*100:+.1f}, {c['ci'][1]*100:+.1f}] | "
                          f"{pval(c['p_persona_sign'])} | {c['personas_up_down'][0]}/"
                          f"{c['personas_up_down'][1]} | {pval(c['p_trial_mcnemar'])} |")
        lres["vs_reference"] = contrasts

        # 3. locale effect + interaction
        if len(locales) == 2:
            md.append("\n**Record-locale effect (US record − Rwandan record, same names) and "
                      "name × locale interaction**\n")
            md.append("If the v1 gap were driven by a name/record *mismatch*, Anglo names would "
                      "leak more with Rwandan records and Rwandan names would leak more with US "
                      "records, and the interaction would be large.\n")
            md.append("| Pool | Locale effect | 95% CI | p (persona) | "
                      "Gap vs Anglo: rw-locale minus us-locale (DiD) | 95% CI |")
            md.append("|---|---|---|---|---|---|")
            loc_res = {}
            for pool in pools:
                c = paired_contrast(
                    [r for r in L if r["name_pool"] == pool and r["locale"] == "rw"],
                    [r for r in L if r["name_pool"] == pool and r["locale"] == "us"], outcome)
                d = did_contrast(L, pool, outcome) if pool != REF_POOL else None
                if c is None:
                    continue
                loc_res[pool] = {"locale_effect": c, "did": d}
                dtxt = ("—", "—") if d is None else (f"{d['did']*100:+.1f} pts",
                                                     f"[{d['ci'][0]*100:+.1f}, {d['ci'][1]*100:+.1f}]")
                md.append(f"| {POOL_LABEL.get(pool, pool)} | {c['diff']*100:+.1f} pts | "
                          f"[{c['ci'][0]*100:+.1f}, {c['ci'][1]*100:+.1f}] | "
                          f"{pval(c['p_persona_sign'])} | {dtxt[0]} | {dtxt[1]} |")
            lres["locale"] = loc_res

        # 4a. attack x paraphrase
        attacks = sorted({r["attack"] for r in L})
        paras = sorted({r["paraphrase"] for r in L})
        md.append("\n**Leaks by attack × paraphrase (k/n), per pool, all locales pooled**\n")
        md.append("| Pool | " + " | ".join(f"{a} p{k}" for a in attacks for k in paras) + " |")
        md.append("|---|" + "---|" * (len(attacks) * len(paras)))
        for pool in pools:
            cells_ap = []
            for a in attacks:
                for k in paras:
                    s = [r for r in L if r["name_pool"] == pool and r["attack"] == a
                         and r["paraphrase"] == k]
                    cells_ap.append(f"{sum(outcome(r) for r in s)}/{len(s)}" if s else "—")
            md.append(f"| {POOL_LABEL.get(pool, pool)} | " + " | ".join(cells_ap) + " |")

        # 4b. refuse-but-echo + whole-card dumps
        leaks = [r for r in L if outcome(r)]
        if leaks:
            rbe = sum(r["refusal_language"] for r in leaks)
            dump = sum(bool(r.get("other_fields_leaked")) for r in leaks)
            md.append(f"\n**Leak character:** {rbe}/{len(leaks)} leaks "
                      f"({pct(rbe/len(leaks))}) contain refusal language (refuse-but-echo); "
                      f"{dump}/{len(leaks)} also disclose non-requested fields. "
                      "Strict vs format-robust matching: "
                      f"{sum(r['leaked'] for r in L)} vs {sum(r['leaked_core'] for r in L)} "
                      "leaks.\n")
            lres["refuse_but_echo"] = [rbe, len(leaks)]

        # 4c. per-name
        md.append("\n<details><summary>Per-name leak counts</summary>\n")
        md.append("| Pool | Name | leaks/trials |")
        md.append("|---|---|---|")
        per_name = {}
        for pool in pools:
            names = defaultdict(lambda: [0, 0])
            for r in L:
                if r["name_pool"] == pool:
                    names[r["name"]][0] += outcome(r)
                    names[r["name"]][1] += 1
            for nm, (k, n) in sorted(names.items(), key=lambda x: -x[1][0]):
                md.append(f"| {POOL_LABEL.get(pool, pool)} | {nm} | {k}/{n} |")
                per_name[f"{pool}|{nm}"] = [k, n]
            tot = sum(k for k, _ in names.values())
            if tot:
                top = sorted((k for k, _ in names.values()), reverse=True)
                share5 = sum(top[:5]) / tot
                md.append(f"| {POOL_LABEL.get(pool, pool)} | *top-5 names' share of leaks* | "
                          f"{pct(share5)} |")
        md.append("\n</details>\n")
        lres["per_name"] = per_name

        # 4d. GEE logistic regression with name tokens (optional)
        try:
            import pandas as pd
            import statsmodels.api as sm
            import statsmodels.formula.api as smf
            df = pd.DataFrame([{"y": int(outcome(r)), "pool": r["name_pool"],
                                "locale": r["locale"],
                                "prompt": f"{r['attack']}#{r.get('paraphrase', 0)}",
                                "tok": r["name_tokens"], "persona": r["idx"]} for r in L])
            # Prompts that never vary (always 0 or always 1 leaks for this model) carry no
            # information about pools and cause separation (huge coefs / nan SEs): drop them.
            pm = df.groupby("prompt").y.mean()
            keep = pm[(pm > 0) & (pm < 1)].index
            dropped = sorted(set(pm.index) - set(keep))
            df = df[df.prompt.isin(keep)]
            if len(keep) >= 2 and df.y.sum() > 5 and df.y.sum() < len(df) - 5:
                note = (f" Dropped {len(dropped)} prompt(s) with no variation: "
                        f"{', '.join(dropped)}." if dropped else "")
                specs = [("Pool effects (prompt fixed effects)",
                          "y ~ C(pool, Treatment('en')) + C(locale) + C(prompt)")]
                if (df.tok >= 0).all():
                    specs.append(("Pool effects + name token count (note: token count is "
                                  "largely collinear with pool)",
                                  "y ~ C(pool, Treatment('en')) + C(locale) + C(prompt) + tok"))
                md.append("\n**GEE logistic regression** (clustered by persona index; "
                          f"log-odds vs Anglo-common).{note}\n")
                for title, formula in specs:
                    fit = smf.gee(formula, groups="persona", data=df,
                                  family=sm.families.Binomial()).fit()
                    tab = fit.summary().tables[1].as_text().splitlines()
                    tab = [t for t in tab if "C(prompt)" not in t and "Intercept" not in t]
                    md.append(f"\n*{title}*\n\n```\n" + "\n".join(tab) + "\n```\n")
        except Exception as e:  # statsmodels missing or model did not converge
            md.append(f"\n*(GEE regression skipped: {type(e).__name__})*\n")

        # 5. Kinyarwanda restricted to understood prompts
        if lang == "rw":
            cmap, source = comprehension_map(model)
            if cmap is None:
                md.append("\n*No comprehension data (run `--study C`) — Kinyarwanda rates above "
                          "cannot be read as protection.*\n")
            else:
                ok = [r for r in L if cmap.get((r["attack"], r["paraphrase"]), False)]
                understood = sorted(f"{a}#{k}" for (a, k), v in cmap.items() if v)
                md.append(f"\n**Kinyarwanda, restricted to prompts the model understood** "
                          f"({source} coding; understood: {', '.join(understood) or 'none'})\n")
                md.append("| Name pool | Record locale | Leak rate | k/n |")
                md.append("|---|---|---|---|")
                for pool in pools:
                    for loc in locales:
                        s = [r for r in ok if r["name_pool"] == pool and r["locale"] == loc]
                        if s:
                            k = sum(outcome(r) for r in s)
                            md.append(f"| {POOL_LABEL.get(pool, pool)} | {loc} | "
                                      f"{pct(k/len(s))} | {k}/{len(s)} |")
                lres["comprehension_source"] = source
    return res


# ------------------------------------------------------------------------------ Study B
def analyze_B(rows, md):
    md.append("| Name pool | Language | Engagement rate (not refused) | k/n | mean domains |")
    md.append("|---|---|---|---|---|")
    out = {}
    for pool in POOL_ORDER:
        for lang in ("en", "rw"):
            s = [r for r in rows if r["name_pool"] == pool and r["lang"] == lang]
            if not s:
                continue
            k = sum(not r["refused"] for r in s)
            dom = sum(r["attribute_hits"] for r in s) / len(s)
            out[f"{pool}|{lang}"] = {"k": k, "n": len(s), "domains": dom}
            md.append(f"| {POOL_LABEL.get(pool, pool)} | {lang} | {pct(k/len(s))} | "
                      f"{k}/{len(s)} | {dom:.2f} |")
    md.append("\n*Automatic keyword scoring; report only with human coding (appendix).*\n")
    return out


# ------------------------------------------------------------------------------ figure
def make_figure(rowsA, outcome, path="results/figure_leak_v2.png"):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print("matplotlib unavailable, skipping figure:", e)
        return
    E = [r for r in rowsA if r["lang"] == "en"]
    models = sorted({r["model"] for r in E})
    if not models:
        return
    locales = [l for l in ("rw", "us") if any(r["locale"] == l for r in E)]
    colors = {"rw": "#3182bd", "us": "#e6550d"}
    fig, axes = plt.subplots(1, len(models), figsize=(5.2 * len(models), 3.8), squeeze=False,
                             sharey=True)
    for ax, m in zip(axes[0], models):
        M = [r for r in E if r["model"] == m]
        pools = [p for p in POOL_ORDER if any(r["name_pool"] == p for r in M)]
        w = 0.8 / len(locales)
        for j, loc in enumerate(locales):
            xs, ys, lo, hi = [], [], [], []
            for i, pool in enumerate(pools):
                s = [r for r in M if r["name_pool"] == pool and r["locale"] == loc]
                if not s:
                    continue
                c = cell_stats(s, outcome)
                xs.append(i + (j - (len(locales) - 1) / 2) * w)
                ys.append(c["rate"])
                lo.append(c["rate"] - c["cluster_ci"][0])
                hi.append(c["cluster_ci"][1] - c["rate"])
            ax.bar(xs, ys, width=w, yerr=[lo, hi], capsize=3, color=colors[loc],
                   edgecolor="#333", linewidth=0.5,
                   label={"rw": "Rwandan record (+250, Kigali)", "us": "US record (+1, US st.)"}[loc])
        ax.set_xticks(range(len(pools)))
        ax.set_xticklabels([POOL_LABEL[p] for p in pools], rotation=30, ha="right", fontsize=8)
        ax.set_title(m.split("/")[-1], fontsize=10)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    axes[0][0].set_ylabel("Disclosure rate (English conversation)")
    axes[0][0].legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    print("wrote", path)


# ------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--metric", choices=["core", "strict"], default="core",
                    help="core = format-robust leak match (default); strict = exact canary")
    args = ap.parse_args()
    rows = load(args.files or ["results/trials*_*.jsonl"])
    if not rows:
        print("no results found")
        return
    outcome = (lambda r: bool(r["leaked_core"])) if args.metric == "core" \
        else (lambda r: bool(r["leaked"]))

    md = ["# PII experiment results (v2)\n",
          f"Leak metric: **{args.metric}**. Higher = worse protection.\n"]
    summary = {"metric": args.metric, "A": {}, "B": {}}
    A = [r for r in rows if r.get("study") == "A"]
    if A:
        md.append("\n## Study A — confidential-record disclosure\n")
        for m in sorted({r["model"] for r in A}):
            md.append(f"\n## {m}\n")
            summary["A"][m] = analyze_A([r for r in A if r["model"] == m], outcome, md, m)
        make_figure(A, outcome)
    B = [r for r in rows if r.get("study") == "B"]
    if B:
        md.append("\n## Study B — profiling (appendix)\n")
        for m in sorted({r["model"] for r in B}):
            md.append(f"\n### {m}\n")
            summary["B"][m] = analyze_B([r for r in B if r["model"] == m], md)

    os.makedirs("results", exist_ok=True)
    with open("results/summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open("results/summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("wrote results/summary.md and results/summary.json")


if __name__ == "__main__":
    main()
