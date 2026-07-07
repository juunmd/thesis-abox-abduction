# profile_ontologies.py

import csv
from pathlib import Path
from config import load_ontology

ORE_FOLDER  = Path(r"C:\Users\mydah\Downloads\ore2015_sample\pool_sample\files")
CAND_CSV    = Path("candidate_counts.csv")
RESULTS_CSV = Path("results/results.csv")
OUT_CSV     = Path("ontology_profiles.csv")

# "Light" thresholds (student-inspired, adapted):
MAX_OBJ_PROPS   = 50
MAX_INDIVIDUALS = 200
MIN_CANDIDATES  = 10

def profile(path: Path) -> dict:
    onto = load_ontology(str(path))
    j = onto.owlapi_ontology
    imports = onto._get_imports_enum(True)
    return {
        "classes":      len(list(onto.classes_in_signature())),
        "obj_props":    len(list(onto.object_properties_in_signature())),
        "individuals":  len(list(onto.individuals_in_signature())),
        "tbox_axioms":  len(list(j.getTBoxAxioms(imports))),
        "abox_axioms":  len(list(j.getABoxAxioms(imports))),
        "total_axioms": int(j.getAxiomCount()),
    }


def main():
    if not CAND_CSV.exists():
        raise SystemExit("candidate_counts.csv not found.")
    with open(CAND_CSV, encoding="utf-8") as f:
        cand = {r["file"]: r for r in csv.DictReader(f)
                if not r.get("error")
                and int(float(r.get("candidates") or 0)) >= MIN_CANDIDATES}
    print(f"{len(cand)} ontologies have >= {MIN_CANDIDATES} candidates. "
          f"Profiling...\n")

    rows = []
    for i, (fname, c) in enumerate(sorted(cand.items()), 1):
        path = ORE_FOLDER / fname
        print(f"\r  [{i}/{len(cand)}] {fname:<28s}", end="", flush=True)
        if not path.exists():
            continue
        try:
            p = profile(path)
        except Exception as e:
            continue
        p.update({"file": fname,
                  "candidates": int(float(c["candidates"])),
                  "equivalence_axioms": int(float(c["equivalence_axioms"]))})
        rows.append(p)
    print()

    fields = ["file", "candidates", "equivalence_axioms", "classes",
              "obj_props", "individuals", "tbox_axioms", "abox_axioms",
              "total_axioms"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"\nProfiles -> {OUT_CSV.resolve()}")

    light = [r for r in rows
             if r["obj_props"] <= MAX_OBJ_PROPS
             and r["individuals"] <= MAX_INDIVIDUALS]
    light.sort(key=lambda r: (r["obj_props"], r["total_axioms"]))
    print(f"\n{'='*66}")
    print(f"LIGHT sample: obj_props <= {MAX_OBJ_PROPS}, "
          f"individuals <= {MAX_INDIVIDUALS}, "
          f"candidates >= {MIN_CANDIDATES}: {len(light)} ontologies")
    print(f"  {'file':<26s}{'props':>6}{'inds':>6}{'cands':>6}"
          f"{'total':>8}")
    for r in light[:30]:
        print(f"  {r['file']:<26s}{r['obj_props']:>6}{r['individuals']:>6}"
              f"{r['candidates']:>6}{r['total_axioms']:>8}")
    print("\nPaste-ready list (top 30 light):")
    for r in light[:30]:
        print(r["file"])

    if RESULTS_CSV.exists():
        import pandas as pd
        res = pd.read_csv(RESULTS_CSV)
        res["timed_out"] = (res["timed_out"].astype(str).str.lower()
                            .isin(["true", "1"]))
        prof = pd.DataFrame(rows)
        prof["ontology_name"] = prof["file"].str.replace(".owl", "", regex=False)
        to = (res.groupby("ontology_name")["timed_out"].mean()
              .rename("timeout_rate").reset_index())
        m = prof.merge(to, on="ontology_name")
        if len(m) >= 3:
            print(f"\n{'='*66}")
            print("Correlation with per-ontology timeout rate "
                  f"(n={len(m)} ontologies):")
            for col in ["obj_props", "individuals", "classes",
                        "tbox_axioms", "total_axioms"]:
                r = m[col].corr(m["timeout_rate"])
                print(f"  {col:<14s} r = {r:+.2f}")
            print("\n(use plot: obj_props vs timeout_rate per tool for the "
                  "thesis figure)")


if __name__ == "__main__":
    main()