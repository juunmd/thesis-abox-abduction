# scan_ontologies.py
"""
Scan a whitelist of ORE 2015 ontologies for usability in our ABox
abduction experiment.

For each whitelisted ontology found in the input folder (recursively):
  - load it via OWLAPY
  - count class assertions, SubClassOf axioms, named individuals, named classes
  - check whether at least one asserted individual has a class whose
    superclass chain extends beyond owl:Thing (the "anchored" condition)
  - record file size for size-based ranking

Output: scan_results.csv with one row per ontology.
"good" = True when:
    class_assertions > 5
    AND subclass_axioms > 5
    AND has_anchored_candidate
"""
import csv
import sys
from pathlib import Path

from owlapy.owl_ontology import SyncOntology
from owlapy.owl_axiom import OWLClassAssertionAxiom, OWLSubClassOfAxiom

# --- Configuration ---
INPUT_FOLDER = Path(r"C:\Users\mydah\Downloads\ore2015_sample\pool_sample\files")
OUTPUT_CSV   = Path("scan_results.csv")

# Only these filenames will be scanned. Anything in INPUT_FOLDER but not
# in this list is ignored. Anything in this list but not found in
# INPUT_FOLDER is reported as missing at the start of the run.
WHITELIST = frozenset([
    "ore_ont_5760.owl",
    "ore_ont_11694.owl",
    "ore_ont_1330.owl",
    "ore_ont_10481.owl",
    "ore_ont_14216.owl",
    "ore_ont_12150.owl",
    "ore_ont_13233.owl",
    "ore_ont_4780.owl",
    "ore_ont_1043.owl",
    "ore_ont_11978.owl",
    "ore_ont_1743.owl",
    "ore_ont_5149.owl",
    "ore_ont_10750.owl",
    "ore_ont_16267.owl",
    "ore_ont_1954.owl",
    "ore_ont_11572.owl",
    "ore_ont_2046.owl",
    "ore_ont_2556.owl",
    "ore_ont_8882.owl",
    "ore_ont_11115.owl",
    "ore_ont_6233.owl",
    "ore_ont_2608.owl",
    "ore_ont_16184.owl",
    "ore_ont_13112.owl",
    "ore_ont_16767.owl",
    "ore_ont_2488.owl",
    "ore_ont_9386.owl",
    "ore_ont_15921.owl",
    "ore_ont_6120.owl",
    "ore_ont_568.owl",
    "ore_ont_15013.owl",
    "ore_ont_14191.owl",
    "ore_ont_1012.owl",
    "ore_ont_13872.owl",
    "ore_ont_9792.owl",
    "ore_ont_12152.owl",
    "ore_ont_8723.owl",
    "ore_ont_12721.owl",
    "ore_ont_7356.owl",
    "ore_ont_8730.owl",
    "ore_ont_5769.owl",
    "ore_ont_9462.owl",
    "ore_ont_4182.owl",
    "ore_ont_16124.owl",
    "ore_ont_1306.owl",
    "ore_ont_9690.owl",
    "ore_ont_12992.owl",
    "ore_ont_7483.owl",
    "ore_ont_9046.owl",
    "ore_ont_14175.owl",
    "ore_ont_4127.owl",
    "ore_ont_6401.owl",
    "ore_ont_13482.owl",
    "ore_ont_4315.owl",
    "ore_ont_12522.owl",
    "ore_ont_7680.owl",
    "ore_ont_4557.owl",
    "ore_ont_155.owl",
    "ore_ont_12452.owl",
    "ore_ont_12932.owl",
    "ore_ont_9768.owl",
    "ore_ont_13035.owl",
    "ore_ont_11053.owl",
    "ore_ont_14353.owl",
    "ore_ont_7993.owl",
    "ore_ont_16033.owl",
    "ore_ont_6792.owl",
    "ore_ont_7188.owl",
    "ore_ont_4242.owl",
    "ore_ont_1172.owl",
    "ore_ont_5721.owl",
    "ore_ont_15475.owl",
    "ore_ont_5781.owl",
    "ore_ont_8355.owl",
    "ore_ont_4033.owl",
    "ore_ont_8844.owl",
    "ore_ont_6816.owl",
    "ore_ont_16115.owl",
    "ore_ont_1965.owl",
    "ore_ont_12351.owl",
    "ore_ont_5509.owl",
    "ore_ont_6720.owl",
    "ore_ont_2253.owl",
    "ore_ont_7800.owl",
    "ore_ont_3771.owl",
    "ore_ont_15280.owl",
    "ore_ont_8502.owl",
    "ore_ont_11577.owl",
    "ore_ont_11827.owl",
    "ore_ont_10314.owl",
    "ore_ont_12892.owl",
    "ore_ont_5602.owl",
    "ore_ont_10199.owl",
    "ore_ont_13078.owl",
    "ore_ont_5596.owl",
    "ore_ont_3936.owl",
    "ore_ont_253.owl",
    "ore_ont_12567.owl",
    "ore_ont_5205.owl",
    "ore_ont_9947.owl",
    "ore_ont_8787.owl",
    "ore_ont_15068.owl",
    "ore_ont_1469.owl",
    "ore_ont_11459.owl",
    "ore_ont_16827.owl",
    "ore_ont_4400.owl",
    "ore_ont_14185.owl",
    "ore_ont_16759.owl",
    "ore_ont_3259.owl",
])

OWL_THING = "http://www.w3.org/2002/07/owl#Thing"


def scan_one(path: Path) -> dict:
    """Return a dict of metrics for one ontology, or an error dict."""
    file_size = path.stat().st_size
    try:
        onto = SyncOntology(str(path))
    except Exception as e:
        return {
            "file":          path.name,
            "file_size_kb":  round(file_size / 1024, 1),
            "loadable":      False,
            "error":         f"load error: {type(e).__name__}",
            "class_assertions":   0,
            "subclass_axioms":    0,
            "total_axioms":       0,
            "named_classes":      0,
            "named_individuals":  0,
            "has_anchored":  False,
            "good":          False,
        }

    java_onto = onto.owlapi_ontology
    try:
        imports_enum = onto._get_imports_enum(True)
        abox = list(java_onto.getABoxAxioms(imports_enum))
        tbox = list(java_onto.getTBoxAxioms(imports_enum))

        ca_axioms = []
        for ax in abox:
            try:
                mapped = onto.mapper.map_(ax)
                if isinstance(mapped, OWLClassAssertionAxiom):
                    ca_axioms.append(mapped)
            except Exception:
                continue

        sc_count = 0
        # Build a quick subclass map for the anchored check.
        super_of = {}
        for ax in tbox:
            try:
                mapped = onto.mapper.map_(ax)
                if not isinstance(mapped, OWLSubClassOfAxiom):
                    continue
                sc_count += 1
                sub = mapped.get_sub_class()
                sup = mapped.get_super_class()
                if hasattr(sub, "iri") and hasattr(sup, "iri"):
                    sub_iri = sub.iri.as_str()
                    sup_iri = sup.iri.as_str()
                    if sup_iri != OWL_THING:
                        super_of.setdefault(sub_iri, set()).add(sup_iri)
            except Exception:
                continue

        has_anchored = False
        for ca in ca_axioms:
            try:
                cls = ca.get_class_expression()
                if hasattr(cls, "iri"):
                    if super_of.get(cls.iri.as_str()):
                        has_anchored = True
                        break
            except Exception:
                continue

        total_axioms = int(java_onto.getAxiomCount())
        classes = list(onto.classes_in_signature())
        inds    = list(onto.individuals_in_signature())

        ca_count = len(ca_axioms)
        good = (ca_count > 5) and (sc_count > 5) and has_anchored

        return {
            "file":               path.name,
            "file_size_kb":       round(file_size / 1024, 1),
            "loadable":           True,
            "error":              "",
            "class_assertions":   ca_count,
            "subclass_axioms":    sc_count,
            "total_axioms":       total_axioms,
            "named_classes":      len(classes),
            "named_individuals":  len(inds),
            "has_anchored":       has_anchored,
            "good":               good,
        }
    except Exception as e:
        return {
            "file":          path.name,
            "file_size_kb":  round(file_size / 1024, 1),
            "loadable":      True,
            "error":         f"scan error: {type(e).__name__}",
            "class_assertions":   0,
            "subclass_axioms":    0,
            "total_axioms":       0,
            "named_classes":      0,
            "named_individuals":  0,
            "has_anchored":  False,
            "good":          False,
        }


def main():
    if not INPUT_FOLDER.exists():
        sys.exit(f"Folder not found: {INPUT_FOLDER}")

    # Recurse — ORE sometimes nests files in subfolders.
    all_files = {f.name: f for f in INPUT_FOLDER.rglob("*.owl")}
    found     = [all_files[name] for name in WHITELIST if name in all_files]
    missing   = sorted(WHITELIST - set(all_files.keys()))

    print(f"Whitelist: {len(WHITELIST)} files requested")
    print(f"Found in folder: {len(found)}")
    if missing:
        print(f"NOT FOUND ({len(missing)}):")
        for m in missing:
            print(f"  - {m}")
        print()

    if not found:
        sys.exit("No whitelisted files found in INPUT_FOLDER. "
                 "Check the path and try again.")

    fields = ["file", "file_size_kb", "loadable", "error",
              "class_assertions", "subclass_axioms", "total_axioms",
              "named_classes", "named_individuals",
              "has_anchored", "good"]
    rows = []
    for i, f in enumerate(sorted(found, key=lambda p: p.name), 1):
        print(f"  [{i}/{len(found)}] {f.name}", flush=True)
        rows.append(scan_one(f))

    # Sort by total_axioms ascending so the smallest are at the top.
    rows.sort(key=lambda r: r["total_axioms"])

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    good_rows = [r for r in rows if r["good"]]
    print(f"\nScan complete. Results -> {OUTPUT_CSV.resolve()}")
    print(f"  Total scanned: {len(rows)}")
    print(f"  GOOD (eligible): {len(good_rows)}")
    print(f"  Errors / unloadable: "
          f"{sum(1 for r in rows if not r['loadable'] or r['error'])}")

    if good_rows:
        n_show = min(30, len(good_rows))
        print(f"\n{n_show} smallest GOOD ontologies (by total_axioms):")
        for r in good_rows[:n_show]:
            print(f"  {r['file']:<40s} "
                  f"axioms={r['total_axioms']:<6d} "
                  f"CA={r['class_assertions']:<5d} "
                  f"SC={r['subclass_axioms']:<5d}")


if __name__ == "__main__":
    main()