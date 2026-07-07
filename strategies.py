# strategies.py
import random
from owlapy.owl_ontology import SyncOntology
from owlapy.owl_axiom import OWLClassAssertionAxiom, OWLObjectPropertyAssertionAxiom
from owlapy.owl_individual import OWLNamedIndividual
from owlapy.iri import IRI
from ontology_utils import get_class_assertions, save_ontology

def _copy_ontology(original: SyncOntology, new_path: str) -> SyncOntology:
    """Create a full copy of an ontology at a new path, skipping unmappable axioms."""
    copy = SyncOntology(IRI.create(f"file:/{new_path}"), load=False)
    for axiom in original.owlapi_ontology.getTBoxAxioms(
            original._get_imports_enum(True)):
        try:
            mapped = original.mapper.map_(axiom)
            copy.add_axiom(mapped)
        except Exception:
            pass
    for axiom in original.owlapi_ontology.getABoxAxioms(
            original._get_imports_enum(True)):
        try:
            mapped = original.mapper.map_(axiom)
            copy.add_axiom(mapped)
        except Exception:
            pass
    return copy

# ── Prompt 5: Strategy A — sig(O) \ sig(α) ──────────────────
def apply_strategy_a(onto: SyncOntology, alpha: list) -> tuple:
    """Remove alpha from a copy; allowed signature = sig(O) - sig(alpha)."""
    sig_o = {entity.iri for entity in onto.get_signature()}
    sig_alpha = set()
    for axiom in alpha:
        sig_alpha.add(axiom.get_individual().iri)
        sig_alpha.add(axiom.get_class_expression().iri)
    allowed_signature = sig_o - sig_alpha
    return alpha, allowed_signature  # (ground_truth, allowed_signature)

# ── Prompt 6: Strategy B — random 50% removal ───────────────
def apply_strategy_b(onto: SyncOntology, onto_path: str,
                     out_path: str = "observation_b.owl",
                     seed: int = 42) -> list:
    """Remove 50% of class assertions randomly; save observation ontology."""
    random.seed(seed)
    all_assertions = get_class_assertions(onto)
    ground_truth = random.sample(all_assertions, len(all_assertions) // 2)
    obs = _copy_ontology(onto, out_path)
    obs.remove_axiom(ground_truth)
    save_ontology(obs, out_path)
    return ground_truth

# ── Prompt 7: Strategy C — individual removal ────────────────
def apply_strategy_c(onto: SyncOntology, x: OWLNamedIndividual,
                     out_path: str = None) -> list:
    """Remove all axioms mentioning individual x; save observation ontology."""
    ground_truth = []
    for axiom in onto.get_abox_axioms():
        if isinstance(axiom, OWLClassAssertionAxiom):
            if axiom.get_individual() == x:
                ground_truth.append(axiom)
        elif isinstance(axiom, OWLObjectPropertyAssertionAxiom):
            if axiom.get_subject() == x or axiom.get_object() == x:
                ground_truth.append(axiom)
    path = out_path or f"observation_{x.iri.remainder}.owl"
    obs = _copy_ontology(onto, path)
    obs.remove_axiom(ground_truth)
    save_ontology(obs, path)
    return ground_truth