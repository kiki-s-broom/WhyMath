# 런북 — 헌법 토큰 실측 (HARN-121 ①)

> 실행 주체: **Kiki** · 실행 머신: **Phaiakes9** (실 Anthropic 키가 있는 유일한 곳)
> 게이트: `G-harn121-constitution-token-measure`

## 1. 과제 명칭

`CLAUDE.md` · `AGENTS.md` · SessionStart 브리핑의 **실토큰 수 측정**.

## 2. 목적

반복 실패 보고서는 세션 고정비를 "4.5만~6.8만 토큰"으로 적으면서 **추정임을 명시**한다
(문자 구성 기반). 헌법 다이어트의 목표가 "코어 ≤ 1.5만 토큰"인데 분모가 추정이면
달성 여부를 판정할 수 없다. 이 측정이 그 분모를 확정한다.

결과는 `metrics/constitution_tokens.json`에 남고, 3분리(HARN-121 ②)의 전후 비교
기준선이 된다.

**tiktoken으로 대체하지 않는 이유**: tiktoken은 OpenAI BPE이고 Claude 토크나이저가
아니다. 한국어 비중이 높은 문서에서 둘의 차이는 작지 않아, 그 수를 "실측"이라 부르면
보고서가 배제한 추정을 이름만 바꿔 되살리는 것이 된다. 그래서 스크립트는 키가 없으면
**측정하지 않고 exit 2로 거부**한다.

## 3. 구체적 절차

세 단계이고 전부 합쳐 **2~3분**이다. API 호출 3회(문서 3종)라 비용은 무시할 수준이다.

1. 저장소를 최신 main으로 맞추고 스크립트 실재를 확인한다 (약 20초)
2. 키 자가검증 — 등록된 키가 온전한지 본다 (약 5초, 키 값은 출력하지 않는다)
3. 측정 실행 — 표와 JSON이 나온다 (약 30초)

## 4. 성공 기준

- **성공**: `합계(측정분만) NN,NNN 토큰` 줄이 나오고 `metrics/constitution_tokens.json`이 생긴다
- **실패 A**: `ANTHROPIC_API_KEY 없음` → 키가 현재 셸에 없다. 5-A 참조
- **실패 B**: `미측정 N건` 이 표시됨 → 합계는 **하한**이다. 사유 문자열을 그대로 회신
- **실패 C**: `anthropic SDK 없음` → 5-B 참조

## 5. 실행 환경

Windows PowerShell (= Phaiakes9 그 자체 · SSH 불요). 작업 디렉터리는
`C:\Users\kiki\Desktop\__AI\WhyMath`. Docker·서버 가동 불요 — 파일만 읽는다.

## 6. 창 구분

**새 창 1개**로 끝난다. 장기 점유 프로세스가 없으므로 이후 조작 제한도 없다.

---

## 실행 블록

### 블록 1 — 저장소 동기화 + 자가검증

이 클론은 여러 세션이 공유하는 단일 작업 사본이라, 다른 세션이 브랜치를 전환해 뒀을
수 있다. 그래서 **기대 상태를 눈으로 확인**하는 줄을 함께 둔다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout -B harn121-token-measure origin/main
git log -1 --oneline
Test-Path scripts\ops\measure_constitution_tokens.py
```

> 확인: 마지막 두 줄이 **커밋 1줄**과 **True**를 내야 합니다. `False`가 나오면 이
> 스크립트가 아직 main에 없다는 뜻이니 중단하고 알려 주세요 (그대로 진행하면 3단계가
> "파일 없음"으로 끝납니다).

### 블록 2 — 키 자가검증 (키 값은 출력하지 않습니다)

```powershell
$k = $env:ANTHROPIC_API_KEY
if (-not $k) { "KEY=없음 — 이 창에 키가 설정되지 않았습니다 (5-A 참조)" } else { "KEY=있음 · 길이 $($k.Length) · 생략문자포함 $($k.Contains([char]0x2026))" }
```

> 확인: `KEY=있음`이고 **길이가 100자 이상**, **생략문자포함 False**여야 합니다.
> `True`가 나오면 자리표시자(`sk-ant-…` 형태)가 그대로 등록된 것이라 측정이 인증
> 실패로 끝납니다 — 그 경우 실제 키 전체로 다시 등록해 주세요.

### 블록 3 — 측정

블록 2가 `KEY=있음`이고 생략문자포함 `False`일 때만 붙여넣으세요. 이 블록은 그것을
**스스로 다시 확인하고 아니면 거부**합니다.

```powershell
$k = $env:ANTHROPIC_API_KEY
$ok = ($k) -and ($k.Length -ge 100) -and (-not $k.Contains([char]0x2026))
if ($ok) { python -m pip install -q anthropic; python scripts\ops\measure_constitution_tokens.py --out metrics\constitution_tokens.json } else { "MEASURE_REFUSED=True — 키가 없거나 자리표시자입니다. 블록 2 결과를 확인하세요." }
```

## 회신해 주실 것

블록 3의 출력 전문(표 + 합계 줄)을 그대로 붙여 주세요. `미측정` 줄이 있으면 그 사유
문자열도 함께 주세요 — 그것이 다음 조치를 정합니다.

## 실패 시 대처

**5-A · 키가 없을 때**: 이 창에만 임시로 넣는 방법입니다(영구 등록 아님).

```powershell
$env:ANTHROPIC_API_KEY = "여기에_실제_키_전체"
```

> 넣은 뒤 블록 2를 다시 돌려 `생략문자포함 False`를 확인하고 블록 3으로 가세요.

**5-B · SDK가 없을 때**: 블록 3이 이미 `python -m pip install -q anthropic`을 포함합니다.
그래도 실패하면 콘다 base와 `.venv`가 섞였을 수 있으니 출력 전문을 보내 주세요.
