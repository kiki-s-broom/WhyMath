# S4-16 2차 강등전 라이브 실행 런북 (Phaiakes9)

> **이 문서는 Kiki가 직접 실행하는 과제의 안내서다.** 세션은 이 회차를 실행할 수 없다 — 이
> 저장소의 CI·컨테이너에는 LLM provider가 없어 전 테스트가 결정론 시임이다.

---

## 1. 사전 브리핑 (6항목)

| 항목 | 내용 |
|---|---|
| **① 과제 명칭** | 잔여 축 교차검증 게이트 2차 강등전 — v4 프로덕션 모드 라이브 측정 |
| **② 목적** | 결함을 우리가 일부러 주입한 시험지를 검출기에 태워 **검출률·오검출률을 측정**한다. 이 수치가 `S4-16`의 승격/기각 판정 근거이고, 통과하면 파일럿 코퍼스 34문의 노출 게이팅(`is_published=False`)이 풀린다. 1차(2026-08-10)는 검출 2/12로 기각됐고, 그 뒤 클라우드 회차 2번은 **오검출**에서 막혔다(측정 이력 = `docs/standards/residue_gate_demotion_battle_history.md`). |
| **③ 구체적 절차** | 4단계. [A] main 트리 고정 + 자가검증 → [B] Ollama·모델 실재 확인 → [C] 실행 전 판정값 출력 → [D] 측정 실행(판정값을 재검사해 스스로 거부). [D]의 예상 소요는 **호출 531회**(항목 59건 x 9콜)이며, 콜당 5~15초 가정 시 **45분~2시간 20분**이다. 진행 중 출력은 없다 — 끝날 때 리포트가 한 번에 나온다. |
| **④ 성공 기준** | **`BATTLE_EXIT` 으로 판정하지 않는다.** 이 회차는 임계를 일부러 주지 않으므로(§5) exit 1 은 구조적으로 나올 수 없고, `=0` 은 "게이트 통과"가 아니라 "임계 검사를 하지 않았다"는 뜻이다 — 검출 0%·오검출 100%·전건 측정실패 세 경우가 전부 `=0` 을 낸다(2026-09-22 실측, 세 시나리오 주입). 성공은 **리포트의 세 수치**로 판정한다: `결함 검출률`·`무결함 오검출`·그 두 줄의 **`판정불가 N건`**. 판정불가가 절반을 넘으면 그 회차는 측정 실패이므로 수치를 판정 근거로 쓰지 않고 [B]의 모델·타임아웃을 점검해 재실행한다(전 관점이 `unclear` 로 떨어지는 가장 흔한 원인이 provider 타임아웃이며, 그 상태도 `BATTLE_EXIT=0` 으로 보인다). 환경·인자 오류는 `=2`, 선행 조건 미충족은 `WRITE_REFUSED=True` 로 각각 구분된다. |
| **⑤ 실행 환경** | Kiki 작업 PC = Phaiakes9. **Windows PowerShell**(진입 명령 불요). 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: Ollama 가동 + `qwen3:30b-a3b` 모델 보유. Docker·DB는 **불필요**하다(이 측정은 코퍼스 파일만 읽는다). |
| **⑥ 창 구분** | 창 하나면 된다. 서버를 띄우지 않으므로 점유 창이 없다. [D]는 길게 도니 그 동안 그 창을 건드리지 말 것. |

---

## 2. [A] main 트리 고정 + 자가검증

이 런북이 쓰는 CLI 옵션(`--v4`·`--clean-n`·`--repeat-runs`)은 **main에 있다**(2026-09-22
실측 — `residue_gate_demotion_battle.py` 는 main과 옛 작업 브랜치가 바이트 동일이다). 그러므로
**어느 작업 브랜치로도 옮기지 않는다.** 종전 문면은 `claude/optimistic-gates-9ef9nm` 체크아웃을
지시했는데, 그 브랜치가 갖고 있던 측정 코드는 이미 main에 착지했고 그 위에 남은 것은 이 측정과
무관한 커밋뿐이다. 작업 브랜치의 상태는 시시각각 바뀌므로(머지·삭제·타 세션의 새 커밋) **측정이
브랜치 이름에 의존하면 그 의존 자체가 결함이다** — main 은 그 변동의 밖에 있다.

클론은 여러 세션이 공유하는 단일 작업 사본이라 다른 세션이 브랜치를 바꿔 뒀을 수 있다. 아래
블록은 ①main 트리로 **비파괴적으로** 옮기고(덮어쓸 로컬 변경이 있으면 git이 큰 소리로 거부한다)
②무엇으로 옮겨졌는지 직접 출력하고 ③**실제로 임포트되는 파일 경로**를 출력한다. 파일을 읽어
보는 것만으로는 그 파일이 돌았는지 알 수 없다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONUTF8="1"
$env:PYTHONPATH="C:\Users\kiki\Desktop\__AI\WhyMath\src\backend"
git fetch origin main
git switch --detach origin/main
git log -1 --oneline
python -c "import whymath_backend.harness.residue_gate_demotion_battle as m; print(m.__file__)"
python -m whymath_backend.harness.residue_gate_demotion_battle --help | Select-String -Pattern "--v4","--clean-n"
```

**정정(2026-09-24 실측) — 다른 작업 사본의 코드가 임포트되는 문제.** Kiki 머신의 `python`
은 conda base에 **편집 설치(editable install)** 된 `whymath_backend`를 갖고 있고, 그 설치가
가리키는 곳은 이 클론이 아니라 타 세션의 작업 사본(`WhyMath-mp02-rerun`)이었다 — main으로
체크아웃해도 실제로 돈 것은 그쪽 파일이다. 그래서 모든 블록이 `PYTHONPATH` 를 이 클론의
`src\backend` 로 고정한다(`PYTHONPATH` 는 site-packages·편집 설치보다 앞서 검색된다). 편집
설치 자체는 **건드리지 않는다** — 다시 설치하면 그 사본을 쓰는 다른 세션의 실행이 깨진다. [C]·[D]
는 `__file__` 을 다시 계산해 `MODULE_OK` 로 판정하고, [D]는 그것이 False면 측정을 거부한다.

**확인할 것** 3가지. ①`git switch` 가 오류 없이 끝난다 — `local changes would be overwritten`
으로 거부하면 타 세션의 미커밋 변경이 있는 것이니 **진행하지 말고** 그 메시지를 세션에 회신한다
(임의로 버리면 남의 작업분이 사라진다). ②`__file__` 이
`C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\whymath_backend\...` 아래를 가리킨다 —
다른 경로면 설치된 옛 사본이 돌고 있다. ③마지막 명령이 `--v4`와 `--clean-n` 두 줄을 출력한다.
하나라도 어긋나면 진행하지 말고 `git log -1 --oneline` 출력과 함께 회신한다.

---

## 3. [B] Ollama·모델 실재 확인

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
ollama list | Select-String -Pattern "qwen3:30b-a3b"
"FLASH_ATTENTION_USER=" + [Environment]::GetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","User")
```

**확인할 것**: ①`qwen3:30b-a3b` 줄이 보여야 한다. 안 보이면 `ollama pull qwen3:30b-a3b`(17.3GB)를
먼저 받는다. ②`FLASH_ATTENTION_USER=1` 이 보이면 좋다. `flash attention`은
`docs/ops/amd395_local_llm_performance.md` 확정 조건 3번이다(MoE 생성 +20.3%).

**정정(2026-09-24)**: 종전 문면은 이 창에서 `$env:OLLAMA_FLASH_ATTENTION="1"` 을 설정하게 했는데,
그 변수는 **Ollama 데몬 프로세스**가 읽는다 — 이미 떠 있는 데몬(트레이 앱)에는 클라이언트 창의
변수가 닿지 않으므로 그 줄은 아무것도 바꾸지 않았다(변별력 없는 스텝). 비어 있거나 `1` 이 아니면
위 성능 정본 §확정 조건의 User 환경변수 등록 + Ollama 재시작 절차를 따른다. 켜지지 않아도 측정은
유효하다 — 느려질 뿐이다. 요청 타임아웃(`WHYMATH_OLLAMA_REQUEST_TIMEOUT_S`)은 측정 프로세스가
읽는 값이라 [D] 블록 안으로 옮겼다(블록 자기완결).

---

## 4. [C] 실행 전 판정값 출력 (읽기 전용)

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONUTF8="1"
$env:PYTHONPATH="C:\Users\kiki\Desktop\__AI\WhyMath\src\backend"
$Corpus = "data\corpus\problem_bank_probability_finite_v0\problems.jsonl"
$CorpusOk = Test-Path $Corpus
$HasV4 = (python -m whymath_backend.harness.residue_gate_demotion_battle --help | Select-String -Pattern "--v4").Count -gt 0
$OllamaOk = (ollama list | Select-String -Pattern "qwen3:30b-a3b").Count -gt 0
git diff --quiet origin/main -- src/backend/whymath_backend/harness/residue_gate_demotion_battle.py src/backend/whymath_backend/l3/cross_verify.py data/corpus/problem_bank_probability_finite_v0/problems.jsonl docs/prompts
$PathsMatchMain = ($LASTEXITCODE -eq 0)
$ModuleFrom = python -c "import whymath_backend.harness.residue_gate_demotion_battle as m; print(m.__file__)"
$ModuleOk = $ModuleFrom -like "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\*"
"CORPUS_OK=$CorpusOk"
"HAS_V4=$HasV4"
"OLLAMA_OK=$OllamaOk"
"PATHS_MATCH_MAIN=$PathsMatchMain"
"MODULE_OK=$ModuleOk  MODULE_FROM=$ModuleFrom"
```

다섯 줄(`MODULE_OK` 포함)이 전부 `True`여야 다음 단계가 실행된다. 하나라도 `False`면 [D]는 **스스로 거부하고 멈춘다**
— 그래도 위 네 줄을 눈으로 확인하고 넘어가는 편이 낫다.

`PATHS_MATCH_MAIN` 은 **이 측정이 읽는 경로만** main과 비교한다(검증기 2개 + 코퍼스 + `docs/prompts` — 검증 관점의 프롬프트는 임포트된 패키지가 속한 저장소의 `docs/prompts` 에서 읽힌다, 2026-09-24 실측으로 추가). 무관한
파일이 더러워도 통과하고, 측정 입력이 다르면 막는다 — 변별력이 필요한 자리에 정확히 놓은
검사다. `False` 면 어느 경로가 다른지
`git diff --stat origin/main -- src/backend/whymath_backend/harness/residue_gate_demotion_battle.py src/backend/whymath_backend/l3/cross_verify.py data/corpus/problem_bank_probability_finite_v0/problems.jsonl` 로 확인해 회신한다.

---

## 5. [D] 측정 실행 — 정본 회차 (v4 프로덕션 모드)

이 블록은 [C]의 판정값을 **다시 계산해 스스로 거부한다.** 출력은 흐름을 멈추지 못하므로,
쓰기·측정 블록은 사람 판정에 기대지 않는다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONUTF8="1"
$env:PYTHONPATH="C:\Users\kiki\Desktop\__AI\WhyMath\src\backend"
$env:WHYMATH_OLLAMA_REQUEST_TIMEOUT_S="180"
$Corpus = "data\corpus\problem_bank_probability_finite_v0\problems.jsonl"
$CorpusOk = Test-Path $Corpus
$HasV4 = (python -m whymath_backend.harness.residue_gate_demotion_battle --help | Select-String -Pattern "--v4").Count -gt 0
$OllamaOk = (ollama list | Select-String -Pattern "qwen3:30b-a3b").Count -gt 0
git diff --quiet origin/main -- src/backend/whymath_backend/harness/residue_gate_demotion_battle.py src/backend/whymath_backend/l3/cross_verify.py data/corpus/problem_bank_probability_finite_v0/problems.jsonl docs/prompts
$PathsMatchMain = ($LASTEXITCODE -eq 0)
$ModuleFrom = python -c "import whymath_backend.harness.residue_gate_demotion_battle as m; print(m.__file__)"
$ModuleOk = $ModuleFrom -like "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\*"
if ($CorpusOk -and $HasV4 -and $OllamaOk -and $PathsMatchMain -and $ModuleOk) { cmd /c "python -m whymath_backend.harness.residue_gate_demotion_battle $Corpus --v4 production --sample-n 5 --clean-n 34 --audit-out data\audit\s4-16-v4-production-2026-09.jsonl > battle_v4_production.log 2>&1" ; "BATTLE_EXIT=$LASTEXITCODE" ; Get-Content -Encoding UTF8 battle_v4_production.log } else { "WRITE_REFUSED=True - CORPUS_OK=$CorpusOk HAS_V4=$HasV4 OLLAMA_OK=$OllamaOk PATHS_MATCH_MAIN=$PathsMatchMain MODULE_OK=$ModuleOk MODULE_FROM=$ModuleFrom (하나라도 False면 측정하지 않는다 — 어느 것이 False인지가 다음 행동을 정한다)" }
```

- `--v4 production`: 전 관점 세트를 태우고 판정을 합집합한다. **승격 판정은 이 모드로만 한다**
  (오라클 모드는 결함류를 알고 세트를 골라 오검출을 과소 추정한다 — 이력 문서 §4.6).
- `--clean-n 34`: 무결함 대조군을 코퍼스 전량으로 잡는다. 1차가 `--max-defect-upper` 보정에
  실패한 직접 원인이 대조군 n=2였다. 34가 이 코퍼스의 상한이다.
- 임계(`--min-detection-lower`·`--max-false-alarm-upper`)는 **일부러 주지 않는다.** 2차는
  천장을 판정하기 위한 측정이지 천장을 적용하는 회차가 아니다(§6).
- **정정(2026-09-24) — 리포트를 PowerShell 파이프에 통과시키지 않는다.** 종전 문면은
  `2>&1 | Tee-Object` 였다. Windows PowerShell 5.1은 네이티브 명령의 출력을
  `[Console]::OutputEncoding`(한국어 Windows = cp949)으로 디코딩하는데, `PYTHONUTF8=1` 인
  Python은 UTF-8을 낸다 — 리포트의 한국어 라벨이 깨지고, 경계가 어긋나면 인접 문자까지 삼킨다
  (CLAUDE.md 인코딩 규칙 "셸이 중계하는 제3 도구 출력" 축, 2026-09-14 JSON 41자 유실 실측).
  2시간짜리 회차의 유일한 산출 리포트가 그 경로를 지나면 안 되므로 `cmd /c "… > 로그 2>&1"` 로
  바이트를 파일에 직접 쓰고 `Get-Content -Encoding UTF8` 로 읽는다. `$LASTEXITCODE` 는
  `cmd /c` 가 Python의 종료 코드를 그대로 돌려준다. 감사 JSONL은 Python이 UTF-8로 직접 쓰므로
  종전에도 안전했다. 부수 효과: 실행 중 화면 출력이 없다(원래도 끝날 때 한 번에 나왔다).
- **세션 사전 검증(2026-09-24, main `fbb6c215`)**: 세션 컨테이너에서 이 인자 그대로 가짜
  provider(전 호출 실패)로 드라이런 — 호출 **531회** 확인, 라우터가 고르는 검증 모델은
  `llm:qwen3:30b-a3b`(로컬), 전 호출 실패 시 두 줄 모두 `판정불가` 가 찍히고 exit 0(§1-④와 일치).

---

## 6. 회신할 것 + 오검출 천장 판정

### 6.1 회신할 것

`battle_v4_production.log`의 리포트 전문. 특히 이 두 줄(각 줄 끝의 **`판정불가 N건`** 까지 함께
— 그것이 이 회차가 실제로 측정에 성공했는지를 말한다):

- `결함 검출률 : m/n (95% 하한 …)  판정불가 N건`
- `무결함 오검출 : m/34 (95% 상한 …)  판정불가 N건`

그리고 `data\audit\s4-16-v4-production-2026-09.jsonl`(항목별 판정 원자료).
`BATTLE_EXIT` 값도 같이 적되 **판정 근거로는 쓰지 않는다**(§1-④ — 이 회차에서 그 값은 항상 0).

### 6.2 함께 판정할 것 — 오검출 천장을 얼마로 둘 것인가

`S4-16` acceptance 가 요구하는 오검출 상한 **0.05 는 이 코퍼스로 인증이 불가능하다.** 대조군
34문 **전건 무오검출**이어도 95% 단측 Wilson 상한은 `0.0737` 에서 멈춘다(위 §5 [D] 를 돌리면
리포트가 그 수치를 직접 낸다). 0.05 아래로 내리려면 대조군 `n>=51` 이 필요한데 코퍼스가 34문이다
— 즉 지금 임계를 적용하면 **모델이 완벽해도 상시 FAIL** 이다(잘못 캘리브레이션된 임계).

그래서 이 회차는 천장을 *적용*하지 않고 *판정*한다. Kiki 판정 3택:

1. **천장을 `.08` 수준으로 재설정** — n=34 전건 무오검출을 요구한다(이 코퍼스에서 달성 가능한
   가장 엄격한 기준). 측정치가 그 아래면 통과.
2. **코퍼스를 확장해 0.05 를 겨냥** — 대조군 51문 이상을 만든 뒤 재측정한다(별도 태스크).
3. **이 경로를 인간 검수 대체 후보에서 내린다** — 다섯 회차에서 검출률은 16.7%→90% 로 올랐지만
   오검출은 한 번도 60% 아래로 내려오지 않았다. 구속 축이 모델 성능이 아니라 프로토콜이라는
   판단이면 이 선택지가 맞다(이력 = `docs/standards/residue_gate_demotion_battle_history.md`).

---

## 7. 선택 회차 (정본 회차 결과를 보고 나서 결정)

- **진단용 오라클 회차** — 같은 인자에서 `--v4 production`을 `--v4 oracle`로 바꾼다. 결함류별
  실명(失明) 지점을 찾는 용도이며 **승격 근거가 아니다**. 콜 수가 1/3이라 훨씬 빠르다.
- **상한 참조 클라우드 회차** — `--cloud`를 더한다(`settings.cloud_provider`가 좌석을 정한다).
  측정 구성 = 배포 구성 원칙상, 배포 라우팅이 클라우드가 아니면 이 수치는 인증이 아니라
  "이 프로토콜이 최고 모델에서 얼마나 가는가"의 참조값이다.
- **일관성 회차** — `--repeat-runs 3`. 1차 기록이 요구한 "검출 일관성 자체의 측정"이다. 콜 수가
  3배가 되니 정본 회차의 실소요를 본 뒤 결정한다.
