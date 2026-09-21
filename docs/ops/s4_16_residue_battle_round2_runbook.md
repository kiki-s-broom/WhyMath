# S4-16 2차 강등전 라이브 실행 런북 (Phaiakes9)

> **이 문서는 Kiki가 직접 실행하는 과제의 안내서다.** 세션은 이 회차를 실행할 수 없다 — 이
> 저장소의 CI·컨테이너에는 LLM provider가 없어 전 테스트가 결정론 시임이다.

---

## 1. 사전 브리핑 (6항목)

| 항목 | 내용 |
|---|---|
| **① 과제 명칭** | 잔여 축 교차검증 게이트 2차 강등전 — v4 프로덕션 모드 라이브 측정 |
| **② 목적** | 결함을 우리가 일부러 주입한 시험지를 검출기에 태워 **검출률·오검출률을 측정**한다. 이 수치가 `S4-16`의 승격/기각 판정 근거이고, 통과하면 파일럿 코퍼스 34문의 노출 게이팅(`is_published=False`)이 풀린다. 1차(2026-08-10)는 검출 2/12로 기각됐고, 그 뒤 클라우드 회차 2번은 **오검출**에서 막혔다(측정 이력 = `docs/standards/residue_gate_demotion_battle_history.md`). |
| **③ 구체적 절차** | 4단계. [A] 브랜치 체크아웃 + 자가검증 → [B] Ollama·모델 실재 확인 → [C] 실행 전 판정값 출력 → [D] 측정 실행(판정값을 재검사해 스스로 거부). [D]의 예상 소요는 **호출 531회**(항목 59건 x 9콜)이며, 콜당 5~15초 가정 시 **45분~2시간 20분**이다. 진행 중 출력은 없다 — 끝날 때 리포트가 한 번에 나온다. |
| **④ 성공 기준** | [D]가 리포트를 출력하고 `BATTLE_EXIT=0` 또는 `=1`을 낸다. **둘 다 정상**이다 — 0은 게이트 통과, 1은 게이트 미달이며 **미달도 유효한 측정 결과**다(우리가 알고 싶은 것이 그 수치다). 실패는 `=2`(인자·환경 오류)이거나 `WRITE_REFUSED=True`(선행 조건 미충족)이다. 실패 시 대처는 각 단계에 적었다. |
| **⑤ 실행 환경** | Kiki 작업 PC = Phaiakes9. **Windows PowerShell**(진입 명령 불요). 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: Ollama 가동 + `qwen3:30b-a3b` 모델 보유. Docker·DB는 **불필요**하다(이 측정은 코퍼스 파일만 읽는다). |
| **⑥ 창 구분** | 창 하나면 된다. 서버를 띄우지 않으므로 점유 창이 없다. [D]는 길게 도니 그 동안 그 창을 건드리지 말 것. |

---

## 2. [A] 브랜치 체크아웃 + 자가검증

이 런북이 쓰는 CLI 옵션(`--v4`·`--clean-n`·`--repeat-runs`)은 **아직 main에 없다.** 반드시
이 브랜치로 옮긴 뒤 실행한다. 클론은 여러 세션이 공유하는 단일 작업 사본이라, 다른 세션이
그 사이 브랜치를 바꿔 뒀을 수 있다 — 그래서 아래 블록은 옮긴 뒤 **무엇으로 옮겨졌는지 직접
출력한다**.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin claude/optimistic-gates-9ef9nm
git checkout -B claude/optimistic-gates-9ef9nm origin/claude/optimistic-gates-9ef9nm
git log -1 --oneline
python -m whymath_backend.harness.residue_gate_demotion_battle --help | Select-String -Pattern "--v4","--clean-n"
```

**확인할 것**: 마지막 명령이 `--v4`와 `--clean-n` 두 줄을 출력해야 한다.
아무것도 안 나오면 옛 코드가 돌고 있는 것이다(체크아웃이 안 됐거나 다른 트리다) — 진행하지 말고
`git log -1 --oneline` 출력을 세션에 회신한다.

---

## 3. [B] Ollama·모델 실재 확인

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
ollama list | Select-String -Pattern "qwen3:30b-a3b"
$env:OLLAMA_FLASH_ATTENTION="1"
$env:WHYMATH_OLLAMA_REQUEST_TIMEOUT_S="180"
```

**확인할 것**: `qwen3:30b-a3b` 줄이 보여야 한다. 안 보이면 `ollama pull qwen3:30b-a3b`(17.3GB)를
먼저 받는다. `flash attention`은 `docs/ops/amd395_local_llm_performance.md` 확정 조건 3번이다
(MoE 생성 +20.3%).

---

## 4. [C] 실행 전 판정값 출력 (읽기 전용)

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Corpus = "data\corpus\problem_bank_probability_finite_v0\problems.jsonl"
$CorpusOk = Test-Path $Corpus
$HasV4 = (python -m whymath_backend.harness.residue_gate_demotion_battle --help | Select-String -Pattern "--v4").Count -gt 0
$OllamaOk = (ollama list | Select-String -Pattern "qwen3:30b-a3b").Count -gt 0
"CORPUS_OK=$CorpusOk"
"HAS_V4=$HasV4"
"OLLAMA_OK=$OllamaOk"
```

세 줄이 전부 `True`여야 다음 단계가 실행된다. 하나라도 `False`면 [D]는 **스스로 거부하고 멈춘다**
— 그래도 위 세 줄을 눈으로 확인하고 넘어가는 편이 낫다.

---

## 5. [D] 측정 실행 — 정본 회차 (v4 프로덕션 모드)

이 블록은 [C]의 판정값을 **다시 계산해 스스로 거부한다.** 출력은 흐름을 멈추지 못하므로,
쓰기·측정 블록은 사람 판정에 기대지 않는다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Corpus = "data\corpus\problem_bank_probability_finite_v0\problems.jsonl"
$CorpusOk = Test-Path $Corpus
$HasV4 = (python -m whymath_backend.harness.residue_gate_demotion_battle --help | Select-String -Pattern "--v4").Count -gt 0
$OllamaOk = (ollama list | Select-String -Pattern "qwen3:30b-a3b").Count -gt 0
if ($CorpusOk -and $HasV4 -and $OllamaOk) { python -m whymath_backend.harness.residue_gate_demotion_battle $Corpus --v4 production --sample-n 5 --clean-n 34 --audit-out data\audit\s4-16-v4-production-2026-09.jsonl 2>&1 | Tee-Object -FilePath battle_v4_production.log ; "BATTLE_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True - CORPUS_OK=$CorpusOk HAS_V4=$HasV4 OLLAMA_OK=$OllamaOk (하나라도 False면 측정하지 않는다)" }
```

- `--v4 production`: 전 관점 세트를 태우고 판정을 합집합한다. **승격 판정은 이 모드로만 한다**
  (오라클 모드는 결함류를 알고 세트를 골라 오검출을 과소 추정한다 — 이력 문서 §4.6).
- `--clean-n 34`: 무결함 대조군을 코퍼스 전량으로 잡는다. 1차가 `--max-defect-upper` 보정에
  실패한 직접 원인이 대조군 n=2였다. 34가 이 코퍼스의 상한이다.
- 임계(`--min-detection-lower`·`--max-false-alarm-upper`)는 **일부러 주지 않는다.** 2차는
  천장을 판정하기 위한 측정이지 천장을 적용하는 회차가 아니다(§6).

---

## 6. 회신할 것

`battle_v4_production.log`의 리포트 전문과 `BATTLE_EXIT` 값. 특히 이 두 줄:

- `결함 검출률 : m/n (95% 하한 …)`
- `무결함 오검출 : m/34 (95% 상한 …)`

그리고 `data\audit\s4-16-v4-production-2026-09.jsonl`(항목별 판정 원자료).

---

## 7. 선택 회차 (정본 회차 결과를 보고 나서 결정)

- **진단용 오라클 회차** — 같은 인자에서 `--v4 production`을 `--v4 oracle`로 바꾼다. 결함류별
  실명(失明) 지점을 찾는 용도이며 **승격 근거가 아니다**. 콜 수가 1/3이라 훨씬 빠르다.
- **상한 참조 클라우드 회차** — `--cloud`를 더한다(`settings.cloud_provider`가 좌석을 정한다).
  측정 구성 = 배포 구성 원칙상, 배포 라우팅이 클라우드가 아니면 이 수치는 인증이 아니라
  "이 프로토콜이 최고 모델에서 얼마나 가는가"의 참조값이다.
- **일관성 회차** — `--repeat-runs 3`. 1차 기록이 요구한 "검출 일관성 자체의 측정"이다. 콜 수가
  3배가 되니 정본 회차의 실소요를 본 뒤 결정한다.
