## Repository structure

```
.
.
├── README.md
├── LICENSE
├── environment.yml
├── .gitignore
├── scan_ontologies.py          # scan corpus for candidate ontologies
├── profile_ontologies.py       # profile / classify candidates
├── select_best.py              # apply selection criteria -> final set
├── main.py                     # main pipeline entry point
├── simple_experiment.py        # reasoning-light replication run
├── plot_results.py             # coverage/runtime figures
├── tools/                      # place the solver jars here (git-ignored)
│   └── .gitkeep
├── ontologies/                 # place ORE 2015 ontologies here (git-ignored)
│   └── .gitkeep
├── candidate_counts.csv        # selection artifact (kept in git)
└── results/                    # experiment output CSVs (kept in git)
    ├── results.csv
    ├── results_main_run.csv
    └── simple_results.csv
```

---

## Requirements

- **Python 3.11** with the packages in `environment.yml`
  (key pins: `owlapy==1.6.5`, `jpype1`)
- **Java 11**: required by all three solver jars
- **WSL (Ubuntu)**: required **only** for AAA (see quirks below)
- Reasoning uses **HermiT** (via OWLAPY's `SyncReasoner`) for entailment and
  consistency checks; **CATS** uses **JFact** internally.


## Setup

```bash
# 1. clone
git clone https://github.com/<username>/<repo>.git
cd <repo>

# 2. create the environment
conda env create -f environment.yml
conda activate thesis-abduction

# 3. confirm Java 11
java -version    # should report 11.x

# 4. drop the jars into tools/ and the corpus into corpus/ (see table above)
```

---

## Running the experiments

```bash
# 1. select ontologies from the corpus (writes results/candidate_counts.csv
#    and results/selected_ontologies.csv)
python select_ontologies.py

# 2. run the main evaluation (builds problems, invokes all three tools,
#    writes per-invocation rows to results/)
python <run_experiment>.py

# 3. (optional) the reasoning-light replication run
python simple_experiment.py

# 4. (optional) regenerate the figures
python <plotting>.py
```

Results are written incrementally to CSV after each run, so an interrupted
experiment can be resumed.

---

## Expected outputs

With the final selection of **23 ontologies** (22 ORE/LUBM + LUBM), the pipeline
generates ~**112 abduction problems** and **336 tool invocations** (112 × 3).
Each CSV row is one tool invocation on one problem, with status
`solved / empty / timeout / error` plus recovery, precision, runtime, and size.

Ballpark from the thesis run (will vary with machine and timeouts): LETHE solves
the most problems, CATS is intermediate, AAA solves very few on this corpus.

---

## Known platform quirks

These cost real debugging time — read before reproducing:

- **AAA requires WSL.** Apache Jena 2.x rejects uppercase Windows drive letters
  as invalid URI schemes, so AAA cannot run natively on Windows. It is invoked
  through `wsl java ...` with a `_to_wsl_path()` helper that rewrites paths.
- **AAA `-abd` signature length limit.** The abducible signature is passed as a
  comma-separated IRI list via `-abd`. When that string exceeds ~28,000
  characters it blows the Windows command-line limit, so `-abd` is omitted and
  AAA runs on the full signature (much larger search space → frequent timeouts).
  This is itself reported as an evaluation finding.
- **CATS input syntax.** CATS needs **prefix-form Manchester syntax** with
  explicit prefix declarations in its config. Full-IRI angle-bracket form causes
  exit code 2. CATS was run with `-aI:i:a -n:false -alg:mxp` and JFact as the
  back-end reasoner.
- **CATS timeouts must differ.** CATS's internal `-t` timeout and the subprocess
  wrapper timeout must **not** be equal — give the wrapper ~60s of headroom, or
  runs are misclassified.
- **LETHE signature semantics.** LETHE receives the observed class `C` as the
  **forgetting** signature (not an abducible signature): it forgets `C` and
  computes an explanation over the remaining vocabulary. Non-`ALC` axioms are
  stripped before execution.
- **OWLAPY 1.6.5 API.** Use `has_consistent_ontology()` (not `is_consistent()`)
  on `SyncReasoner`. Adding axioms to an ontology must go through the **raw Java
  OWL API factory via jpype** — the high-level OWLAPY API is insufficient here.
- **Hardcoded values to check.** The fresh-individual IRI is
  `http://abduction.local/a`; the random seed is fixed for reproducible
  sampling. Make sure no absolute local paths (e.g. `C:\Users\...`) remain —
  move them to config or CLI arguments before publishing.

---

## License

Source code: MIT (see `LICENSE`). The solver jars and ORE corpus are **not**
covered by this license and retain their own terms.

