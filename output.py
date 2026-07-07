# output.py
import csv
from pathlib import Path

FIELDNAMES = [
    "ontology_name", "strategy", "tool_name",
    "runtime_s", "hypothesis_size", "hypothesis_class_count",
    "recovery_rate", "recovered_set_precision",
    "valid_explanation", "timed_out", "peak_memory_mb"
]


def _ensure_header(path: str) -> None:
    """Make sure the CSV file exists with the header row written."""
    p = Path(path)
    p.parent.mkdir(exist_ok=True)
    if not p.exists() or p.stat().st_size == 0:
        with open(p, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()


def init_results(path: str = "results/results.csv") -> None:
    """Reset results file at the start of an experiment run."""
    p = Path(path)
    p.parent.mkdir(exist_ok=True)
    with open(p, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()


def append_result(key: tuple, data: dict,
                  path: str = "results/results.csv") -> None:
    """Append a single result row to the CSV immediately. Survives crashes."""
    _ensure_header(path)
    ontology_name, strategy, tool_name = key
    with open(path, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDNAMES).writerow({
            "ontology_name":          ontology_name,
            "strategy":               strategy,
            "tool_name":              tool_name,
            "runtime_s":              data.get("runtime_s"),
            "hypothesis_size":        data.get("hypothesis_size"),
            "hypothesis_class_count": data.get("hypothesis_class_count"),
            "recovery_rate":          data.get("recovery_rate"),
            "recovered_set_precision":data.get("recovered_set_precision"),
            "valid_explanation":      data.get("valid_explanation"),
            "timed_out":              data.get("timed_out", False),
            "peak_memory_mb":         data.get("peak_memory_mb"),
        })


def save_results(results: dict,
                 path: str = "results/results.csv") -> None:
    """Batch write — kept for backward compatibility. Overwrites file."""
    Path(path).parent.mkdir(exist_ok=True)
    init_results(path)
    for key, data in results.items():
        append_result(key, data, path)