"""Headline numbers + Figure 1 for the paper (v2), from the trial files in results/.

    python -m src.paper_numbers            # reads results/, writes results/paper_numbers.md
                                           # and results/figure1_v2.png / .pdf
All name-pool comparisons are paired by persona index (identical secrets) and pool the two
record locales; CIs are persona-level bootstrap, p-values are persona-level sign tests.
"""
from __future__ import annotations
import glob
import json
import random
from collections import defaultdict
from math import comb

R = "results"
MAIN = [("Qwen2.5-1.5B", "Qwen25-15B-Instruct"), ("Qwen2.5-3B", "Qwen25-3B-Instruct"),
        ("Qwen2.5-7B", "Qwen25-7B-Instruct"), ("Llama-3.2-3B", "Llama-32-3B-Instruct"),
        ("Phi-3.5-mini", "Phi-35-mini-instruct")]
OTHER = ["en_rare", "invented", "cn", "in", "ng"]


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def load_comprehension(tag):
    """Study C rows with r['understood'] = native-speaker code (0/1) where one exists,
    else None; r['auto_understood'] keeps the keyword check. Codes come from
    results/comprehension_coding_<tag>_kin.csv, same row order as trialsC."""
    import csv
    import os
    c = load(f"{R}/trialsC_{tag}_kin.jsonl")
    path = f"{R}/comprehension_coding_{tag}_kin.csv"
    codes = list(csv.DictReader(open(path, encoding="utf-8"))) if os.path.exists(path) else []
    for i, r in enumerate(c):
        h = codes[i].get("human_understood_0_1", "").strip() if i < len(codes) else ""
        assert not codes or codes[i]["item"] == r["item"], f"row order mismatch at {i}"
        r["understood"] = int(h) if h in ("0", "1") else None
    return c


def sign_p(up, down):
    n, k = up + down, min(up, down)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def per_persona(rows, pool, lang="en"):
    """persona idx -> (leaks, trials) for one pool, locales pooled."""
    d = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["name_pool"] == pool and r["lang"] == lang:
            d[r["idx"]][0] += int(r["leaked_core"])
            d[r["idx"]][1] += 1
    return d


def paired_diff(rows, pools, ref="en", lang="en", B=4000, seed=0):
    """Mean over `pools` of (pool - ref) leak rate, in points, paired by persona index."""
    refd = per_persona(rows, ref, lang)
    ds = [per_persona(rows, p, lang) for p in pools]
    idx = sorted(refd)
    per = []
    for i in idx:
        r_rate = refd[i][0] / refd[i][1]
        per.append(sum(d[i][0] / d[i][1] for d in ds) / len(ds) - r_rate)
    est = 100 * sum(per) / len(per)
    rng = random.Random(seed)
    boots = sorted(100 * sum(rng.choice(per) for _ in per) / len(per) for _ in range(B))
    up, down = sum(x > 1e-12 for x in per), sum(x < -1e-12 for x in per)
    return est, boots[int(.025 * B)], boots[int(.975 * B)], sign_p(up, down), up, down


def rate(rows, **kw):
    sub = [r for r in rows if all(r[k] == v for k, v in kw.items())]
    return sum(r["leaked_core"] for r in sub), len(sub)


def main():
    md = ["# Paper numbers (v2)\n"]
    fig_a = []
    md.append("## English conversation: name pools vs Anglo (common), locales pooled\n")
    md.append("| Model | Anglo common | Rwandan | Rwandan − Anglo [95% CI], p, ↑/↓ | "
              "Other 5 pools (mean) − Anglo [95% CI], p |")
    md.append("|---|---|---|---|---|")
    for label, tag in MAIN:
        rows = load(f"{R}/trialsA_{tag}_main.jsonl")
        ke, ne = rate(rows, name_pool="en", lang="en")
        kr, nr = rate(rows, name_pool="rw", lang="en")
        rw = paired_diff(rows, ["rw"])
        ot = paired_diff(rows, OTHER)
        fig_a.append((label, rw, ot))
        md.append(f"| {label} | {100*ke/ne:.1f}% ({ke}/{ne}) | {100*kr/nr:.1f}% ({kr}/{nr}) | "
                  f"{rw[0]:+.1f} [{rw[1]:+.1f}, {rw[2]:+.1f}], p={rw[3]:.3g}, {rw[4]}/{rw[5]} | "
                  f"{ot[0]:+.1f} [{ot[1]:+.1f}, {ot[2]:+.1f}], p={ot[3]:.3g} |")

    md.append("\n## Original (v1) wording only vs new paraphrases: Anglo vs Rwandan leaks\n")
    md.append("| Model | p0 (v1 wording) | p1 | p2 |")
    md.append("|---|---|---|---|")
    for label, tag in MAIN:
        rows = load(f"{R}/trialsA_{tag}_main.jsonl")
        cells = []
        for p in range(3):
            ke, ne = rate(rows, name_pool="en", lang="en", paraphrase=p)
            kr, nr = rate(rows, name_pool="rw", lang="en", paraphrase=p)
            cells.append(f"{ke}/{ne} vs {kr}/{nr}")
        md.append(f"| {label} | " + " | ".join(cells) + " |")

    md.append("\n## Sampling (Qwen2.5-3B, T=0.7, 3 samples)\n")
    s = load(f"{R}/trialsA_Qwen25-3B-Instruct_sampled.jsonl")
    ke, ne = rate(s, name_pool="en")
    kr, nr = rate(s, name_pool="rw")
    d = paired_diff(s, ["rw"])
    md.append(f"Anglo {100*ke/ne:.1f}% ({ke}/{ne}), Rwandan {100*kr/nr:.1f}% ({kr}/{nr}); "
              f"diff {d[0]:+.1f} [{d[1]:+.1f}, {d[2]:+.1f}], sign p={d[3]:.3g}")
    for p in range(3):
        ke, ne = rate(s, name_pool="en", paraphrase=p)
        kr, nr = rate(s, name_pool="rw", paraphrase=p)
        md.append(f"- p{p}: Anglo {ke}/{ne} vs Rwandan {kr}/{nr}")

    md.append("\n## Language: English vs Kinyarwanda (Anglo + Rwandan pools, locales pooled)\n")
    md.append("| Model | English | Kinyarwanda | Study C native-speaker coded | Study C auto keyword check |")
    md.append("|---|---|---|---|---|")
    fig_b = []
    for label, tag in [("Qwen2.5-3B", "Qwen25-3B-Instruct"), ("Phi-3.5-mini", "Phi-35-mini-instruct"),
                       ("GPT-4o", "gpt-4o")]:
        kin = load(f"{R}/trialsA_{tag}_kin.jsonl")
        en_rows = kin if any(r["lang"] == "en" for r in kin) else \
            [r for r in load(f"{R}/trialsA_{tag}_main.jsonl") if r["name_pool"] in ("en", "rw")]
        k1, n1 = rate(en_rows, lang="en")
        k2, n2 = rate(kin, lang="rw")
        c = load_comprehension(tag)
        u = sum(r["auto_understood"] for r in c)
        hc = [r["understood"] for r in c if r["understood"] is not None]
        key = {r["item"]: (r["understood"], r["auto_understood"]) for r in c
               if r["item"] in ("system", "setup")}
        fig_b.append((label, 100 * k1 / n1, 100 * k2 / n2))
        md.append(f"| {label} | {100*k1/n1:.1f}% ({k1}/{n1}) | {100*k2/n2:.1f}% ({k2}/{n2}) | "
                  f"{sum(hc)}/{len(hc)} coded ({len(c)-len(hc)} uncoded; system prompt: "
                  f"{key['system'][0]}, record: {key['setup'][0]}) | "
                  f"{u}/{len(c)} (system: {key['system'][1]}, record: {key['setup'][1]}) |")

    v1 = load(f"{R}/trialsA_Qwen25-3B-Instruct_v1repro.jsonl")
    md.append("\n## v1 reproduction (Qwen2.5-3B, v1 settings)\n")
    for lang in ("en", "rw"):
        ke, ne = rate(v1, name_pool="en", lang=lang)
        kr, nr = rate(v1, name_pool="rw", lang=lang)
        md.append(f"- {lang}: Anglo {ke}/{ne}, Rwandan {kr}/{nr}")

    open(f"{R}/paper_numbers.md", "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))
    make_figure(fig_a, fig_b)


def make_figure(fig_a, fig_b):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2, grid = "#0b0b0b", "#52514e", "#e4e3df"
    c_rw, c_ot = "#eb6834", "#2a78d6"      # validated pair (categorical slots 2, 1)
    c_en, c_kin = "#6250d6", "#1baf7a"     # validated pair; aqua < 3:1 -> values labelled
    plt.rcParams.update({"font.size": 8, "axes.edgecolor": ink2, "axes.labelcolor": ink,
                         "xtick.color": ink2, "ytick.color": ink2, "font.family": "DejaVu Sans"})
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.6), gridspec_kw={"width_ratios": [1.25, 1]})
    ys = list(range(len(fig_a)))[::-1]
    for y, (label, rw, ot) in zip(ys, fig_a):
        a.plot([ot[1], ot[2]], [y - .15] * 2, color=c_ot, lw=2, solid_capstyle="round")
        a.plot(ot[0], y - .15, "o", ms=6, mfc="white", mec=c_ot, mew=2)
        a.plot([rw[1], rw[2]], [y + .15] * 2, color=c_rw, lw=2, solid_capstyle="round")
        a.plot(rw[0], y + .15, "o", ms=6, color=c_rw, mec="white", mew=1)
    a.axvline(0, color=ink2, lw=1)
    a.set_yticks(ys, [f[0] for f in fig_a])
    a.set_xlabel("Leak rate minus common Anglo names (pts)")
    a.grid(axis="x", color=grid, lw=.6)
    a.set_axisbelow(True)
    a.plot([], [], "o", color=c_rw, label="Rwandan names")
    a.plot([], [], "o", mfc="white", mec=c_ot, mew=2, label="Other 5 pools (mean)")
    a.legend(frameon=False, loc="lower right", fontsize=7)
    a.set_title("(a) Name effect, English conversations", loc="left", fontsize=8.5, color=ink)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)

    xs = range(len(fig_b))
    w = .36
    for x, (label, e, k) in zip(xs, fig_b):
        for dx, val, col in ((-w / 2 - .01, e, c_en), (w / 2 + .01, k, c_kin)):
            b.bar(x + dx, max(val, .4), w, color=col, edgecolor="white", lw=0)
            b.text(x + dx, max(val, .4) + 2, f"{val:.0f}%", ha="center", va="bottom",
                   fontsize=7, color=ink)
    b.set_xticks(list(xs), [f[0] for f in fig_b])
    b.set_ylim(0, 112)
    b.set_ylabel("Leak rate (%)")
    b.grid(axis="y", color=grid, lw=.6)
    b.set_axisbelow(True)
    from matplotlib.patches import Patch
    b.legend(handles=[Patch(color=c_en, label="English"), Patch(color=c_kin, label="Kinyarwanda")],
             frameon=False, loc="upper left", fontsize=7)
    b.set_title("(b) Language effect", loc="left", fontsize=8.5, color=ink)
    for s in ("top", "right"):
        b.spines[s].set_visible(False)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(f"{R}/figure1_v2.{ext}", dpi=300)
    print(f"wrote {R}/figure1_v2.png/.pdf")
    make_appendix_figures()


POOLS = [("en", "Anglo\ncommon"), ("en_rare", "Anglo\nrare"), ("invented", "Invented"),
         ("cn", "Chinese"), ("in", "Indian"), ("ng", "Nigerian"), ("rw", "Rwandan")]
ATK = ["reconnect_email", "reconnect_phone", "postal_address", "id_direct", "id_authority"]
ATK_SHORT = {"reconnect_email": "email", "reconnect_phone": "phone", "postal_address": "addr.",
             "id_direct": "ID", "id_authority": "bank"}


def _heat(ax, M, rows, cols, cmap, vmin, vmax, fmt, ink="#0b0b0b"):
    import numpy as np
    im = ax.imshow(np.array(M), cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(cols)), cols)
    ax.set_yticks(range(len(rows)), rows)
    for i, row in enumerate(M):
        for j, v in enumerate(row):
            frac = (v - vmin) / (vmax - vmin) if vmax > vmin else 0
            dark = frac > .62 if vmin >= 0 else abs(v) / vmax > .6
            ax.text(j, i, fmt(v), ha="center", va="center", fontsize=6.5,
                    color="white" if dark else ink)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    return im


def make_appendix_figures():
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    seq = LinearSegmentedColormap.from_list("seq", ["#f4f8fd", "#86b6ef", "#2a78d6", "#0d366b"])
    div = LinearSegmentedColormap.from_list("div", ["#2a78d6", "#f0efec", "#e34948"])
    models = [(lab, load(f"{R}/trialsA_{tag}_main.jsonl")) for lab, tag in MAIN]

    # A1: leak rate per pool x model (English, locales pooled)
    M = []
    for _, rows in models:
        M.append([100 * rate(rows, name_pool=p, lang="en")[0] / rate(rows, name_pool=p, lang="en")[1]
                  for p, _ in POOLS])
    fig, ax = plt.subplots(figsize=(6.2, 2.3))
    im = _heat(ax, M, [m[0] for m in models], [c for _, c in POOLS], seq, 0, 60,
               lambda v: f"{v:.0f}%")
    fig.colorbar(im, ax=ax, fraction=.03, pad=.02).set_label("Leak rate (%)")
    ax.set_title("Leak rate by name pool (English conversations; 900 trials per cell)",
                 loc="left", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(f"{R}/figA1_pools.pdf")
    fig.savefig(f"{R}/figA1_pools.png", dpi=300)

    # A2: Rwandan - Anglo difference per prompt (attack x paraphrase)
    cols, M = [], []
    for a in ATK:
        for p in range(3):
            cols.append(f"{ATK_SHORT[a]}\np{p}")
    for _, rows in models:
        row = []
        for a in ATK:
            for p in range(3):
                ke, ne = rate(rows, name_pool="en", lang="en", attack=a, paraphrase=p)
                kr, nr = rate(rows, name_pool="rw", lang="en", attack=a, paraphrase=p)
                row.append(100 * (kr / nr - ke / ne))
        M.append(row)
    fig, ax = plt.subplots(figsize=(7.0, 2.4))
    im = _heat(ax, M, [m[0] for m in models], cols, div, -60, 60, lambda v: f"{v:+.0f}")
    ax.tick_params(axis="x", labelsize=6)
    fig.colorbar(im, ax=ax, fraction=.03, pad=.02).set_label("Rwandan − Anglo (pts)")
    ax.set_title("Name gap per prompt (p0 = original wording; 60 trials per pool per cell)",
                 loc="left", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(f"{R}/figA2_prompts.pdf")
    fig.savefig(f"{R}/figA2_prompts.png", dpi=300)

    # A3: Kinyarwanda comprehension per item (native-speaker coded translation check)
    items = ["system", "setup"] + [f"{a}#{p}" for a in ATK for p in range(3)]
    labels = ["system\nprompt", "record"] + [f"{ATK_SHORT[a]}\np{p}" for a in ATK for p in range(3)]
    rowsM, names = [], []
    for lab, tag in [("Qwen2.5-3B", "Qwen25-3B-Instruct"), ("Phi-3.5-mini", "Phi-35-mini-instruct"),
                     ("GPT-4o", "gpt-4o")]:
        c = load_comprehension(tag)
        agg = defaultdict(lambda: [0, 0])
        for r in c:
            if r["understood"] is None:     # uncoded rows are left out, not counted as 0
                continue
            agg[r["item"]][0] += r["understood"]
            agg[r["item"]][1] += 1
        rowsM.append([100 * agg[i][0] / agg[i][1] for i in items])
        names.append(lab)
    fig, ax = plt.subplots(figsize=(7.0, 1.7))
    im = _heat(ax, rowsM, names, labels, seq, 0, 100, lambda v: f"{v:.0f}")
    ax.tick_params(axis="x", labelsize=6)
    fig.colorbar(im, ax=ax, fraction=.03, pad=.02).set_label("% understood")
    ax.set_title("Kinyarwanda comprehension: share of translations native speakers coded as correct",
                 loc="left", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(f"{R}/figA3_comprehension.pdf")
    fig.savefig(f"{R}/figA3_comprehension.png", dpi=300)
    print("wrote appendix figures A1-A3")


if __name__ == "__main__":
    main()
