# OPS-106 런북 — 게이트② 라이브 표본 실측: 서빙 vs 저작 분리 확인 (Kiki · Phaiakes9)

> **판정 기준**: `origin/main` `198bba76` (OPS-84 #1424 · OPS-105 #1452 가 이미 main에 착지한 상태).
> 이 런북은 **문서만** 추가합니다 — 실행하는 코드는 전부 main에 이미 있습니다. §1이 Kiki 클론의
> 코드가 `origin/main`과 같은지 기계로 확인합니다(다르면 아무것도 돌리지 않고 멈춥니다).
>
> 태스크: `OPS-106-gate2-live-sample-serving-vs-authoring` · 게이트: `G-ops106-gate2-live-sample`.
> 결과 수치는 세션이 MEMORY에 기록하고 게이트를 닫습니다.

## 사전 브리핑 (6항목)

### ① 과제 명칭
게이트② **라이브 표본 실측** — "학생 대면 호출이 표본에 들어가고, 저작 호출은 표본에서 빠지는가"를
Phaiakes9에서 실제 Langfuse로 확인합니다.

### ② 목적
게이트②("루프당 LLM 비용 실측")는 Langfuse의 `l3_routing` 이벤트를 `ops/cost_report`가 집계해 판정합니다.
OPS-84·OPS-105가 서빙/저작/프로브 **표면 표지(`traffic_surface`)** 를 붙이고 저작·프로브를 표본에서
빼도록 만들었지만, 그 검증은 **전부 가짜 싱크(hermetic 테스트)** 로만 했습니다. 이번에 처음으로 다음 셋을
**진짜 Langfuse**로 확인합니다.

1. **서빙**: 서버(uvicorn)가 WH-1 primary 호출을 **프로덕션 `LangfuseSink`** 로 실제 전송하고,
   `cost_report`가 그것을 학생 대면 표본(`serving`)으로 계상하는가
2. **이중 회계**: 프로세스 안에서 센 호출 수(`cost_probe`)와 Langfuse에서 읽은 수가 **같은가** —
   Langfuse가 말없이 죽었을 때 "0건 통과"로 위장되지 않는지 (이 저장소가 langfuse v2에서 8일간
   무증상 전멸을 겪은 이력의 재발 방지 확인)
3. **저작 분리**: 저작 rephrase 호출이 `authoring`으로만 도착하고 표본(`event_count`)을 늘리지 않는가

> **이것은 게이트② 자체의 합격 판정이 아닙니다.** 게이트② 합격(로컬 ≥80% 등)은 이 계측 사슬이 믿을 만한가를
> 먼저 확인한 뒤의 일입니다. 이번은 **계측 사슬의 검증**입니다.

### ③ 구체적 절차 (전체 약 10~20분 — 추정, 실측 전)
| 절 | 창 | 무엇이 일어나는가 | 소요(추정) |
|---|---|---|---|
| §1 | ② | 코드 동등성·파이썬·키·Ollama·코퍼스 사전 점검(읽기 전용) | 약 1분 |
| §2 | ① | `run_demo.ps1`로 Postgres·서버 기동 | 1~3분 |
| §3 | ② | 서버 확인 + 기준선 스냅샷(Langfuse 읽기 1회) | 약 1분 |
| §4 | ② | 이중 회계: `cost_probe` 18콜(로컬만·0원) 후 Langfuse 증가분과 대조 | 2~5분 |
| §5 | ② | 저작 분리: rephrase 5콜 후 `authoring` 증가분 확인 | 1~3분 |
| §6 | ② | 서빙: 합성 코치 트래픽 15제출 후 `serving` 증가분 확인 | 2~5분 |
| §7 | ② | 판정 요약 한 화면 | 수 초 |

**실행 순서가 ②→③→①인 이유**: Langfuse 수집에는 지연이 있어 앞 단계의 늦게 온 이벤트가 다음 단계의
창으로 샐 수 있습니다. 서빙을 **마지막**에 두면 늦게 오는 서빙 이벤트가 저작 판정(서빙 증가 0이어야 함)을
오염시킬 수 없습니다.

### ④ 성공 기준
| 판정 줄 | 성공 | 실패면 |
|---|---|---|
| §1 `PRE_OK` | `True` | `False`인 항목 이름을 회신(세션이 원인별로 처리) |
| §4 `DUAL_ACCOUNTING` | `MATCH` | `SILENT_ZERO`=Langfuse가 말없이 비어 있음(측정 실패) — §8 표 |
| §5 `AUTHORING_SEPARATION` | `SEPARATED_MATCH` | `LEAK_INTO_SAMPLE`·`AUTHORING_UNLABELED` 등 — §8 표 |
| §6 `SERVING_SAMPLE` | `COUNTED` | `SILENT_ZERO`·`ARRIVED_UNLABELED` 등 — §8 표 |

**성공이 아닌 값도 결과입니다.** 틀린 값이 나오면 그대로 회신해 주십시오 — 이 런북의 목적이 "계측이
정말 되는가"의 확인이라, 안 된다는 사실이 가장 가치 있는 산출입니다.

### ⑤ 실행 환경
Phaiakes9 = 평소 쓰시는 **Windows PowerShell**. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`.
**선행 조건**: ⓐ Docker Desktop 가동 ⓑ Ollama 가동(로컬 모델 응답 가능) ⓒ Langfuse 키가 사용자 환경변수
`WHYMATH_LANGFUSE_PUBLIC_KEY`·`WHYMATH_LANGFUSE_SECRET_KEY`(또는 `src\backend\.env`)로 설정돼 있을 것.
**비용 0원** — `--no-cloud`로 클라우드 호출을 막았고(ARCH-66: Anthropic API 사용 중단 기간) 모든 LLM 호출이
로컬입니다. 결과 파일은 저장소 밖 `C:\Users\kiki\Desktop\__AI\ops106-out`에만 씁니다.

### ⑥ 창 구분
**두 개의 창**을 씁니다.
- **창 ①** — §2에서 서버를 기동하는 **새 PowerShell**. 기동 후 **이 창은 이후 조작하지 마십시오.** 서버가 이
  콘솔을 공유하므로 창을 닫거나 `Ctrl+C`(복사가 아니라 **중단 신호**)를 누르면 서버가 죽습니다.
- **창 ②** — 나머지 전부(§1·§3~§7). 창 ①과 **별개의 새 PowerShell**. §1에서 만든 변수를 뒤 블록이 씁니다 —
  **창 ②를 닫았다면 §1부터 다시** 붙여넣으십시오. 각 블록은 선행 조건을 스스로 다시 검사해, 맞지 않으면
  아무것도 실행하지 않고 거부합니다.

---

## 먼저 알아 둘 세 가지 (코드 실측에서 나온 함정)

1. **`cost_probe`·`live_preflight`로는 서빙 표본을 못 만듭니다.** 두 도구는 의도적으로 `traffic_surface=probe`
   표지를 붙이고, `cost_report`는 그것을 표본에서 **뺍니다**. 그래서 WH-1 primary 표본은 **서버에 HTTP로
   들어가는 합성 코치 트래픽**(`wh1_shadow_probe`)으로 만들고, `cost_probe`는 §4의 **이중 회계 대조
   전용**으로만 씁니다.
2. **합성 트래픽이 WH-1 primary LLM 경로에 실제로 도달하는가.** 도달합니다 — 합성 요청에는 `problem_id`가
   없어 완료 상태머신이 `NONE`을 내고(`_final_answer_state`→`decide_completion` ⑤), 그래서
   `completion.handled=False`라 primary LLM이 호출됩니다. **다만 실제 학생(문항이 있고 정답/오답이 판정되는 턴)은
   일부 턴이 돌아보기·재고 템플릿으로 가로채져 LLM을 건너뜁니다** — 이 실측은 "배선이 닿는가"의 확인이지
   "학생 분포를 대표한다"는 주장이 아닙니다.
3. **rephrase 입력 코퍼스를 아무거나 쓰면 LLM 호출이 0건입니다.** 코퍼스 31개 중 대부분이 `question_text`에서
   방정식을 추출할 수 없는 문항(`equation_extractable=0`)이라, 그것을 넘기면 저작 호출이 0건이 되어
   "분리 실패"로 오진됩니다. 이 런북은 **200건 전부 추출 가능한** `problem_bank_discrete_ev_v0`를 쓰고,
   §1이 앞 5건이 실제로 추출 가능한지 **직접 재서** `CORPUS_OK`로 확인합니다.

---

## 1. 사전 점검 — 창 ② (읽기 전용 · 결과 폴더만 만듦)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 사전 점검(읽기 전용 · 결과 폴더 스캐폴딩만)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$Out = "C:\Users\kiki\Desktop\__AI\ops106-out"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
New-Item -ItemType Directory -Force -Path $Out | Out-Null
git fetch origin main
$FetchOk = ($LASTEXITCODE -eq 0)
git diff --quiet origin/main -- src/backend scripts/demo data/corpus/problem_bank_discrete_ev_v0
$PathsMatch = ($LASTEXITCODE -eq 0)
$HeadNow = (git rev-parse --short HEAD)
$MainNow = (git rev-parse --short origin/main)
$PyExe = ""
foreach ($c in @("$Repo\src\backend\.venv\Scripts\python.exe", "$Repo\.venv\Scripts\python.exe")) { if (($PyExe -eq "") -and (Test-Path $c)) { $Imp = & $c -c "import whymath_backend, langfuse; print('IMPORT_OK')" 2>$null; if ($Imp -eq "IMPORT_OK") { $PyExe = $c } } }
$JDual = "import json,sys; L=lambda p: json.load(open(p,encoding='utf-8')); pr,a,b=map(L,sys.argv[1:4]); n=pr['total']-pr['errors']; sa=a.get('surface_counts') or {}; sb=b.get('surface_counts') or {}; d=sb.get('probe',0)-sa.get('probe',0); v=('NO_SURFACE_AXIS' if not (sa and sb) else 'INPROC_ZERO' if n<=0 else 'MATCH' if d==n else 'SILENT_ZERO' if d==0 else 'PARTIAL' if d<n else 'EXCESS'); print('INPROC_SUCCESS_N',n,'INPROC_ERRORS',pr['errors']); print('LANGFUSE_PROBE_DELTA',d); print('DUAL_ACCOUNTING',v)"
$JAuth = "import json,sys; L=lambda p: json.load(open(p,encoding='utf-8')); sw,a,b=map(L,sys.argv[1:4]); r=sw['rows'][0]; pe=sum(1 for x in r['unchanged_reason_sample'] if 'provider' in x); e=r['attempted']-pe; sa=a.get('surface_counts') or {}; sb=b.get('surface_counts') or {}; D=lambda k: sb.get(k,0)-sa.get(k,0); da=D('authoring'); du=D('unlabeled'); ds=D('serving'); de=b['event_count']-a['event_count']; v=('NO_SURFACE_AXIS' if not (sa and sb) else 'PROVIDER_DOWN_NO_CALLS' if e<=0 else 'AUTHORING_UNLABELED' if (da==0 and du>=1) else 'LEAK_INTO_SAMPLE' if de>0 else 'SILENT_ZERO' if da==0 else 'SEPARATED_MATCH' if da==e else 'PARTIAL' if da<e else 'EXCESS'); print('SWEEP_ATTEMPTED',r['attempted'],'PROVIDER_ERRORS',pe,'EXPECTED_EVENTS',e); print('LANGFUSE_AUTHORING_DELTA',da,'SAMPLE_DELTA',de,'SERVING_DELTA',ds,'UNLABELED_DELTA',du); print('AUTHORING_SEPARATION',v)"
$JServ = "import json,sys; L=lambda p: json.load(open(p,encoding='utf-8')); a,b=L(sys.argv[1]),L(sys.argv[2]); P=int(sys.argv[3]); sa=a.get('surface_counts') or {}; sb=b.get('surface_counts') or {}; D=lambda k: sb.get(k,0)-sa.get(k,0); ds,da,dp,du=D('serving'),D('authoring'),D('probe'),D('unlabeled'); de=b['event_count']-a['event_count']; ar=(de==ds+du); v=('NO_SURFACE_AXIS' if not (sa and sb) else 'NO_PRIMARY_TURN_IN_SERVER_LOG' if P<1 else 'ARITHMETIC_BROKEN' if not ar else 'COUNTED' if ds>=1 else 'ARRIVED_UNLABELED' if du>=1 else 'SILENT_ZERO' if (da+dp)==0 else 'OTHER_SURFACE_ONLY'); print('PRIMARY_RECORDS_IN_SERVER_LOG',P); print('LANGFUSE_SERVING_DELTA',ds,'UNLABELED_DELTA',du,'SAMPLE_DELTA',de,'AUTHORING_DELTA',da,'PROBE_DELTA',dp); print('SAMPLE_ARITHMETIC_OK',ar); tot=sum(sb.values()); print('SURFACE_LABELED_RATE', round((tot-sb.get('unlabeled',0))/tot,3) if tot else None); print('SERVING_SAMPLE',v)"
$CfgCheck = "from whymath_backend.config import Settings; s=Settings(); k=s.langfuse_public_key; sk=s.langfuse_secret_key.get_secret_value(); print('LANGFUSE_CONFIGURED', s.langfuse_configured); print('KEYS_PLACEHOLDER_FREE', len(k)>=20 and len(sk)>=20 and chr(8230) not in k and chr(8230) not in sk); print('KEY_PREFIX_TYPICAL', k.startswith('pk-lf-') and sk.startswith('sk-lf-')); print('WH1_PRIMARY_ENABLED', s.wh1_primary_enabled); print('LANGFUSE_HOST', s.langfuse_host)"
$PfRead = "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('OLLAMA_REACHABLE', d['ollama_reachable']); print('PREFLIGHT_LANGFUSE_CONFIGURED', d['langfuse_configured'])"
$CorpCheck = "import json,sys; from whymath_backend.l3.equivalent.rephrase import extract_equation; rows=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8') if l.strip()]; qs=[r.get('question_text') for r in rows if isinstance(r.get('question_text'),str) and r.get('question_text')][:int(sys.argv[2])]; n=sum(1 for q in qs if extract_equation(q) is not None); print('CORPUS_FIRST_N', len(qs), 'EXTRACTABLE', n); print('CORPUS_OK', len(qs)==int(sys.argv[2]) and n==len(qs))"
$Corpus = "$Repo\data\corpus\problem_bank_discrete_ev_v0\problems.jsonl"
$Cfg = @()
$Src = ""
$Pf = @()
$CorpOut = @()
if ($PyExe -ne "") { cd "$Repo\src\backend"; $Cfg = @(& $PyExe -c $CfgCheck); $Src = (& $PyExe -c "import whymath_backend; print(whymath_backend.__file__)"); cmd /c "$PyExe -m whymath_backend.ops.live_preflight --no-smoke --json $Out\preflight.json > $Out\preflight.out 2> $Out\preflight.err"; $Pf = @(& $PyExe -c $PfRead "$Out\preflight.json"); $CorpOut = @(& $PyExe -c $CorpCheck $Corpus 5) } else { "PYTHON_NOT_FOUND=True — src\backend\.venv 와 .venv 어디에도 whymath_backend+langfuse 를 임포트할 수 있는 python 이 없습니다." }
$SrcOk = ($Src -like "$Repo\src\backend*")
$CfgOk = (($Cfg -contains "LANGFUSE_CONFIGURED True") -and ($Cfg -contains "KEYS_PLACEHOLDER_FREE True"))
$PrimaryOn = ($Cfg -contains "WH1_PRIMARY_ENABLED True")
$OllamaOk = ($Pf -contains "OLLAMA_REACHABLE True")
$CorpusOk = ($CorpOut -contains "CORPUS_OK True")
$PreOk = ($FetchOk -and $PathsMatch -and ($PyExe -ne "") -and $SrcOk -and $CfgOk -and $PrimaryOn -and $OllamaOk -and $CorpusOk)
"FETCH_OK=$FetchOk"
"CODE_MATCHES_ORIGIN_MAIN=$PathsMatch  (HEAD=$HeadNow  origin/main=$MainNow)"
"PYTHON=$PyExe"
"LOADED_FROM_CLONE=$SrcOk  ($Src)"
$Cfg
"LANGFUSE_KEYS_OK=$CfgOk"
"WH1_PRIMARY_ON=$PrimaryOn"
$Pf
$CorpOut
"PRE_OK=$PreOk"
```

**판정**: `PRE_OK=True`면 §2로 갑니다. 하나라도 `False`면 그 줄(`FETCH_OK`·`CODE_MATCHES_ORIGIN_MAIN`·
`LOADED_FROM_CLONE`·`LANGFUSE_KEYS_OK`·`WH1_PRIMARY_ON`·`OLLAMA_REACHABLE`·`CORPUS_OK`)을 회신해 주십시오.

- `CODE_MATCHES_ORIGIN_MAIN=False` — 이 클론이 다른 브랜치이거나 미커밋 변경이 있는 것입니다. **브랜치를 옮기지
  마십시오**(여러 세션이 공유하는 작업 사본입니다). 출력을 회신하면 세션이 처리합니다.
- `KEY_PREFIX_TYPICAL=False`는 정보일 뿐 중단 사유가 아닙니다(자체 호스팅 키는 접두사가 다를 수 있음).
  중단 사유는 `KEYS_PLACEHOLDER_FREE`(키가 20자 미만이거나 `…` 문자가 섞임 = 자리표시자 키)입니다.
- `WH1_PRIMARY_ON=False` — `WHYMATH_WH1_PRIMARY_ENABLED=false`가 어딘가에 남아 있는 것입니다(킬스위치).

---

## 2. 서버 기동 — 창 ① (새 PowerShell · 기동 후 이 창 조작 금지)

> **새 PowerShell 창을 하나 더 여십시오.** 창 ②와 별개입니다. 아래 한 블록만 붙여넣고 **그 뒤로는 이 창에
> 아무것도 입력하지 않습니다.** 서버가 이 콘솔을 공유하므로 창을 닫거나 `Ctrl+C`를 누르면 서버가 죽습니다
> (`Ctrl+C`는 복사가 아니라 중단 신호입니다).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 서버 기동 전용(이 창은 이후 조작 금지)
cd C:\Users\kiki\Desktop\__AI\WhyMath
.\scripts\demo\run_demo.ps1
```

`▶ [6/6]` 단계와 "실기기 시연 준비 완료" 안내가 보이면 기동이 끝난 것입니다(1~3분 추정). 이 런북은 실기기·Flutter를
쓰지 않으므로 안내된 `flutter run` 명령은 무시하십시오. 이 줄에서 `throw` 오류(`backend 프로세스가 기동 직후
종료`, `PG가 시간 내 준비되지 않음` 등)가 나면 그 문장을 회신해 주십시오.

---

## 3. 서버 확인 + 기준선 스냅샷 — 창 ②

서버가 맞는 서버인지는 **간접 신호(`/health`·PID 파일)가 아니라 §6의 `primary` 로그 라인 수**로 판정합니다
(`/health`는 이전 세션의 좀비 서버도 응답합니다). 여기서는 정보만 출력하고, 기준선 스냅샷을 만듭니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 서버 정보 출력 + 기준선 스냅샷(Langfuse 읽기 1회)
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$RecLog = "$Repo\src\backend\wh1_shadow_records.log"
$SnapRead = "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('SNAP_EVENT_COUNT', d['event_count']); print('SNAP_SURFACE_COUNTS', d['surface_counts'])"
if ($PreOk) { $Health = try { (Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5 | Out-String).Trim() } catch { "HEALTH_FAIL " + $_.Exception.GetType().Name }; "HEALTH(참고용 · 간접 신호)=$Health"; $Lsn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; "PORT_8000_LISTENER_PID=$($Lsn.OwningProcess)"; "RECORD_LOG_EXISTS=$(Test-Path $RecLog)"; "RECORD_LINES_AT_START=$(@(Get-Content $RecLog -ErrorAction SilentlyContinue).Count)"; cmd /c "$PyExe -m whymath_backend.ops.cost_report --days 1 --json $Out\snap_0.json > $Out\snap_0.out 2> $Out\snap_0.err"; "SNAP_0_EXISTS=$(Test-Path "$Out\snap_0.json")"; & $PyExe -c $SnapRead "$Out\snap_0.json"; "--- snap_0.err (Langfuse 조회 경고가 있으면 여기 보입니다) ---"; Get-Content "$Out\snap_0.err" -Encoding UTF8 -ErrorAction SilentlyContinue } else { "REFUSED=True — PRE_OK=$PreOk. §1이 False이거나 창 ②를 새로 열었습니다 — §1부터 다시 붙여넣으십시오. 아무것도 실행하지 않았습니다." }
```

**판정**: `SNAP_0_EXISTS=True`와 `SNAP_SURFACE_COUNTS` 줄이 보여야 합니다(값이 전부 0이어도 정상일 수 있습니다 —
**0이 곧 정상이라는 뜻은 아닙니다**, 그것을 §4가 가려냅니다). `RECORD_LINES_AT_START`는 `0`이어야 합니다
(`run_demo.ps1`이 기동 시 이 파일을 지우고 새로 만듭니다). `RECORD_LOG_EXISTS=False`면 서버가 새 로그 설정으로
뜨지 않은 것입니다 — 회신해 주십시오.

---

## 4. 이중 회계(②) — 인프로세스 성공 수 vs Langfuse `probe` 증가분 — 창 ②

`cost_probe`는 대표 요청 18건(`--rounds 2`·로컬만)을 `pipeline.generate`로 태우고, **프로세스 안에서** 성공 수를
셉니다(`total − errors`). 같은 호출이 Langfuse에 `probe` 표면으로 도착했다면 `cost_report`의 `probe` 증가분이
그 수와 **정확히 같아야** 합니다. `pipeline.generate`는 호출 성공 1건당 이벤트를 정확히 1건 기록하고(캐시 적중도
기록) provider 예외일 때만 기록하지 않기 때문에, 이 등식이 성립합니다(`l3/pipeline.py`).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 이중 회계(선행 조건 재검사 · 로컬 LLM 18콜 · 비용 0원)
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$Snap0Ready = (Test-Path "$Out\snap_0.json")
if ($PreOk -and $Snap0Ready) { cmd /c "$PyExe -m whymath_backend.ops.cost_probe --rounds 2 --no-cloud --json $Out\probe.json > $Out\probe.out 2> $Out\probe.err"; "COST_PROBE_EXIT=$LASTEXITCODE"; Get-Content "$Out\probe.out" -Encoding UTF8 -TotalCount 30; for ($t = 1; $t -le 4; $t++) { cmd /c "$PyExe -m whymath_backend.ops.cost_report --days 1 --json $Out\snap_1.json > $Out\snap_1.out 2> $Out\snap_1.err"; $DualOut = @(& $PyExe -c $JDual "$Out\probe.json" "$Out\snap_0.json" "$Out\snap_1.json"); "POLL $t / 4"; $DualOut; if ($DualOut -contains "DUAL_ACCOUNTING MATCH") { break }; Start-Sleep -Seconds 30 } } else { "REFUSED=True — PRE_OK=$PreOk SNAP_0_READY=$Snap0Ready. §1·§3을 먼저 통과해야 합니다. 아무 LLM 호출도 하지 않았습니다." }
```

화면에 출력이 거의 없이 1~3분(추정)이 지나갈 수 있습니다 — 로컬 모델이 18번 답하는 시간입니다.

**판정**: `DUAL_ACCOUNTING MATCH` 한 줄. `COST_PROBE_EXIT=1`은 **실패가 아닙니다**(로컬 비율 Wilson 하한이 0.80
미만이라는 뜻 — 게이트② 로컬 판정선이지 이 런북의 판정이 아닙니다). 다른 값은 §8 표를 보고 그대로 회신하십시오.
`INPROC_ZERO`는 프로브 자체가 한 건도 성공하지 못한 것(대개 Ollama 문제)이라 Langfuse 쪽 결론을 낼 수 없습니다.

---

## 5. 저작 분리(③) — rephrase 5콜 후 `authoring` 증가분 — 창 ②

`problem_corpus_rephrase_sweep`은 `QuestionRephraser`를 라이브로 구성해 발문 5건을 다양화합니다. 기대 이벤트 수는
**`attempted − provider 예외 수`** 입니다(provider가 예외를 낸 호출은 이벤트가 없습니다). 이 5건은 **표본(`event_count`)을
늘리지 않고 `authoring` 건수로만** 나타나야 합니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 저작 분리(선행 조건 재검사 · 로컬 LLM 5콜 · 비용 0원)
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$Snap1Ready = (Test-Path "$Out\snap_1.json")
if ($PreOk -and $CorpusOk -and $Snap1Ready) { cmd /c "$PyExe -m whymath_backend.harness.problem_corpus_rephrase_sweep --in $Corpus --temperatures 0.7 --limit 5 --json > $Out\sweep.json 2> $Out\sweep.err"; "SWEEP_EXIT=$LASTEXITCODE"; for ($t = 1; $t -le 4; $t++) { cmd /c "$PyExe -m whymath_backend.ops.cost_report --days 1 --json $Out\snap_2.json > $Out\snap_2.out 2> $Out\snap_2.err"; $AuthOut = @(& $PyExe -c $JAuth "$Out\sweep.json" "$Out\snap_1.json" "$Out\snap_2.json"); "POLL $t / 4"; $AuthOut; if (($AuthOut -contains "AUTHORING_SEPARATION SEPARATED_MATCH") -or ($AuthOut -contains "AUTHORING_SEPARATION PROVIDER_DOWN_NO_CALLS")) { break }; Start-Sleep -Seconds 30 } } else { "REFUSED=True — PRE_OK=$PreOk CORPUS_OK=$CorpusOk SNAP_1_READY=$Snap1Ready. §1·§4를 먼저 통과해야 합니다. 아무 LLM 호출도 하지 않았습니다." }
```

**판정**: `AUTHORING_SEPARATION SEPARATED_MATCH`. `PROVIDER_DOWN_NO_CALLS`는 Ollama가 5건 전부 거절한 것이라
**Langfuse 문제가 아닙니다** — Ollama를 확인한 뒤 이 블록만 다시 붙여넣으면 됩니다.

---

## 6. 서빙 계상(①) — 합성 코치 트래픽 후 `serving` 증가분 — 창 ②

`wh1_shadow_probe`가 서버의 `/v1/coach/sessions`에 대표 3모양(방정식 체인·표현식 동치·오전개) 풀이를 5세션×3제출 =
15건 보냅니다(쓰기 한도 30/분에 맞춘 2.5초 간격 — 약 40초 + LLM 시간). 서버가 `wh1_primary_enabled`로 뜬 상태라
각 제출은 **프로덕션 `LangfuseSink`(서버가 `create_app()`으로 만든 기본 싱크 — 테스트 주입 싱크가 아님)** 로
`serving` 표지를 붙여 Langfuse에 보냅니다. 서버가 별개 프로세스이므로 Langfuse에 `serving`이 늘었다면 그것을 보낼 수
있었던 것은 기본 싱크뿐입니다.

**토큰은 프로브가 직접 발급합니다(`--token` 미지정).** `wh1_shadow_probe`는 `run_demo.ps1`과 같은 순서
(`GET …/demo/state` → `POST …/demo/callback`)로 `state`를 먼저 받아 콜백 바디에 싣습니다(OPS-111 — 종전에는
`state` 없이 호출해 SEC-08 이후 HTTP 422로 첫 단계에서 죽었고, 이 블록이 토큰을 대신 발급하는 우회를 썼다).
발급 실패는 `serve.err`에 `프로브 실패(ProbeAuthError): …`로 남고 `SHADOW_PROBE_EXIT=2`가 됩니다.

서버 로그의 `"primary":true` 줄 수(`P`)는 **서버가 primary 경로를 실제로 탔다는 인프로세스 증거**입니다. 턴 단위
기록이라 LLM 호출 수와 1:1이 아니므로(턴마다 정책·프로즈 호출이 0~여러 건) **등식이 아니라 "P가 1 이상인가"만**
판정에 씁니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 서빙 계상(선행 조건 재검사 · 서버로 HTTP 15제출 · 비용 0원)
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$Snap2Ready = (Test-Path "$Out\snap_2.json")
$P = 0
if ($PreOk -and $Snap2Ready) { cmd /c "$PyExe -m whymath_backend.ops.wh1_shadow_probe --base-url http://127.0.0.1:8000 --rounds 1 > $Out\serve.out 2> $Out\serve.err"; "SHADOW_PROBE_EXIT=$LASTEXITCODE"; Get-Content "$Out\serve.out" -Encoding UTF8 -TotalCount 30; Get-Content "$Out\serve.err" -Encoding UTF8 -TotalCount 10 -ErrorAction SilentlyContinue; if (Test-Path $RecLog) { $P = @(Select-String -Path $RecLog -Pattern '"primary":true').Count }; "PRIMARY_RECORDS_P=$P"; for ($t = 1; $t -le 4; $t++) { cmd /c "$PyExe -m whymath_backend.ops.cost_report --days 1 --json $Out\snap_3.json > $Out\snap_3.out 2> $Out\snap_3.err"; $ServOut = @(& $PyExe -c $JServ "$Out\snap_2.json" "$Out\snap_3.json" $P); "POLL $t / 4"; $ServOut; if ($ServOut -contains "SERVING_SAMPLE COUNTED") { break }; Start-Sleep -Seconds 30 } } else { "REFUSED=True — PRE_OK=$PreOk SNAP_2_READY=$Snap2Ready. §1·§5를 먼저 통과해야 합니다. 서버에 합성 트래픽을 보내지 않았습니다." }
```

**판정**: `SERVING_SAMPLE COUNTED`. `SHADOW_PROBE_EXIT=2`는 일부 제출이 HTTP 오류(401·429 등)로 실패했다는 뜻입니다 —
`serve.out`의 오류 회계를 회신해 주십시오(그래도 `COUNTED`가 나올 수 있고, 그것은 유효한 결과입니다).
`NO_PRIMARY_TURN_IN_SERVER_LOG`는 서버가 primary 경로를 타지 않았다는 뜻입니다 — 이전 세션의 좀비 서버가 8000을
잡고 있었을 가능성이 높습니다(§8 표).

---

## 7. 판정 요약 — 창 ② (읽기 전용)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 판정 요약(읽기 전용 · 다섯 파일이 모두 있어야 계산)
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$RecLog7 = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\wh1_shadow_records.log"
$PNow = 0
if (Test-Path $RecLog7) { $PNow = @(Select-String -Path $RecLog7 -Pattern '"primary":true').Count }
$AllFiles = ((Test-Path "$Out\probe.json") -and (Test-Path "$Out\sweep.json") -and (Test-Path "$Out\snap_0.json") -and (Test-Path "$Out\snap_1.json") -and (Test-Path "$Out\snap_2.json") -and (Test-Path "$Out\snap_3.json"))
if ($AllFiles) { "=== OPS-106 판정 요약 ==="; "[② 이중 회계]"; & $PyExe -c $JDual "$Out\probe.json" "$Out\snap_0.json" "$Out\snap_1.json"; "[③ 저작 분리]"; & $PyExe -c $JAuth "$Out\sweep.json" "$Out\snap_1.json" "$Out\snap_2.json"; "[① 서빙 계상]"; & $PyExe -c $JServ "$Out\snap_2.json" "$Out\snap_3.json" $PNow; "BASE_HEAD=$HeadNow  ORIGIN_MAIN=$MainNow" } else { "SUMMARY_SKIPPED=True — 필요한 결과 파일이 없습니다(probe=$(Test-Path "$Out\probe.json") sweep=$(Test-Path "$Out\sweep.json") snap_0=$(Test-Path "$Out\snap_0.json") snap_1=$(Test-Path "$Out\snap_1.json") snap_2=$(Test-Path "$Out\snap_2.json") snap_3=$(Test-Path "$Out\snap_3.json")). 어느 단계에서 멈췄는지 회신해 주십시오." }
```

---

## 8. 판정값 해석 — 틀린 값이 나왔을 때

| 판정 줄 | 값 | 의미 | 회신할 것 · 세션의 다음 조치 |
|---|---|---|---|
| `DUAL_ACCOUNTING` | `MATCH` | 프로세스가 센 수와 Langfuse가 센 수가 같다 — 전송·수집·집계 사슬이 이번에 살아 있다 | 없음 |
| | `SILENT_ZERO` | **프로세스는 N건을 냈는데 Langfuse는 0건** — 키·호스트·SDK·수집 어딘가가 말없이 끊김. `cost_report`가 exit 0으로 "0건"을 낸 바로 그 위장 | `snap_1.err`·`probe.err`의 `Langfuse … 실패(<예외 타입명>)` 줄 — §9의 진단 블록 |
| | `PARTIAL` | 일부만 도착 — 수집 지연이거나 일부 유실 | 값 그대로. 2~3분 뒤 §4의 for 루프(`cost_report` 부분)만 다시 돌려 증가하는지 확인 |
| | `EXCESS` | Langfuse가 더 많이 셈 — 같은 창에 다른 `probe` 트래픽이 섞임(다른 세션·이전 실행) | 값 그대로 — 결론 보류 |
| | `INPROC_ZERO` | 프로브 성공이 0건 — Ollama 문제. 이 단계로는 Langfuse를 판정할 수 없음 | `probe.out`의 오류 표본. Ollama 확인 후 §4 재실행 |
| | `NO_SURFACE_AXIS` | `cost_report` JSON에 표면 축이 없음 — 클론의 코드가 OPS-105 이전 | §1 `CODE_MATCHES_ORIGIN_MAIN` 재확인 |
| `AUTHORING_SEPARATION` | `SEPARATED_MATCH` | 저작 N건이 `authoring`으로만 도착, 표본 불변 — OPS-84의 분리가 라이브에서 성립 | 없음 |
| | `LEAK_INTO_SAMPLE` | **저작 호출이 표본을 늘림** — 표지가 일부/전부 유실되어 서빙·미표기로 샘 | 값 그대로 — 게이트② 로컬 비율이 위장된 상태 |
| | `AUTHORING_UNLABELED` | 저작 이벤트가 표지 없이 도착(`unlabeled`↑) | 값 그대로 — 표지 배선 결함 |
| | `SILENT_ZERO` | 기대 이벤트가 있는데 Langfuse는 0건 | §9 진단 블록 |
| | `PROVIDER_DOWN_NO_CALLS` | Ollama가 전건 거절 — Langfuse와 무관 | Ollama 확인 후 §5 재실행 |
| | `PARTIAL` · `EXCESS` | 일부 도착 · 다른 저작 트래픽 혼입 | 값 그대로 |
| `SERVING_SAMPLE` | `COUNTED` | 서버의 WH-1 primary 호출이 프로덕션 싱크로 전송되어 학생 대면 표본으로 계상됨 | 없음 |
| | `NO_PRIMARY_TURN_IN_SERVER_LOG` | `"primary":true` 로그가 0건 — **서버가 primary 경로를 안 탔다**(좀비 서버·킬스위치·로그 미캡처) | §9의 포트 점검 블록 |
| | `SILENT_ZERO` | primary 턴은 있었는데 Langfuse에 어떤 표면으로도 안 옴 — 전송 단절, **또는** primary 턴이 LLM을 한 번도 부르지 않고 결정론 폴백만 탔음(둘을 이 숫자만으로는 못 가름) | `serve.err`·서버 `.demo_uvicorn.err.log`의 타입명 경고 — §9 |
| | `ARRIVED_UNLABELED` | 이벤트는 왔는데 `serving` 표지가 없음 — 앱 싱크의 표지 배선 결함 | 값 그대로 |
| | `ARITHMETIC_BROKEN` | `event_count ≠ serving + unlabeled` — 표본 제외 로직 결함 | 값 그대로 |
| | `OTHER_SURFACE_ONLY` | `serving`은 안 늘고 `authoring`/`probe`만 늘었음 — 다른 세션의 트래픽 혼입 | 값 그대로 |

**한계 (명시)**: ⓐ 서빙에는 LLM 호출 단위의 인프로세스 카운터가 없어 §6은 **등식이 아니라 "1건 이상 도착"** 까지만
증명합니다. ⓑ `cost_report --days 1`은 최근 24시간 창이라 24시간 가까이 지난 기준선과 비교하면 증가분이 줄어 보입니다
(이 런북은 기준선을 몇 분 전에 찍습니다). ⓒ 합성 트래픽의 분포는 실제 학생과 다릅니다(위 「먼저 알아 둘 세 가지」 2).
ⓓ `SILENT_ZERO`(서빙)는 "전송 단절"과 "LLM 미호출"을 이 한 숫자로 가르지 못합니다.

---

## 9. 진단 블록 — 판정이 `COUNTED`/`MATCH`가 아닐 때만 (읽기 전용)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 진단(읽기 전용) · 타입명 경고와 포트 점유자를 모아 보여줌
cd C:\Users\kiki\Desktop\__AI\WhyMath
$ErrLog = "$Repo\.demo_uvicorn.err.log"
$Lsn2 = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
"PORT_8000_LISTENERS=$($Lsn2.Count)  PIDS=$(($Lsn2 | Select-Object -ExpandProperty OwningProcess -Unique) -join ',')"
"RECORD_LOG_LINES_NOW=$(@(Get-Content $RecLog -ErrorAction SilentlyContinue).Count)"
"--- 서버 stderr 의 Langfuse 경고(예외 타입명 포함) ---"
Select-String -Path $ErrLog -Pattern "Langfuse" -Encoding UTF8 -ErrorAction SilentlyContinue | Select-Object -First 10 | ForEach-Object { $_.Line }
"--- 이번 실행의 조회·전송 경고(snap_*.err · probe.err · sweep.err) ---"
Select-String -Path "$Out\snap_*.err","$Out\probe.err","$Out\sweep.err" -Pattern "Langfuse" -Encoding UTF8 -ErrorAction SilentlyContinue | Select-Object -First 10 | ForEach-Object { "$($_.Filename): $($_.Line)" }
```

`PORT_8000_LISTENERS`가 2 이상이거나 PID가 §2의 서버와 다르면 이전 세션의 좀비가 포트를 잡고 있던 것입니다 —
`.\scripts\demo\stop_demo.ps1`을 창 ②에서 실행한 뒤 §2부터 다시 하십시오(`run_demo.ps1`도 기동 전 포트 점유자를 정리합니다).

---

## 10. 회신 목록

1. §1 출력 전체(`PRE_OK`와 `False`였던 줄 포함)
2. §3의 `SNAP_SURFACE_COUNTS` 줄·`RECORD_LINES_AT_START`
3. §4의 `COST_PROBE_EXIT`·`DUAL_ACCOUNTING`·`INPROC_SUCCESS_N`·`LANGFUSE_PROBE_DELTA` 줄
4. §5의 `SWEEP_EXIT`·`EXPECTED_EVENTS`·`LANGFUSE_AUTHORING_DELTA`·`AUTHORING_SEPARATION` 줄
5. §6의 `SHADOW_PROBE_EXIT`·`PRIMARY_RECORDS_P`·`LANGFUSE_SERVING_DELTA`·`SURFACE_LABELED_RATE`·`SERVING_SAMPLE` 줄
6. §7 요약 화면 전체
7. 판정이 성공 값이 아니었다면 §9 출력

세션이 수치를 MEMORY에 기록하고 게이트 `G-ops106-gate2-live-sample`을 닫습니다. 게이트② 합격 판정(로컬 ≥80% 등)은
이 계측 사슬이 `MATCH`·`SEPARATED_MATCH`·`COUNTED`로 확인된 **뒤**의 별건입니다.
