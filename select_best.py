
import sys
import os
import csv
import glob

SMALL_MAX = 50
MEDIUM_MAX = 150
SAMPLE_PER_BUCKET = 8
DEEP_SHORTLIST = 120
MAX_CLASSES = 800
MAX_FILE_MB = 40

_SKIP_EXT = {".py", ".csv", ".txt", ".md", ".json", ".log", ".pyc", ".ini"}


def quick_scan(path):
    """No-Java scan: returns dict(size, has_problem) or None to skip."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _SKIP_EXT:
        return None
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_MB * 1_000_000:
            return None                      # monster ontology: skip outright
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read(8_000_000)        # cap reads at ~8 MB
    except Exception:
        return None
    low = text.lower()
    looks_onto = ("ontology(" in low or "<owl:" in low
                  or "xmlns:owl" in low or "<rdf:rdf" in low)
    if not looks_onto:
        return None                          # not an ontology file
    has_problem = ("subclassof" in low) or ("equivalentclass" in low)
    return {"size": size, "has_problem": has_problem}


def analyze(path):
    from owlapy.owl_ontology import SyncOntology
    from equivalence_strategy import _equivalence_pairs, _subclass_pairs
    onto = SyncOntology(path)
    n_classes = len(list(onto.classes_in_signature()))
    n_obj = len(list(onto.object_properties_in_signature()))
    n_data = len(list(onto.data_properties_in_signature()))
    n_ind = len(list(onto.individuals_in_signature()))
    eq_pairs = list(_equivalence_pairs(onto))
    covered = {c for c, _ in eq_pairs}
    sub_pairs = list(_subclass_pairs(onto, covered))
    dl = None
    try:
        import jpype
        P = jpype.JClass("org.semanticweb.owlapi.profiles.OWL2DLProfile")
        dl = bool(P().checkOntology(onto.owlapi_ontology).isInProfile())
    except Exception:
        dl = None
    return {"n_classes": n_classes, "n_objprops": n_obj, "n_dataprops": n_data,
            "n_individuals": n_ind, "n_eq": len(eq_pairs), "n_sub": len(sub_pairs),
            "n_problems": len(eq_pairs) + len(sub_pairs), "dl": dl}


def _spread(items, k):
    """Evenly spaced k items from a list."""
    if len(items) <= k:
        return list(items)
    step = len(items) / k
    return [items[int(j * step)] for j in range(k)]


def main(pool_dir, deep_n=DEEP_SHORTLIST):
    files = [f for f in sorted(glob.glob(os.path.join(pool_dir, "*")))
             if os.path.isfile(f)]
    if not files:
        print(f"No files found in {pool_dir!r}")
        return

    print(f"Phase 1: text-scanning {len(files)} files (no Java)...")
    usable = []
    for f in files:
        info = quick_scan(f)
        if info is None or not info["has_problem"]:
            continue
        info["file"] = f
        usable.append(info)
    usable.sort(key=lambda r: r["size"])

    with open("quick_scan.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "size_bytes", "has_problem"])
        for r in usable:
            w.writerow([os.path.basename(r["file"]), r["size"], True])
    print(f"  -> {len(usable)} usable ontologies (have subclass/equiv axioms). "
          f"Wrote quick_scan.csv")

    if not usable:
        return


    n = len(usable)
    t = max(1, n // 3)
    groups = [usable[:t], usable[t:2 * t], usable[2 * t:]]
    per = max(1, deep_n // 3)
    shortlist = []
    for g in groups:
        shortlist.extend(_spread(g, min(per, len(g))))
    print(f"\nPhase 2: owlapy + DL analysis on {len(shortlist)} "
          f"size-spread candidates...")

    rows = []
    for i, r in enumerate(shortlist, 1):
        name = os.path.basename(r["file"])
        try:
            info = analyze(r["file"])
        except Exception as e:
            print(f"  [{i}/{len(shortlist)}] {name}: FAILED ({type(e).__name__})")
            continue
        info["file"] = name
        rows.append(info)
        print(f"  [{i}/{len(shortlist)}] {name}: classes={info['n_classes']} "
              f"problems={info['n_problems']} dataprops={info['n_dataprops']} "
              f"dl={info['dl']}")

    verified = [r for r in rows if r["n_problems"] > 0 and r["dl"] is not False
                and r["n_classes"] <= MAX_CLASSES]
    capped = [r for r in rows if r["n_classes"] > MAX_CLASSES]
    if capped:
        print(f"  ({len(capped)} ontologies excluded as > {MAX_CLASSES} "
              f"classes — impractical for the tool run)")
    verified.sort(key=lambda r: r["n_classes"])

    fields = ["file", "n_classes", "n_objprops", "n_dataprops",
              "n_individuals", "n_eq", "n_sub", "n_problems", "dl"]
    with open("ontology_selection.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in verified:
            w.writerow({k: r[k] for k in fields})

    small = [r for r in verified if r["n_classes"] < SMALL_MAX]
    medium = [r for r in verified if SMALL_MAX <= r["n_classes"] < MEDIUM_MAX]
    large = [r for r in verified if r["n_classes"] >= MEDIUM_MAX]

    print("\n" + "=" * 60)
    print(f"Phase 1 usable: {len(usable)}   Phase 2 verified DL+usable: "
          f"{len(verified)}")
    print(f"  small  (<{SMALL_MAX}):      {len(small)}")
    print(f"  medium ({SMALL_MAX}-{MEDIUM_MAX - 1}):  {len(medium)}")
    print(f"  large  (>={MEDIUM_MAX}):    {len(large)}")
    print("Wrote ontology_selection.csv")

    sample = (_spread(small, SAMPLE_PER_BUCKET)
              + _spread(medium, SAMPLE_PER_BUCKET)
              + _spread(large, SAMPLE_PER_BUCKET))
    print(f"\nSuggested stratified sample ({len(sample)}):")
    for r in sample:
        print(f"  {r['file']:42} classes={r['n_classes']:4} "
              f"problems={r['n_problems']:3} dataprops={r['n_dataprops']}")


if __name__ == "__main__":
    pool = sys.argv[1] if len(sys.argv) > 1 else "."
    deep = DEEP_SHORTLIST
    if "--deep" in sys.argv:
        try:
            deep = int(sys.argv[sys.argv.index("--deep") + 1])
        except Exception:
            pass
    main(pool, deep)