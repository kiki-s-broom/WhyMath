"""P3-42 runbook probe - summary of phase3_coverage JSON and DB-vs-bank problem id-space check.

Read-only. ASCII only on purpose (the runbook fetches this file by git and verifies its SHA-256).
Usage: p3_42_probe.py summary <json> | idspace <repo>
"""
import collections, glob, json, os, subprocess, sys

DB = ["docker", "exec", "-i", "whymath-pg", "psql", "-U", "whymath", "-d", "whymath",
      "-t", "-A", "-F", "|"]


def psql(sql):
    try:
        r = subprocess.run(DB + ["-c", sql], capture_output=True, encoding="utf-8",
                           errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        print("PSQL_FAILED reason=timeout60s")
        sys.exit(2)
    if r.returncode != 0:
        print("PSQL_FAILED rc=%s stderr=%s" % (r.returncode, r.stderr.strip()[:300]))
        sys.exit(2)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def summary(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    print("MEASURED=%s" % isinstance(d.get("hint_seat"), dict))
    print("JSON_EXIT_CODE_FIELD=%s" % d.get("exit_code"))
    print("PROBLEMS_SCANNED=%s" % d.get("problems_scanned"))
    print("HINT_SEAT=" + json.dumps(d.get("hint_seat")))
    comp = next((m for m in d.get("metrics", []) if m.get("key") == "concept_completeness"), None)
    if comp is None:
        print("COMPLETENESS=MISSING_IN_JSON")
    if comp is not None:
        print("COMPLETENESS value=%s met=%s/%s target=%s met_flag=%s" % (
            comp.get("value"), comp.get("met_count"), comp.get("population"),
            comp.get("target"), comp.get("met")))
    print("LINK_COUNTS_HINT=" + json.dumps(d.get("link_counts", {}).get("hint")))
    print("COMPLETENESS_MEASURABLE=" + json.dumps(d.get("completeness_measurable")))
    for w in d.get("warnings", []):
        print("WARNING: " + w)


def idspace(repo):
    n_all = int(psql("SELECT count(*) FROM hints")[0])
    n_hinted = int(psql("SELECT count(DISTINCT problem_id) FROM hints WHERE verified IS TRUE")[0])
    rows = [ln.split("|") for ln in psql(
        "SELECT DISTINCT p.problem_id, p.slug, coalesce(p.review_status::text, 'NULL') FROM hints h "
        "JOIN problem p ON p.problem_id = h.problem_id WHERE h.verified IS TRUE ORDER BY 1")]
    by_id, by_slug, scanned = {}, {}, 0
    pattern = os.path.join(repo, "data", "corpus", "problem_bank_*", "problems.jsonl")
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                scanned += 1
                pid, slug = row.get("problem_id"), row.get("slug")
                if isinstance(pid, str):
                    by_id[pid] = row.get("review_status")
                if isinstance(slug, str):
                    by_slug[slug] = pid
    if scanned == 0:
        print("BANK_SCANNED=0 - JSONL bank not found under %s" % repo)
        sys.exit(2)
    match, drift, absent = [], [], []
    for pid, slug, db_status in rows:
        if pid in by_id:
            match.append((pid, slug, db_status))
            continue
        if slug in by_slug:
            drift.append((pid, slug, by_slug[slug]))
            continue
        absent.append((pid, slug))
    print("DB_HINTS_ALL=%d" % n_all)
    print("DB_HINTED_PROBLEMS=%d" % n_hinted)
    print("JOINED_PROBLEM_ROWS=%d" % len(rows))
    print("BANK_ROWS_SCANNED=%d  BANK_IDS=%d" % (scanned, len(by_id)))
    print("ID_MATCH=%d" % len(match))
    print("SLUG_MATCH_BUT_ID_DIFFERS=%d" % len(drift))
    print("NOT_IN_BANK=%d" % len(absent))
    print("ID_MATCH_STATUS_DB_VS_JSONL=" + json.dumps(dict(collections.Counter(
        "%s/%s" % (st, by_id[pid]) for pid, _, st in match))))
    for pid, slug, bank_pid in drift[:5]:
        print("  DRIFT_SAMPLE db=%s bank=%s slug=%s" % (pid, bank_pid, slug))
    for pid, slug in absent[:5]:
        print("  ABSENT_SAMPLE db=%s slug=%s" % (pid, slug))
    print("VERDICT=" + verdict_of(n_hinted, len(rows), match, drift))


def verdict_of(n_hinted, n_rows, match, drift):
    if n_hinted == 0:
        return "NO_VERIFIED_HINTS"
    if n_rows != n_hinted:
        return "HINTS_WITHOUT_PROBLEM_ROW"
    if match:
        return "OVERLAP_OK"
    if drift:
        return "ID_SPACE_DRIFT"
    return "NOT_IN_BANK"


def main(argv):
    if len(argv) == 3 and argv[1] == "summary":
        summary(argv[2])
        return 0
    if len(argv) == 3 and argv[1] == "idspace":
        idspace(argv[2])
        return 0
    print("usage: p3_42_probe.py summary <json> | idspace <repo>")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
