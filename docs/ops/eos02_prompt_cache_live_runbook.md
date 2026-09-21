# EOS-02 — 프롬프트 캐시 라이브 계측 회차 (Kiki 실행 런북)

> 이 문서는 `EOS-02-prompt-cache-live-measurement` acceptance ①의 **실행 절차**다.
> 세션은 도구를 만들지 않는다 — 계측은 `EOS-99`가 이미 배선했고(`prompt_cache` 리포트 블록),
> 여기서 필요한 것은 **실 Anthropic 키로 한 회차를 돌리는 것**뿐이다.
>
> **검증 기준: main `1abf743b`** — 아래 명령·플래그·기본값은 전부 그 커밋의 trunk 코드에서
> 확인했다(`problem_corpus_accumulate.main()` 인자 정의 · `config.Settings` 필드 ·
> `anchor_round_ledger.prompt_cache_rates()` 상태 어휘).

---

## 1. 과제 명칭

프롬프트 캐시 **적중률 라이브 1회차 계측** — "켰다"와 "작동했다"를 실측으로 가른다.

## 2. 목적

`WHYMATH_ANTHROPIC_PROMPT_CACHING`은 현재 기본값 **False**다. 켜는 판단을 하려면 적중률이
필요한데, **적중은 실 Anthropic 키로만 관측된다**(hermetic 테스트로는 정의되지 않는다).

이 회차의 산출은 리포트의 `prompt_cache` 블록 3개 값이며, 그것이 곧 `EOS-02` acceptance ③
(기본값 전환 여부)의 **유일한 판정 재료**다. 계측 없이 켜지 않는다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 예상 출력 | 소요 |
|---|---|---|---|
| ① 최신화 | main을 당긴다 | `Already up to date.` 또는 fast-forward | ~10초 |
| ② 선행 자가검증 | 키 존재·플래그를 **실행 전에** 확인 | `KEY_OK=True` / `CACHE_FLAG=true` | 즉시 |
| ③ 회차 실행 | Sonnet(CLOUD_MID)으로 10회 저작 시도 | 리포트 JSON이 화면 + 파일에 남음 | 3~8분 |
| ④ 자가검증 | 저장된 리포트에서 3개 값을 뽑아 출력 | `state` / `hit_rate` / `calls_with_cache_telemetry` | 즉시 |

**클라우드로 나가려면 `--subscription premium --budget-krw 5000` 을 둘 다 줘야 한다.**
하나만 주거나 안 주면 라우터가 LOCAL로 강제해 클라우드 호출이 0건이 되고, 계측이 공전한다
(2026-09-07 실측: free/0=local · free/5000=local · premium/0=local · **premium/5000=cloud_mid**).

예상 비용: Sonnet 10회 저작 — **수백 원 수준**(정확한 값은 리포트의 비용 필드로 확인).

## 4. 성공 기준

**판정은 exit code가 아니라 리포트의 `prompt_cache` 블록으로 한다.** 이 CLI의 exit code는
*코퍼스 수용 여부*를 말하지 캐시 계측 성패를 말하지 않는다(코드 실측: 리포트 JSON은 exit
분기 **이전**에 stdout으로 나간다 — `problem_corpus_accumulate.py` L887).

- `exit 0` = 신규 수용 ≥1 · `exit 1` = 이번 회차 수용 0 · `exit 2` = 연속 무진전 알람
- **셋 중 무엇이든 `prompt_cache` 블록은 남는다.** 캐시 계측 관점에서 exit 1·2는 실패가 아니다.

### 성공

`calls_with_cache_telemetry > 0` — 여기까지 와야 ①이 성립한다. 그 다음 `state`를 읽는다:

| `state` | 의미 | 다음 |
|---|---|---|
| `enabled_working` | 켰고 적중 있음 | `hit_rate`가 (n-1)/n에 근접하면 정상 |
| `enabled_not_working` | **켰는데 적중 0%** | 이 태스크가 존재하는 이유 — 원인 규명(프리픽스가 최소 캐시 토큰 미만인지 · 회차마다 프리픽스가 갈리는지) |
| `disabled_but_hit` | 껐다고 읽었는데 적중이 잡힘 | 리포트가 읽은 플래그와 실제 설정이 다르다는 신호 |

### 실패

`calls_with_cache_telemetry == 0` (→ `state: not_applicable`) — **적중 0%가 아니라 미측정**이다.
클라우드로 안 나갔다는 뜻이므로 **적중률을 읽지 말고 플래그부터 확인한다**: ②단계 출력에서
`CACHE_FLAG=true`였는지, 명령에 `--subscription premium --budget-krw 5000`이 둘 다 있었는지.

## 5. 실행 환경

- **Windows PowerShell** (= Phaiakes9 그 자체 · 별도 접속·SSH 불요)
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath`
- 선행 조건: `WHYMATH_ANTHROPIC_API_KEY`가 User 환경변수에 등록돼 있을 것 (②단계가 확인한다)
- Ollama 기동은 **불요** — 이 회차는 클라우드 경로를 태운다

## 6. 창 구분

**새 PowerShell 창 1개**로 충분하다. 장기 점유 프로세스가 없고(CLI는 끝나면 종료된다)
서버를 띄우지 않으므로, 이 창은 실행 후에도 계속 써도 된다.

---

## 실행 블록 (통째로 복사-붙여넣기)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 — 별도 접속 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 0) 최신화
git checkout main
git pull origin main

# 1) 선행 자가검증 — 키가 있는가 (값은 출력하지 않는다)
$KeyRaw = $env:WHYMATH_ANTHROPIC_API_KEY
$KeyOk = ($KeyRaw -ne $null) -and ($KeyRaw.Length -ge 40) -and ($KeyRaw -notmatch '…|\.\.\.')
"KEY_OK=$KeyOk  (길이 $($KeyRaw.Length))"

# 2) 이 창에서만 캐시 플래그를 켠다 (영구 설정 아님 — 기본값 전환은 계측 후 판단)
$env:WHYMATH_ANTHROPIC_PROMPT_CACHING = "true"
"CACHE_FLAG=$($env:WHYMATH_ANTHROPIC_PROMPT_CACHING)"

# 2-a) 파이프 인코딩 고정 — 리포트에 한글이 들어가고 이 창의 로케일은 cp949다.
#      고정하지 않으면 파이프를 타는 순간 깨지거나 UnicodeEncodeError로 죽는다.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 3) 회차 실행 — 리포트를 화면과 파일 양쪽에 남긴다(실패해도 증거가 남게).
#    stderr는 합치지 않는다 — 알람 문구가 JSON 뒤에 붙으면 4)의 파싱이 깨진다.
New-Item -ItemType Directory -Force -Path work\eos02 | Out-Null
if ($KeyOk) {
  python -m whymath_backend.harness.problem_corpus_accumulate `
      --seed data\corpus\problem_bank_generated_v0\problems.jsonl `
      --out data\corpus\problem_bank_llm_live\eos02_cache_probe.jsonl `
      --n 10 `
      --subscription premium `
      --budget-krw 5000 `
      --standard-code "[9수02-20]" `
      --difficulty 2.5 `
      --topic-hint "중3 이차방정식 — 두 근 중 더 큰 근을 구하는 형태(답 하나)" `
      | Tee-Object -FilePath work\eos02\round_report.json
  "EXIT=$LASTEXITCODE  (0=수용≥1 · 1=수용0 · 2=무진전알람 — 셋 다 계측은 유효)"
} else {
  "중단: WHYMATH_ANTHROPIC_API_KEY 미설정 또는 자리표시자 — 키 등록 후 다시 실행"
}

# 4) 자가검증 — 저장된 리포트에서 판정 재료 3개만 뽑는다
if (Test-Path work\eos02\round_report.json) {
  $Txt = Get-Content work\eos02\round_report.json -Raw
  $Json = $Txt.Substring($Txt.IndexOf('{')) | ConvertFrom-Json
  $Pc = $Json.prompt_cache
  "state                      = $($Pc.state)"
  "hit_rate                   = $($Pc.hit_rate)"
  "calls_with_cache_telemetry = $($Pc.calls_with_cache_telemetry)"
  "→ calls_with_cache_telemetry 가 0 이면 클라우드로 안 나간 것(미측정). 적중률을 읽지 말 것."
} else {
  "리포트 파일 없음 — 3)단계가 실행되지 않았다(KEY_OK 확인)"
}
```

## 회신해 주실 것

4)단계 출력 3줄(`state` · `hit_rate` · `calls_with_cache_telemetry`)과 `EXIT=` 줄.
그 값으로 acceptance ②(정상 판정)와 ③(기본값 전환 여부)을 세션이 판정한다.

원문 리포트 전문이 필요하면 `work\eos02\round_report.json`에 남아 있다
(`work\`는 gitignore 대상이라 커밋되지 않는다).
