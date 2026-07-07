    # config.py
from owlapy.owl_ontology import SyncOntology
from owlapy.owl_reasoner import SyncReasoner
from owlapy.static_funcs import stopJVM

# ── Experiment settings ──────────────────────────────────────
ONTOLOGY_DIR = "ontologies/"
RESULTS_PATH = "results/results.csv"
TIMEOUT      = 300  # seconds per tool call
RANDOM_SEED  = 42

# Manually specify OWL profile per ontology
ONTOLOGY_PROFILES = {
    "father.owl":     "EL",
    "university.owl": "EL",
    "pizza.owl":      "EL",
}

def load_ontology(path: str) -> SyncOntology:
    return SyncOntology(path)

def get_signature(onto: SyncOntology) -> set:
    return {entity.iri for entity in onto.get_signature()}

def load_reasoner(path: str, profile: str) -> SyncReasoner:
    reasoner = "ELK" if profile == "EL" else "HermiT"
    return SyncReasoner(ontology=path, reasoner=reasoner)