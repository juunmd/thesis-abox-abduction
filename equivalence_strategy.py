# equivalence_strategy.py

from collections import namedtuple
from pathlib import Path

import jpype

from owlapy.owl_axiom import (OWLClassAssertionAxiom, OWLEquivalentClassesAxiom,
                              OWLSubClassOfAxiom)
from owlapy.owl_individual import OWLNamedIndividual
from owlapy.class_expression import OWLClass, OWLObjectIntersectionOf
from owlapy.iri import IRI
from owlapy.owl_reasoner import SyncReasoner

from ontology_utils import save_ontology
from strategies import _copy_ontology


FRESH_IND_IRI = "http://abduction.local/a"

OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


LETHE_EXTRA_FORGET_PATH = "tmp/_lethe_extra_forget.txt"


MAX_PROBLEMS_PER_ONTOLOGY = 5


INCLUDE_SUBCLASS_PROBLEMS = True


EqProblem = namedtuple(
    "EqProblem",
    ["observation",
     "ground_truth",
     "allowed_sig",
     "obs_path",
     "obs_onto",
     "c_iri",
     "e_iris",
     "a_iri",
     "source"],
)


def _named_conjuncts(ce):
    """
    If `ce` is a single named class, return [its IRI].
    If `ce` is a conjunction of named classes, return [iri, iri, ...].
    Otherwise (existential, union, complement, nested anonymous, ...)
    return None — meaning the definition can't be written as plain class
    assertions, so the equivalence is not usable in this setting.
    """
    if isinstance(ce, OWLClass):
        return [ce.iri.as_str()]
    if isinstance(ce, OWLObjectIntersectionOf):
        iris = []
        for op in ce.operands():
            if isinstance(op, OWLClass):
                iris.append(op.iri.as_str())
            else:
                return None
        return iris if iris else None
    return None


def _pairs_from_ces(ces):
    """
    Given the operands of one EquivalentClasses axiom, yield
    (C_iri, [definition_conjunct_iris]) where one operand is a named
    class C (the observation) and the other is a named class or a
    conjunction of named classes (C's definition).

    Only binary equivalences are handled (the overwhelmingly common
    case). Axioms with more than two operands are skipped.
    """
    if len(ces) != 2:
        return
    a, b = ces[0], ces[1]
    a_named = isinstance(a, OWLClass)
    b_named = isinstance(b, OWLClass)
    a_conj = _named_conjuncts(a)
    b_conj = _named_conjuncts(b)


    if a_named and b_conj is not None:
        yield a.iri.as_str(), b_conj
    elif b_named and a_conj is not None:
        yield b.iri.as_str(), a_conj


def _equivalence_pairs(onto):
    """
    Yield deduplicated (C_iri, [definition_iris]) over all usable
    equivalence axioms of `onto`. Degenerate cases where C is among its
    own definition are dropped.
    """
    seen_c = set()
    try:
        tbox = list(onto.get_tbox_axioms())
    except Exception as e:
        print(f"  (could not read TBox axioms: {e})")
        return
    # SyncOntology.equivalent_classes_axioms(c) is PER-CLASS (needs a class
    # argument), so we enumerate the whole TBox and keep the equivalences.
    axioms = [ax for ax in tbox
              if isinstance(ax, OWLEquivalentClassesAxiom)]

    for ax in axioms:
        try:
            ces = list(ax.class_expressions())
        except Exception:
            continue
        for c_iri, e_iris in _pairs_from_ces(ces):
            if c_iri == OWL_THING:
                continue
            if c_iri in e_iris:
                continue
            if c_iri in seen_c:
                continue
            seen_c.add(c_iri)
            yield c_iri, e_iris


def _subclass_pairs(onto, skip_classes):
    """
    Yield (C_iri, [D_iri]) for each named SubClassOf axiom  D ⊑ C  where
    BOTH sides are named classes. The observation is the SUPERCLASS C(a)
    and the intended explanation is the named subclass D(a) — a plain
    class assertion every tool can express (D ⊑ C  ⇒  K ∪ {D(a)} ⊨ C(a)).

    One problem per superclass C (deduplicated), using the
    alphabetically-smallest subclass IRI as the intended explanation, so
    runs are reproducible and we never re-observe the same C(a) twice.
    Classes already covered by an equivalence (`skip_classes`) and ⊤ are
    not used. A superclass with several subclasses has several valid
    explanations, so recovery here is inherently partial and semantic
    validity is the primary metric.
    """
    by_super = {}
    try:
        tbox = list(onto.get_tbox_axioms())
    except Exception:
        return
    for ax in tbox:
        if not isinstance(ax, OWLSubClassOfAxiom):
            continue
        sub, sup = ax.get_sub_class(), ax.get_super_class()
        if not (isinstance(sub, OWLClass) and isinstance(sup, OWLClass)):
            continue
        c_iri, d_iri = sup.iri.as_str(), sub.iri.as_str()
        if c_iri == OWL_THING or d_iri == OWL_THING or c_iri == d_iri:
            continue
        if c_iri in skip_classes:
            continue
        by_super.setdefault(c_iri, set()).add(d_iri)

    for c_iri in sorted(by_super):
        yield c_iri, [sorted(by_super[c_iri])[0]]


def _copy_with_fresh_individual(onto, a_iri, out_path):
    """
    Copy `onto` to `out_path` and declare `a_iri` as a named individual.
    No class assertion is added, so the observation C(a) remains NON-
    entailed. Returns the loaded SyncOntology copy.
    """
    Path(out_path).parent.mkdir(exist_ok=True)
    obs = _copy_ontology(onto, out_path)

    IRI_class = jpype.JClass("org.semanticweb.owlapi.model.IRI")
    java_onto = obs.owlapi_ontology
    manager   = java_onto.getOWLOntologyManager()
    factory   = manager.getOWLDataFactory()

    ind  = factory.getOWLNamedIndividual(IRI_class.create(a_iri))
    decl = factory.getOWLDeclarationAxiom(ind)
    manager.addAxiom(java_onto, decl)

    save_ontology(obs, out_path)
    return obs


def _filter_entailed(pairs, obs_path, a_iri):
    """
    Keep only observations C(a) that pose a well-formed abduction problem.
    Two cases are dropped:

    (a) ALREADY ENTAILED — K ⊨ C(a). A fresh `a` *should* guarantee
        K ⊭ C(a), but a class forced on every individual (⊤ ⊑ C, common
        around partition / covering axioms) breaks that: the abduction is
        degenerate (validity vacuous, tools hand back arbitrary assertions).

    (b) UNSATISFIABLE — C ⊑ ⊥. Then K ∪ {C(a)} is inconsistent, so the
        observation can never be explained, every hypothesis is vacuously
        "valid", and reasoners blow up — LETHE in particular throws
        InconsistentOntologyException inside its hypothesis simplifier.
        These C are real in ORE ontologies, so they must be filtered.
    """
    Path("tmp").mkdir(exist_ok=True)
    open(LETHE_EXTRA_FORGET_PATH, "w").close()
    try:
        reasoner = SyncReasoner(obs_path, reasoner="HermiT")
    except Exception as e:
        print(f"  (degeneracy guard disabled — reasoner error: {e})")
        return pairs
    if not reasoner.has_consistent_ontology():
        print("  (degeneracy guard: ontology is INCONSISTENT — every "
              "observation is entailed; skipping all equivalence problems)")
        return []


    try:
        unsat = [c.iri.as_str() for c in reasoner.unsatisfiable_classes()
                 if c.iri.as_str() != OWL_NOTHING]
    except Exception:
        unsat = []
    if unsat:
        with open(LETHE_EXTRA_FORGET_PATH, "w") as _f:
            _f.write("\n".join(unsat) + "\n")
        print(f"  ({len(unsat)} unsatisfiable class(es) in ontology — "
              f"LETHE will forget them)")

    kept = []
    n_entailed = 0
    n_unsat = 0
    for c_iri, e_iris, source in pairs:
        c_obj = OWLClass(IRI.create(c_iri))
        short = c_iri.rsplit('#', 1)[-1].rsplit('/', 1)[-1]

        try:
            insts = reasoner.instances(c_obj, direct=False, timeout=10000)
            entailed = any(i.iri.as_str() == a_iri for i in insts)
        except Exception:
            entailed = False
        if entailed:
            print(f"    skip (degenerate, K |= {short}(a))")
            n_entailed += 1
            continue

        try:
            sat = reasoner.is_satisfiable(c_obj)
        except Exception:
            sat = True
        if not sat:
            print(f"    skip (unsatisfiable class, {short} is subseteq Nothing)")
            n_unsat += 1
            continue


        try:
            gt_unsat = any(
                not reasoner.is_satisfiable(OWLClass(IRI.create(e)))
                for e in e_iris)
        except Exception:
            gt_unsat = False
        if gt_unsat:
            print(f"    skip (unsatisfiable ground-truth class for {short})")
            n_unsat += 1
            continue

        kept.append((c_iri, e_iris, source))

    print(f"  degeneracy guard (HermiT): {len(kept)} kept, "
          f"{n_entailed} entailed, {n_unsat} unsatisfiable")
    return kept


def build_equivalence_problems(onto, full_onto_path,
                               max_problems=MAX_PROBLEMS_PER_ONTOLOGY):
    """
    Build abduction problems for `onto` under Patrick's setting, optionally
    broadened with named SubClassOf axioms (see INCLUDE_SUBCLASS_PROBLEMS).

    Returns a list of EqProblem. Empty if the ontology has no usable
    equivalence or subclass axiom (so the caller should skip it).

    Equivalence-derived problems are ordered first, then by definition size
    (size-1 first), so a small `max_problems` keeps the cleanest problems.
    """
    eq_pairs = [(c, e, "equiv") for c, e in _equivalence_pairs(onto)]
    if INCLUDE_SUBCLASS_PROBLEMS:
        covered = {c for c, _, _ in eq_pairs}
        sub_pairs = [(c, e, "subclass")
                     for c, e in _subclass_pairs(onto, covered)]
    else:
        sub_pairs = []
    pairs = eq_pairs + sub_pairs
    if not pairs:
        return []

    out_path = f"tmp/{Path(full_onto_path).stem}_eqobs.owl"
    obs_onto = _copy_with_fresh_individual(onto, FRESH_IND_IRI, out_path)

    pairs = _filter_entailed(pairs, out_path, FRESH_IND_IRI)
    if not pairs:
        return []

    pairs.sort(key=lambda p: (p[2] != "equiv", len(p[1]), p[0]))
    if len(pairs) > max_problems:
        pairs = pairs[:max_problems]

    full_sig = {e.iri.as_str() for e in onto.get_signature()}
    a_ind = OWLNamedIndividual(IRI.create(FRESH_IND_IRI))

    problems = []
    for c_iri, e_iris, source in pairs:
        observation = OWLClassAssertionAxiom(
            a_ind, OWLClass(IRI.create(c_iri)))
        ground_truth = [
            OWLClassAssertionAxiom(a_ind, OWLClass(IRI.create(e)))
            for e in e_iris
        ]

        allowed_sig = full_sig - {c_iri}

        problems.append(EqProblem(
            observation=observation,
            ground_truth=ground_truth,
            allowed_sig=allowed_sig,
            obs_path=out_path,
            obs_onto=obs_onto,
            c_iri=c_iri,
            e_iris=e_iris,
            a_iri=FRESH_IND_IRI,
            source=source,
        ))
    return problems