# tools.py
import time
import subprocess
import re
import shutil
import threading
from pathlib import Path
from config import TIMEOUT

try:
    import psutil
except ImportError:
    psutil = None


def _split_iri(iri_str: str):
    """Split an IRI into (namespace_with_separator, local_name) for use
    in Manchester-syntax prefix declarations. Handles both #-separated
    and /-separated IRIs."""
    if "#" in iri_str:
        ns, local = iri_str.rsplit("#", 1)
        return ns + "#", local
    if "/" in iri_str:
        ns, local = iri_str.rsplit("/", 1)
        return ns + "/", local
    return "", iri_str


def _write_cats_config(ontology_path, observation, allowed_signature,
                       config_path="tmp/cats_input.in", cats_timeout=120):
    """
    Build the CATS config. Observation AND abducible individual use
    Manchester-style PREFIXED names: CATS's abducible parser rejects full
    IRIs (it resolves a prefix before the first ':'), so we declare prefix
    i: for the individual's namespace and reference it as i:<local>.

      -aI: i:<local>  restricts abducible individuals to the observation's
                      individual. With role assertions off (-r defaults false)
                      every explanation of C(i) is a concept assertion on i,
                      so this is lossless and collapses the level-1 search
                      from (all individuals) to one.
      -n: false       disables negated assertions (ground truth is positive).
    """
    Path(config_path).parent.mkdir(exist_ok=True)
    obs_str, ind_local = "", None
    if observation:
        ax = observation[0]
        try:
            cls_iri = ax.get_class_expression().iri.as_str()
            ind_iri = ax.get_individual().iri.as_str()
            cls_ns, cls_local = _split_iri(cls_iri)
            ind_ns, ind_local = _split_iri(ind_iri)
            obs_str = (
                f"Prefix: c: <{cls_ns}> "
                f"Prefix: i: <{ind_ns}> "
                f"Class: c:{cls_local} "
                f"Individual: i:{ind_local} "
                f"Types: c:{cls_local}"
            )
        except Exception as e:
            print(f"CATS obs build error: {e}")
    with open(config_path, "w") as f:
        f.write(f"-f: {ontology_path}\n")
        f.write(f"-o: {obs_str}\n")
        if ind_local:
            f.write(f"-aI: i:{ind_local}\n")
        f.write(f"-n: false\n")
        f.write("-alg: mxp\n")
        f.write(f"-d: 2\n")
        f.write(f"-t: {cats_timeout}\n")
    return config_path


def _parse_cats_output(logs_dir):
    explanations = []
    logs = Path(logs_dir)
    final_logs = list(logs.rglob("*_final.log"))
    if not final_logs:
        return []
    latest = max(final_logs, key=lambda f: f.stat().st_mtime)
    with open(latest, "r") as f:
        for line in f:
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            if "{" in line and "}" in line:
                outer = line[line.index("{")+1: line.rindex("}")]
                for match in re.findall(r'\{([^}]+)\}', outer):
                    expl = match.strip()
                    if expl:
                        explanations.append(expl)
    return explanations


def _write_lethe_files(observation, allowed_signature):
    Path("tmp").mkdir(exist_ok=True)
    obs_path = "tmp/lethe_observation.owl"
    lines = [
        "Prefix(:=<http://obs#>)",
        "Prefix(owl:=<http://www.w3.org/2002/07/owl#>)",
        "Ontology(<http://obs#>"
    ]
    obs_class_iris = []
    for ax in observation:
        try:
            cls_iri = ax.get_class_expression().iri.as_str()
            ind_iri = ax.get_individual().iri.as_str()
            lines.append(f"  ClassAssertion(<{cls_iri}> <{ind_iri}>)")
            obs_class_iris.append(cls_iri)
        except Exception:
            pass
    lines.append(")")
    with open(obs_path, "w") as f:
        f.write("\n".join(lines))

    concept_path = "tmp/lethe_concepts.txt"
    role_path    = "tmp/lethe_roles.txt"
    # LETHE's signature file is the FORGETTING signature (names to ELIMINATE
    # / non-abducibles): forget the observation's class C so that LETHE
    # abduces an explanation over the remaining signature instead of just
    # echoing C(a).
    forget = list(obs_class_iris)
    with open(concept_path, "w") as f:
        for iri in forget:
            f.write(f"{iri}\n")
    with open(role_path, "w") as f:
        pass
    return obs_path, concept_path, role_path


def _parse_lethe_output():
    from owlapy.owl_ontology import SyncOntology
    hypotheses = []
    i = 0
    while Path(f"hypothesis_{i}.owl").exists():
        try:
            onto = SyncOntology(f"hypothesis_{i}.owl")
            axioms = list(onto.owlapi_ontology.getLogicalAxioms())
            for ax in axioms:
                hypotheses.append(str(ax))
        except Exception:
            with open(f"hypothesis_{i}.owl") as f:
                hypotheses.append(f.read())
        Path(f"hypothesis_{i}.owl").unlink()
        i += 1
    return hypotheses


def _parse_aaa_output(output_path):
    hypotheses = []
    if not Path(output_path).exists():
        return []
    with open(output_path, "r") as f:
        content = f.read()
    if "EXPLANATIONS---" not in content:
        return []
    expl_section = content.split("EXPLANATIONS---")[1]
    for match in re.findall(r'\{([^{}]+)\}', expl_section):
        expl = match.strip()
        if expl:
            hypotheses.append(expl)
    return hypotheses


def _to_wsl_path(windows_path):
    p = str(Path(windows_path).resolve()).replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:]


def _run_with_peak_rss(command, timeout, cwd=None):
    """Run a native subprocess, sampling the child process's RSS while it
    runs. Returns (stdout, stderr, returncode, peak_mb). peak_mb is None if
    psutil is not installed. Use only for native (non-WSL) commands: a WSL
    child's real process runs inside the VM and is not visible from here."""
    proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=cwd)
    peak = [0]

    def watch():
        try:
            p = psutil.Process(proc.pid)
            while proc.poll() is None:
                rss = p.memory_info().rss + sum(
                    c.memory_info().rss for c in p.children(recursive=True))
                peak[0] = max(peak[0], rss)
                time.sleep(0.05)
        except psutil.NoSuchProcess:
            pass

    if psutil is not None:
        threading.Thread(target=watch, daemon=True).start()
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    peak_mb = (peak[0] / 1048576) if psutil is not None else None
    return out, err, proc.returncode, peak_mb


def run_tool(tool_name, ontology_path, allowed_signature, namespace,
             observation=None, timeout=TIMEOUT):
    """Run an abduction tool on one problem.

    Returns (explanations, runtime_or_status, peak_memory_mb):
      - explanations:       list of hypothesis strings (possibly empty)
      - runtime_or_status:  float seconds on success, else "TIMEOUT" or
                            "ERROR: ..."
      - peak_memory_mb:     child-process peak RSS in MB for CATS/LETHE; None
                            for AAA, for timeouts/errors, or if psutil is not
                            installed.
    """
    Path("tmp").mkdir(exist_ok=True)

    if tool_name == "CATS":
        config_path = _write_cats_config(
            ontology_path,
            observation if isinstance(observation, list) else [],
            allowed_signature,
            cats_timeout=min(timeout, 120))
        command = ["java", "-Xmx4096m", "-jar", "tools/cats.jar", config_path]
        cwd = None

    elif tool_name == "LETHE":
        obs_path, concept_path, role_path = _write_lethe_files(
            observation if isinstance(observation, list) else [],
            allowed_signature)
        command = [
            "java", "-Xmx4096m", "-cp", "tools/lethe-abduction.jar",
            "uk.ac.man.cs.lethe.abduction.cmd.AbductionCmd",
            ontology_path, obs_path, concept_path, role_path]
        cwd = None

    elif tool_name == "AAA":
        obs_str = ""
        if observation and len(observation) > 0:
            ax = observation[0]
            try:
                cls_iri = ax.get_class_expression().iri.as_str()
                ind_iri = ax.get_individual().iri.as_str()
                obs_str = f"{ind_iri}: {cls_iri}"
            except Exception as e:
                print(f"AAA obs error: {e}")
        shutil.copy2(ontology_path, "tmp/aaa_input.owl")
        abd_str = ", ".join(allowed_signature)
        jar_wsl = _to_wsl_path("tools/AAA.jar")
        in_wsl  = _to_wsl_path("tmp/aaa_input.owl")
        out_wsl = _to_wsl_path("tmp/aaa_output.txt")
        command = [
            "wsl", "java", "-Xmx4096m", "-jar", jar_wsl,
            "-i", in_wsl, "-obs", obs_str,
            "-out", out_wsl, "-d", "2", "-t", str(timeout)]
        # Windows command-line limit is ~32767 chars (CreateProcess).
        # On large ontologies the full signature can exceed this. When
        # it would, omit -abd entirely (AAA falls back to using the
        # ontology's full signature). This means Strategy A's signature
        # restriction is not honored by AAA on large ontologies — a
        # real accessibility finding worth flagging in the writeup.
        WIN_CMD_BUDGET = 28000  # leave headroom for the rest of the argv
        if abd_str and len(abd_str) < WIN_CMD_BUDGET:
            command += ["-abd", abd_str]
        elif abd_str:
            print(f"[warn] AAA: signature too large for Windows command "
                  f"line ({len(abd_str)} chars), omitting -abd")
        cwd = None
    else:
        return [], "ERROR: No CLI available for this tool", None

    start = time.time()
    try:
        # CATS has its own internal timeout (-t in the config). Give the
        # subprocess wrapper extra headroom so CATS's internal timeout
        # fires first and it can write its log cleanly, rather than being
        # killed by the OS at exactly the same moment.
        sub_timeout = timeout + 60 if tool_name == "CATS" else timeout
        peak_mb = None
        if tool_name in ("CATS", "LETHE"):
            # native java: sample the child process's peak RSS while it runs
            out, err, returncode, peak_mb = _run_with_peak_rss(
                command, sub_timeout, cwd)
        else:
            # AAA runs inside WSL; its real java process is unreachable from
            # here, and AAA solves almost nothing, so memory is not measured.
            result = subprocess.run(command, timeout=sub_timeout,
                                    capture_output=True, text=True, cwd=cwd)
            out, err, returncode = result.stdout, result.stderr, result.returncode
        runtime = time.time() - start
        if returncode != 0:
            return [], f"ERROR: {err.strip()}", peak_mb
        if tool_name == "LETHE":
            explanations = _parse_lethe_output()
        elif tool_name == "AAA":
            explanations = _parse_aaa_output("tmp/aaa_output.txt")
        else:
            explanations = _parse_cats_output("logs")
        return explanations, runtime, peak_mb
    except subprocess.TimeoutExpired:
        return [], "TIMEOUT", None
    except Exception as e:
        return [], f"ERROR: {str(e)}", None