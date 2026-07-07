# main.py
import random
from pathlib import Path
from owlapy.static_funcs import stopJVM
from owlapy.owl_axiom import OWLClassAssertionAxiom
from owlapy.owl_reasoner import SyncReasoner
from owlapy.owl_individual import OWLNamedIndividual
from owlapy.class_expression import OWLClass
from owlapy.iri import IRI

from config import load_ontology, ONTOLOGY_DIR, RANDOM_SEED
from ontology_utils import get_class_assertions, save_ontology
from strategies import _copy_ontology
from tools import run_tool
from evaluate import (compute_metrics, count_hypothesis_classes,
                      count_hypothesis_assertions, is_valid_explanation)
from output import save_results, init_results, append_result
from equivalence_strategy import build_equivalence_problems


def get_sig(onto):
    return {e.iri.as_str() for e in onto.get_signature()}


def _short(iri_str: str) -> str:
    """Last fragment of an IRI for display purposes. Works on both
    #-separated (`http://x.org/ont#Foo` -> `Foo`) and /-separated
    (`http://x.org/ont/Foo` -> `Foo`) IRIs. Returns the input
    unchanged if neither separator is present."""
    if "#" in iri_str:
        return iri_str.rsplit("#", 1)[-1]
    if "/" in iri_str:
        return iri_str.rsplit("/", 1)[-1]
    return iri_str


def sig_of_axioms(axioms):
    s = set()
    for ax in axioms:
        try:
            s.add(ax.get_class_expression().iri.as_str())
            s.add(ax.get_individual().iri.as_str())
        except Exception:
            pass
    return s


def is_entailed(onto_path, axiom):
    try:
        reasoner = SyncReasoner(onto_path, reasoner="HermiT")
        instances = set(reasoner.instances(
            axiom.get_class_expression(), timeout=5000))
        return axiom.get_individual() in instances
    except Exception:
        return False


def main():
    results = {}
    summary = {"total": 0, "solved": 0, "timed_out": 0, "error": 0,
               "ontologies_processed": 0, "ontologies_failed": 0}
    Path("tmp").mkdir(exist_ok=True)
    Path("results").mkdir(exist_ok=True)
    init_results()  # fresh CSV with just the header

    tools      = ["CATS", "LETHE", "AAA"]
    onto_files = sorted(Path(ONTOLOGY_DIR).glob("*.owl"))

    if not onto_files:
        print("No ontologies found in ontologies/ folder.")
        return

    print(f"Found {len(onto_files)} ontology files.\n")

    for ont_idx, owl_file in enumerate(onto_files, 1):
        onto_name      = owl_file.stem
        full_onto_path = str(owl_file)
        print(f"\n{'='*50}")
        print(f"[{ont_idx}/{len(onto_files)}] Ontology: {onto_name}")
        print(f"{'='*50}")

        # Wrap the per-ontology body so a single bad ontology doesn't
        # take the whole experiment down. KeyboardInterrupt still
        # propagates so Ctrl-C works as expected.
        try:
            onto = load_ontology(full_onto_path)

            # Patrick's setting: synthesise observations from equivalence
            # axioms on a fresh individual `a`. No existing ABox is needed,
            # so — unlike the removal-based strategies — we do NOT skip
            # ontologies that lack class assertions.
            problems = build_equivalence_problems(onto, full_onto_path)

            if not problems:
                print(f"  Skipping — no usable equivalence axiom "
                      f"(need an atomic or conjunctive definition over "
                      f"named classes).")
                continue

            print(f"  Built {len(problems)} abduction problem(s) "
                  f"from equivalence axioms")
            # The ontology copy with `a` declared is shared by all problems.
            obs_onto = problems[0].obs_onto

            for p_idx, prob in enumerate(problems, 1):
                observation  = prob.observation
                ground_truth = prob.ground_truth
                allowed_sig  = prob.allowed_sig
                obs_path     = prob.obs_path

                obs_label = f"{_short(prob.c_iri)}({_short(prob.a_iri)})"
                gt_label = ", ".join(
                    f"{_short(e)}({_short(prob.a_iri)})"
                    for e in prob.e_iris)
                src = getattr(prob, "source", "eq")
                print(f"\n  Problem {p_idx}/{len(problems)} [{src}]: "
                      f"obs {obs_label}")
                print(f"    Ground truth: {gt_label}  "
                      f"(size {len(ground_truth)})")

                for tool_name in tools:
                    key = (onto_name, f"eq{p_idx}", tool_name)
                    summary["total"] += 1
                    print(f"    {tool_name}... ", end="", flush=True)

                    # run_tool measures the child process's peak RSS itself
                    # (CATS/LETHE) and returns it as the third value; it is
                    # None for AAA, timeouts, errors, or if psutil is absent.
                    hypothesis, runtime, peak_mb = run_tool(
                        tool_name, obs_path, allowed_sig, "",
                        observation=[observation])
                    peak_mem_mb = round(peak_mb, 2) if peak_mb is not None else None
                    # --- save explanations to inspect (one file per run) ---
                    if hypothesis:
                        _ed = Path("explanations");
                        _ed.mkdir(exist_ok=True)
                        _ef = _ed / f"{onto_name}_eq{p_idx}_{tool_name}.txt"
                        with open(_ef, "w", encoding="utf-8") as _f:
                            _f.write(f"# {onto_name} | eq{p_idx} | {tool_name} | "
                                     f"obs={obs_label} | gt={gt_label} | "
                                     f"count={len(hypothesis)} | "
                                     f"runtime={runtime}\n\n")
                            for _h in hypothesis:
                                _f.write(str(_h) + "\n")

                    timed_out = runtime == "TIMEOUT"
                    is_error  = isinstance(runtime, str)

                    if timed_out:
                        summary["timed_out"] += 1
                    elif is_error:
                        summary["error"] += 1
                    else:
                        summary["solved"] += 1

                    if is_error:
                        print(runtime)
                        row = {
                            "runtime_s": runtime,
                            "hypothesis_size": None,
                            "hypothesis_class_count": None,
                            "recovery_rate": None,
                            "recovered_set_precision": None,
                            "valid_explanation": None,
                            "timed_out": timed_out,
                            "peak_memory_mb": peak_mem_mb}
                        results[key] = row
                        append_result(key, row)
                        continue

                    try:
                        recovery_rate, recovered_set_precision = \
                            compute_metrics(obs_onto, ground_truth, hypothesis)
                    except Exception:
                        recovery_rate, recovered_set_precision = None, None

                    hyp_class_count = count_hypothesis_classes(
                        hypothesis, obs_onto)
                    # Explanation size with conjunctions decomposed — LETHE
                    # packs a multi-assertion explanation into ONE complex
                    # axiom, so len(hypothesis) under-counts it.
                    hyp_assertions = count_hypothesis_assertions(
                        hypothesis, obs_onto)

                    # Semantic validity: does K u H actually entail the
                    # observation? This is the true abduction criterion and
                    # credits valid-but-non-matching hypotheses (e.g. LETHE's).
                    valid_expl = None
                    if hypothesis:
                        try:
                            valid_expl, _reason = is_valid_explanation(
                                obs_path, hypothesis, observation, obs_onto)
                        except Exception:
                            valid_expl = None

                    mem_str = f"{peak_mem_mb}MB" if peak_mem_mb is not None else "n/a"
                    print(f"{runtime:.1f}s | hyp={hyp_assertions} | "
                          f"classes={hyp_class_count} | "
                          f"recovery={recovery_rate} | "
                          f"valid={valid_expl} | "
                          f"mem={mem_str}")

                    row = {
                        "runtime_s":               runtime,
                        "hypothesis_size":         hyp_assertions,
                        "hypothesis_class_count":  hyp_class_count,
                        "recovery_rate":           recovery_rate,
                        "recovered_set_precision": recovered_set_precision,
                        "valid_explanation":       valid_expl,
                        "timed_out":               False,
                        "peak_memory_mb":          peak_mem_mb,
                    }
                    results[key] = row
                    append_result(key, row)

            summary["ontologies_processed"] += 1

        except KeyboardInterrupt:
            print("\n[interrupted by user — partial results saved]")
            break
        except Exception as e:
            print(f"  [ontology failed: {type(e).__name__}: {e}]")
            summary["ontologies_failed"] += 1
            continue

    print(f"\n{'='*50}")
    print(f"EXPERIMENT SUMMARY")
    print(f"{'='*50}")
    print(f"  Ontologies processed: {summary['ontologies_processed']}")
    print(f"  Ontologies failed:    {summary['ontologies_failed']}")
    print(f"  Tool runs total:      {summary['total']}")
    total = max(summary['total'], 1)
    print(f"  Solved:               {summary['solved']} "
          f"({100*summary['solved']//total}%)")
    print(f"  Timeouts:             {summary['timed_out']}")
    print(f"  Errors:               {summary['error']}")
    print(f"\nResults written incrementally to results/results.csv")
    stopJVM()


if __name__ == "__main__":
    main()