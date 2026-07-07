# ontology_utils.py
from owlapy.owl_ontology import SyncOntology
from owlapy.owl_axiom import OWLClassAssertionAxiom


def get_class_assertions(onto: SyncOntology) -> list:
    """
    Return only class assertions with named classes and named individuals.
    Skips complex class expressions (OWLObjectSomeValuesFrom etc.)
    and owl:Thing (trivially entailed, useless for abduction).
    """
    OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
    result = []
    for java_axiom in onto.owlapi_ontology.getABoxAxioms(
            onto._get_imports_enum(True)):
        try:
            mapped = onto.mapper.map_(java_axiom)
            if isinstance(mapped, OWLClassAssertionAxiom):
                ind = mapped.get_individual()
                cls = mapped.get_class_expression()
                # Only keep named classes and named individuals
                if not hasattr(ind, 'iri') or not hasattr(cls, 'iri'):
                    continue
                # Skip owl:Thing
                if cls.iri.as_str() == OWL_THING:
                    continue
                result.append(mapped)
        except Exception:
            pass
    return result


def save_ontology(onto: SyncOntology, path: str) -> None:
    print(f"Saving Ontology into {path}")
    onto.save(path)