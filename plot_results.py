
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

RESULTS_CSV   = "results/results.csv"
SELECTION_CSV = "ontology_selection.csv"
OUT_DIR       = Path("plots")
TOOLS         = ["CATS", "LETHE", "AAA"]
COLORS        = {"CATS": "#3B6BB0", "LETHE": "#E07B39", "AAA": "#4E9A6B"}
# LUBM is added by hand because it is not in the ORE selection file.
LUBM          = {"ontology_name": "univ-bench", "n_classes": 43, "n_dataprops": 7}

plt.rcParams.update({
    "font.size": 12, "axes.titlesize": 13, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 110,
})


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _status(r):
    s = str(r["runtime_s"])
    if s.startswith("TIMEOUT"):
        return "timeout"
    if s.startswith("ERROR"):
        return "error"
    hs = 0 if np.isnan(r["hs"]) else r["hs"]
    if r["valid"] == "true" and hs > 0:
        return "solved"
    if hs > 0:
        return "invalid"
    return "empty"


def load_results():
    df = pd.read_csv(RESULTS_CSV, dtype=str).fillna("")
    df["rt"]    = df["runtime_s"].apply(_num)
    df["hs"]    = df["hypothesis_size"].apply(_num)
    df["rec"]   = df["recovery_rate"].apply(_num)
    df["prec"]  = df["recovered_set_precision"].apply(_num)
    df["mem"]   = df["peak_memory_mb"].apply(_num)
    df["valid"] = df["valid_explanation"].str.strip().str.lower()
    df["status"] = df.apply(_status, axis=1)
    df["solved"] = df["status"] == "solved"
    return df


def load_meta():
    if not Path(SELECTION_CSV).exists():
        return None
    sel = pd.read_csv(SELECTION_CSV)
    sel["ontology_name"] = sel["file"].str.replace(".owl", "", regex=False)
    cols = ["ontology_name", "n_classes", "n_dataprops"]
    extra = pd.DataFrame([{c: LUBM[c] for c in cols}])
    return pd.concat([sel[cols], extra], ignore_index=True)


def _save(fig, name):
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT_DIR / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  saved plots/{name}.pdf")


def plot_outcome(df):
    order = ["solved", "invalid", "empty", "timeout", "error"]
    cols  = {"solved": "#4E9A6B", "invalid": "#C44E52", "empty": "#C7C7C7",
             "timeout": "#E0A030", "error": "#8C6BB1"}
    counts = {t: df[df.tool_name == t].status.value_counts() for t in TOOLS}
    fig, ax = plt.subplots(figsize=(9, 3.6))
    y, left = list(range(len(TOOLS))), [0] * len(TOOLS)
    for c in order:
        vals = [int(counts[t].get(c, 0)) for t in TOOLS]
        ax.barh(y, vals, left=left, color=cols[c], label=c, edgecolor="white")
        left = [l + v for l, v in zip(left, vals)]
    ax.set_yticks(y); ax.set_yticklabels(TOOLS); ax.invert_yaxis()
    ax.set_xlabel("Number of problems")
    ax.set_title("Outcome breakdown by tool")
    ax.legend(ncol=5, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.18))
    _save(fig, "outcome_by_tool")


def plot_cactus(df):
    total = df.groupby(["ontology_name", "strategy"]).ngroups
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for t in TOOLS:
        rts = sorted(df[(df.tool_name == t) & df.solved].rt.dropna())
        if not rts:
            continue
        ax.plot(rts, range(1, len(rts) + 1), marker="o", ms=4, lw=1.8,
                color=COLORS[t], label=f"{t}  ({len(rts)}/{total} solved)")
    ax.set_xscale("log")
    ax.set_xlabel("Time budget per problem  (seconds, log scale)")
    ax.set_ylabel("Problems solved within budget")
    ax.set_title("Problems solved within a time budget, by tool")
    ax.grid(True, which="both", alpha=.25)
    ax.legend(frameon=False, loc="lower right")
    _save(fig, "solved_vs_time")


def plot_recovery_status(df):
    def cls(r):
        if r.solved and r.rec > 0:
            return "matched"
        if r.solved and r.rec == 0:
            return "disjoint"
        return "none"
    d = df.copy()
    d["rs"] = d.apply(cls, axis=1)
    order = ["matched", "disjoint", "none"]
    cols  = {"matched": "#4E9A6B", "disjoint": "#E0A030", "none": "#C7C7C7"}
    labels = {"matched": "matched ground truth",
              "disjoint": "valid but syntactically disjoint",
              "none": "no valid hypothesis"}
    counts = {t: d[d.tool_name == t].rs.value_counts() for t in TOOLS}
    fig, ax = plt.subplots(figsize=(9, 3.6))
    y, left = list(range(len(TOOLS))), [0] * len(TOOLS)
    for c in order:
        vals = [int(counts[t].get(c, 0)) for t in TOOLS]
        ax.barh(y, vals, left=left, color=cols[c], label=labels[c],
                edgecolor="white")
        left = [l + v for l, v in zip(left, vals)]
    ax.set_yticks(y); ax.set_yticklabels(TOOLS); ax.invert_yaxis()
    ax.set_xlabel("Number of problems")
    ax.set_title("Recovery outcome by tool")
    ax.legend(ncol=3, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.18))
    _save(fig, "recovery_status_by_tool")


def plot_validity(df):
    vals = {}
    for t in TOOLS:
        sub = df[(df.tool_name == t) & df.status.isin(["solved", "invalid"])]
        vals[t] = 100 * (sub.status == "solved").mean() if len(sub) else np.nan
    _pct_bar(vals, "Valid-explanation rate by tool (correctness)",
             "Valid explanations (%)", "validity_by_tool")


def plot_precision(df):
    vals = {}
    for t in TOOLS:
        sub = df[(df.tool_name == t) & df.solved]
        vals[t] = 100 * sub.prec.mean() if sub.prec.notna().any() else np.nan
    _pct_bar(vals, "Mean precision by tool", "Mean precision (%)",
             "precision_by_tool")


def _pct_bar(vals, title, ylab, fname):
    fig, ax = plt.subplots(figsize=(6, 4.6))
    bars = ax.bar(TOOLS, [vals[t] for t in TOOLS],
                  color=[COLORS[t] for t in TOOLS], width=0.6)
    for b, t in zip(bars, TOOLS):
        v = vals[t]
        if not np.isnan(v):
            ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.1f}%",
                    ha="center", fontsize=11)
    ax.set_ylim(0, 105); ax.set_ylabel(ylab); ax.set_title(title)
    _save(fig, fname)


def plot_strip(df, col, title, ylab, fname, tools=TOOLS):
    fig, ax = plt.subplots(figsize=(7, 4.8))
    used = []
    for i, t in enumerate(tools):
        vals = df[(df.tool_name == t) & df.solved][col].dropna().values
        if len(vals) == 0:
            continue
        used.append(t)
        x = np.random.normal(i, 0.07, len(vals))
        ax.scatter(x, vals, s=30, alpha=.55, color=COLORS[t],
                   edgecolor="white", linewidth=.4, zorder=3)
        ax.hlines(np.median(vals), i - 0.2, i + 0.2, color="black", lw=2,
                  zorder=4)
    if not used:
        plt.close(fig)
        print(f"  (skipped {fname}: no data in '{col}')")
        return
    ax.set_yscale("log")
    ax.set_xticks(range(len(tools))); ax.set_xticklabels(tools)
    ax.set_ylabel(ylab); ax.set_title(title)
    ax.grid(True, axis="y", which="both", alpha=.25)
    _save(fig, fname)


def plot_solverate_vs(df, meta, xcol, xlabel, title, fname, average=False):
    if meta is None:
        print(f"  (skipped {fname}: {SELECTION_CSV} not found)")
        return
    rows = [dict(ontology_name=ont, tool=t, solve_rate=100 * g.solved.sum() / len(g))
            for (ont, t), g in df.groupby(["ontology_name", "tool_name"])]
    agg = (pd.DataFrame(rows)
           .merge(meta, on="ontology_name", how="left")
           .dropna(subset=[xcol]))
    if agg.empty:
        print(f"  (skipped {fname}: no ontologies matched {SELECTION_CSV})")
        return
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for t in TOOLS:
        d = agg[agg.tool == t]
        if average:
            d = d.groupby(xcol, as_index=False).solve_rate.mean()
        d = d.sort_values(xcol)
        if d.empty:
            continue
        ax.plot(d[xcol], d.solve_rate, marker="o", ms=6, lw=1.6, alpha=.85,
                color=COLORS[t], label=t)
    if not average:
        ax.set_xscale("log")
    ax.set_xlabel(xlabel); ax.set_ylabel("Problems solved (%)")
    ax.set_ylim(-5, 105); ax.set_title(title)
    ax.grid(True, which="both", alpha=.25); ax.legend(frameon=False)
    _save(fig, fname)


def main():
    np.random.seed(0)  # stable strip-plot jitter
    if not Path(RESULTS_CSV).exists():
        print(f"No results at {RESULTS_CSV} — run the experiment first.")
        return
    df = load_results()
    meta = load_meta()
    print(f"Loaded {len(df)} runs across {df.ontology_name.nunique()} "
          f"ontologies ({df.solved.sum()} solved).\n")

    plot_outcome(df)
    plot_cactus(df)
    plot_recovery_status(df)
    plot_validity(df)
    plot_precision(df)
    plot_strip(df, "hs", "Size of valid hypotheses, by tool",
               "Hypothesis size (axioms, log scale)", "hypothesis_size_by_tool")
    # memory is only meaningful for the native-JVM tools (None for AAA)
    plot_strip(df, "mem", "Peak memory of solved runs, by tool",
               "Peak memory (MB, log scale)", "memory_by_tool",
               tools=["CATS", "LETHE"])
    plot_solverate_vs(df, meta, "n_classes", "Ontology size (named classes)",
                      "Solve rate vs ontology size, by tool",
                      "solverate_vs_size", average=False)
    plot_solverate_vs(df, meta, "n_dataprops", "Datatype properties in ontology",
                      "Solve rate vs datatype-property count, by tool",
                      "solverate_vs_dataprops", average=True)
    print("\nDone.")


if __name__ == "__main__":
    main()