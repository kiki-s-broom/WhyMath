"""반복 오답 4회 후 서빙의 누적 가설 신뢰도를 본인 반출(/v1/me/export)에서 읽는다(판정용 관측)."""
import json, sys, importlib.util, pathlib
import yaml
ROOT = pathlib.Path(__file__).resolve().parents[3]  # 저장소 루트(docs/reviews/<폴더>/ 에서 3단계 위)
spec = importlib.util.spec_from_file_location("_w1", ROOT / "tests/backend/api/test_week1_gate_closed_loop.py")
w1 = importlib.util.module_from_spec(spec); sys.modules["_w1"] = w1; spec.loader.exec_module(w1)
from whymath_backend.api._rate_limit import reset_store
REM = yaml.safe_load((ROOT / "data/corpus/phase3_remediation_v1/remediation.yaml").read_text(encoding="utf-8"))
FIX = {s["kebab_id"]: s["fixtures"] for s in REM["signatures"]}
kebab = sys.argv[1]; n = int(sys.argv[2])
reset_store()
with w1._client() as client:
    w1._erase_learner(client); auth = w1._login(client)
    wrongs = FIX[kebab]["wrong"]
    for i in range(n):
        fx = wrongs[i % len(wrongs)]
        r = client.post("/v1/me/attempts", headers=auth, json={"problem_id": fx["problem_id"], "is_correct": False, "selected_choice_index": fx["choice_index"]})
        assert r.status_code == 201, r.text
        import subprocess
        q = subprocess.run(["psql","-h","127.0.0.1","-U","whymath","-d","whymath","-At","-F","|","-c","select misconception_id, confidence, evidence_count, turns_since_evidence, is_active from misconception_hypothesis order by updated_at"],capture_output=True,text=True,timeout=30)
        print(f"#{i+1} hyp_rows(misconception_id|confidence|evidence_count|tse|active)=", q.stdout.strip().replace("\n"," ; "), q.stderr.strip()[:100])
    w1._erase_learner(client)
