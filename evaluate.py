# evaluate.py
from owlapy.owl_ontology import SyncOntology
from owlapy.owl_axiom import OWLClassAssertionAxiom
from owlapy.owl_individual import OWLNamedIndividual
from owlapy.class_expression import OWLClass, OWLObjectIntersectionOf
from owlapy.iri import IRI
import re


_ATOMIC_CA = re.compile(r'ClassAssertion\(<([^>]+)>\s+<([^>]+)>\)')
_SHORT_CA  = re.compile(r'(\w+)\((\w+)\)')
_FN_KEYWORDS = (
    "ClassAssertion(", "ObjectPropertyAssertion(",
    "DataPropertyAssertion(", "NegativeObjectPropertyAssertion(",
    "NegativeDataPropertyAssertion(", "SubClassOf(",
    "SameIndividual(", "DifferentIndividuals(",
)


def _flatten_conjuncts(ce):
    if isinstance(ce, OWLObjectIntersectionOf):
        out = []
        for op in ce.operands():
            out.extend(_flatten_conjuncts(op))
        return out
    return [ce]


def _ce_key(ce) -> str:
    """Hashable identity for a class expression: its IRI when the
    expression is a NAMED class, otherwise its full functional-syntax
    string. Lets complex expressions (unions, existentials) take part in
    set operations even though they have no IRI."""
    return ce.iri.as_str() if isinstance(ce, OWLClass) else str(ce)


def _split_axiom(ax: OWLClassAssertionAxiom) -> list:
    """Decompose one class assertion into per-conjunct class assertions.
    ClassAssertion(D u E)(a) -> [D(a), E(a)]. A NAMED conjunct becomes a
    plain class membership; a COMPLEX conjunct (existential, union, ...) is
    KEPT WHOLE as its own assertion, so a forgetting-based hypothesis such
    as ClassAssertion(exists teacherOf.Thing)(a) counts as one assertion
    instead of being silently dropped."""
    ind = ax.get_individual()
    return [OWLClassAssertionAxiom(ind, sub)
            for sub in _flatten_conjuncts(ax.get_class_expression())]


def _class_assertions_of(onto: SyncOntology) -> list:
    res = []
    for jax in onto.owlapi_ontology.getABoxAxioms(
            onto._get_imports_enum(True)):
        try:
            m = onto.mapper.map_(jax)
            if isinstance(m, OWLClassAssertionAxiom):
                res.append(m)
        except Exception:
            pass
    return res


def _parse_short_form(piece: str, sig: dict):
    if not piece:
        return None
    if ": " in piece and piece.startswith("http"):
        a, c = piece.split(": ", 1)
        return OWLClassAssertionAxiom(
            OWLNamedIndividual(IRI.create(a.strip())),
            OWLClass(IRI.create(c.strip())))
    m = _SHORT_CA.match(piece)
    if m:
        cls_iri = sig.get(m.group(1)) or next(
            (v for k, v in sig.items() if k.lower() == m.group(1).lower()),
            None)
        ind_iri = sig.get(m.group(2)) or next(
            (v for k, v in sig.items() if k.lower() == m.group(2).lower()),
            None)
        if cls_iri and ind_iri:
            return OWLClassAssertionAxiom(
                OWLNamedIndividual(ind_iri), OWLClass(cls_iri))
    return None


def _parse_hypothesis_axioms(hypothesis: list, base: SyncOntology) -> list:
    sig = {e.iri.remainder: e.iri for e in base.get_signature()}
    result = []
    fn_strings = []

    for item in hypothesis:
        if isinstance(item, OWLClassAssertionAxiom):
            result.extend(_split_axiom(item))
            continue
        if not isinstance(item, str):
            continue
        s = item.strip()
        if s.startswith(_FN_KEYWORDS):
            fn_strings.append(s)
        else:
            for piece in s.split(","):
                ax = _parse_short_form(piece.strip(), sig)
                if ax is not None:
                    result.append(ax)

    if fn_strings:
        hyp_onto = _hypothesis_as_ontology(fn_strings)
        if hyp_onto is not None:
            for ax in _class_assertions_of(hyp_onto):
                result.extend(_split_axiom(ax))
        else:
            for s in fn_strings:
                m = _ATOMIC_CA.match(s)
                if m:
                    result.append(OWLClassAssertionAxiom(
                        OWLNamedIndividual(IRI.create(m.group(2))),
                        OWLClass(IRI.create(m.group(1)))))
    return result


def compute_metrics(observation_onto: SyncOntology,
                    ground_truth: list,
                    hypothesis: list) -> tuple:
    """
    Recovery Rate            = |GT cap H_named| / |GT|
    Recovered-Set Precision  = |GT cap H_named| / |H_all|

    Only NAMED-class assertions can match the (named) ground truth.
    COMPLEX assertions (unions / existentials from forgetting-based tools)
    can't be a named match, but they DO count toward the hypothesis size
    (the precision denominator), so a tool isn't rewarded for padding the
    answer with extra complex disjuncts. Direct set match, NOT entailment-
    based (that is is_valid_explanation's job).
    """
    if not hypothesis or not ground_truth:
        return None, None

    hyp_axioms = _parse_hypothesis_axioms(hypothesis, observation_onto)
    if not hyp_axioms:
        return None, None

    gt_pairs = {
        (ax.get_class_expression().iri.as_str(),
         ax.get_individual().iri.as_str())
        for ax in ground_truth
        if isinstance(ax, OWLClassAssertionAxiom)
    }

    named_pairs = set()   # only named-class assertions (can match GT)
    all_pairs = set()     # every distinct assertion (size / denominator)
    for ax in hyp_axioms:
        if not isinstance(ax, OWLClassAssertionAxiom):
            continue
        ce = ax.get_class_expression()
        ind_iri = ax.get_individual().iri.as_str()
        all_pairs.add((_ce_key(ce), ind_iri))
        if isinstance(ce, OWLClass):
            named_pairs.add((ce.iri.as_str(), ind_iri))

    if not all_pairs:
        return None, None

    recovered = len(gt_pairs & named_pairs)
    recovery_rate = recovered / len(gt_pairs) if gt_pairs else 0.0
    recovered_set_precision = recovered / len(all_pairs)

    return recovery_rate, recovered_set_precision


def count_hypothesis_classes(hypothesis: list, onto: SyncOntology) -> int:
    """Count unique class expressions (named or complex)."""
    axioms = _parse_hypothesis_axioms(hypothesis, onto)
    classes = {_ce_key(ax.get_class_expression())
               for ax in axioms
               if isinstance(ax, OWLClassAssertionAxiom)}
    return len(classes)


def count_hypothesis_assertions(hypothesis: list, onto: SyncOntology) -> int:
    """
    Number of class ASSERTIONS in the hypothesis, conjunctions decomposed
    and complex (union / existential) assertions counted as one each. A
    LETHE explanation asserting a conjunction D u E u F counts as 3; one
    asserting a single union or existential counts as 1 (it is no longer
    dropped).
    """
    return len(_parse_hypothesis_axioms(hypothesis, onto))


def _hypothesis_as_ontology(hypothesis: list,
                            tmp_path: str = "tmp/_hypothesis_reload.owl"):
    from pathlib import Path

    FN_KEYWORDS = (
        "ClassAssertion(", "ObjectPropertyAssertion(",
        "DataPropertyAssertion(", "NegativeObjectPropertyAssertion(",
        "NegativeDataPropertyAssertion(", "SubClassOf(",
        "SameIndividual(", "DifferentIndividuals(",
    )
    axiom_lines = [
        s.strip() for s in hypothesis
        if isinstance(s, str) and s.strip().startswith(FN_KEYWORDS)
    ]
    if not axiom_lines:
        return None

    doc = (
        "Prefix(owl:=<http://www.w3.org/2002/07/owl#>)\n"
        "Prefix(rdf:=<http://www.w3.org/1999/02/22-rdf-syntax-ns#>)\n"
        "Prefix(rdfs:=<http://www.w3.org/2000/01/rdf-schema#>)\n"
        "Prefix(xsd:=<http://www.w3.org/2001/XMLSchema#>)\n"
        "Ontology(<http://hypothesis.local/reload>\n"
        + "\n".join(axiom_lines) +
        "\n)\n"
    )
    Path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w") as f:
        f.write(doc)
    try:
        return SyncOntology(tmp_path)
    except Exception:
        return None


def is_valid_explanation(k_prime_path: str,
                         hypothesis: list,
                         observation,
                         base_onto: SyncOntology,
                         tmp_path: str = "tmp/_validity_check.owl") -> tuple:
    import jpype
    from pathlib import Path
    from owlapy.owl_reasoner import SyncReasoner

    try:
        onto = SyncOntology(k_prime_path)
        IRI_class = jpype.JClass("org.semanticweb.owlapi.model.IRI")
        java_onto = onto.owlapi_ontology
        manager   = java_onto.getOWLOntologyManager()
        factory   = manager.getOWLDataFactory()

        added = 0

        hyp_onto = _hypothesis_as_ontology(hypothesis)
        if hyp_onto is not None:
            for ax in list(hyp_onto.owlapi_ontology.getLogicalAxioms()):
                manager.addAxiom(java_onto, ax)
                added += 1

        if added == 0:
            hyp_axioms = _parse_hypothesis_axioms(hypothesis, base_onto)
            for ax in hyp_axioms:
                if not isinstance(ax, OWLClassAssertionAxiom):
                    continue
                ce = ax.get_class_expression()
                if not isinstance(ce, OWLClass):
                    continue   # complex assertions are handled by the reload path
                cls_iri = ce.iri.as_str()
                ind_iri = ax.get_individual().iri.as_str()
                cls_obj = factory.getOWLClass(IRI_class.create(cls_iri))
                ind_obj = factory.getOWLNamedIndividual(IRI_class.create(ind_iri))
                ax_obj  = factory.getOWLClassAssertionAxiom(cls_obj, ind_obj)
                manager.addAxiom(java_onto, ax_obj)
                added += 1

        if added == 0:
            return False, "empty or unparseable hypothesis"

        Path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        onto.save(tmp_path)

        reasoner = SyncReasoner(tmp_path, reasoner="HermiT")

        if not reasoner.has_consistent_ontology():
            return False, "K' u H is inconsistent"

        obs_cls = observation.get_class_expression()
        obs_ind = observation.get_individual().iri.as_str()
        instances = list(reasoner.instances(obs_cls, timeout=10000))
        inst_iris = {ind.iri.as_str() for ind in instances}

        if obs_ind in inst_iris:
            return True, "valid explanation"
        return False, "K' u H does not entail observation"
    except Exception as e:
        return False, f"reasoner error: {type(e).__name__}: {e}"