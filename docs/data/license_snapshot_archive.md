# 라이선스 스냅샷 아카이브 규약 (LIC-02)

> **목적**: 법적 안전조합(`licensing_safety.md`)이 의존하는 외부 소스의 약관/라이선스 페이지를
> **확인 시점 원문(바이트)** 그대로 보관한다. 약관은 언제든 바뀔 수 있고 바뀐 뒤에는 과거를
> 재구성할 수 없다(★소급 불가 — 저작권 K4 계약). 스크립트: `scripts/ops/license_snapshot_archiver.py`.

## 1. Tier1 목록 확정 (licensing_safety.md 대조 실측)

### 도출 규칙 (재현 가능)
`docs/data/licensing_safety.md`의 매트릭스 테이블(한국 자원·글로벌 자원·LLM 학습 데이터셋)에서:

1. **외부 소스** — 자체작성(와이매스 *) 행 제외 (외부 약관이 존재하지 않음)
2. **상업 OK ✅ (무조건부)** — ⚠️(SA·NC·협상·확인필요)·❌(금지·격리) 행 제외 (백본 아님)
3. **외부 약관/라이선스 문서 실재** — "사실정보" 행(평가원 구조메타·EBS 메타·교과서 목차·KICE
   구조메타)은 제외: 의존 근거가 *약관 허락*이 아니라 사실/표현 이분법이라 보관할 약관이 없음
4. L5 OCR 표(소프트웨어 의존성)는 제외 — 라이선스 전문이 패키지 배포물에 동봉되는 별개 축

### 실측 결과: **20곳** (선언 "14곳"과 차이 — 아래 대조 보고)

| # | source_id | 자원 (문서 행) | 라이선스 | URL | URL 출처 |
|---|---|---|---|---|---|
| 1 | `ncic` | NCIC 성취기준 | 공공누리 1유형 | https://www.ncic.go.kr/ | 공식 루트(문서 URL 부재) — 공공누리 표시·저작권 고지 시점 증거 |
| 2 | `kogl-license-types` | 공공누리 AI유형 (유형 본문·1유형 포함) | 공공누리 AI (2026-01) | https://www.kogl.or.kr/info/license.do | `copyright_guide_v2.md` §10.1 |
| 3 | `aihub` | AIHub 수학 데이터셋 (이용정책) | 영리 허용 (4조건) | https://aihub.or.kr/intrcn/guid/usagepolicy.do | `copyright_guide_v2.md` §10.1 |
| 4 | `schoolinfo` | 학교알리미 | 공공데이터 | https://www.schoolinfo.go.kr/ | 공식 루트(문서 URL 부재) |
| 5 | `openstax` | OpenStax | CC BY 4.0 | https://openstax.org/tos | 공식 사이트(문서 URL 부재) |
| 6 | `siyavula` | Siyavula | CC BY | https://www.siyavula.com/terms | 공식 사이트(문서 URL 부재) |
| 7 | `illustrative-mathematics` | Illustrative Math | CC BY 4.0 | https://illustrativemathematics.org/terms-of-use/ | 공식 사이트(문서 URL 부재) |
| 8 | `numinamath-cot` | NuminaMath-CoT | Apache 2.0 | https://huggingface.co/datasets/AI-MO/NuminaMath-CoT | 공식 데이터셋 카드 |
| 9 | `numinamath-tir` | NuminaMath-TIR | Apache 2.0 | https://huggingface.co/datasets/AI-MO/NuminaMath-TIR | 공식 데이터셋 카드 |
| 10 | `prm800k` | PRM800K | MIT | https://raw.githubusercontent.com/openai/prm800k/HEAD/LICENSE | 공식 저장소 LICENSE(raw·HEAD) |
| 11 | `phet` | PhET 시뮬레이션 | CC BY | https://phet.colorado.edu/en/licensing | 공식 라이선싱 페이지 |
| 12 | `metamath-set-mm` | Metamath set.mm | CC0 | https://raw.githubusercontent.com/metamath/set.mm/HEAD/LICENSE | 공식 저장소 LICENSE(raw·HEAD) |
| 13 | `omnimath` | OmniMath | 공개 | https://huggingface.co/datasets/KbsdJames/Omni-MATH | 공식 데이터셋 카드 |
| 14 | `minif2f` | miniF2F | 폴더별 상이(lean·isabelle=Apache 2.0 · metamath=MIT · hollight=FreeBSD) | https://raw.githubusercontent.com/openai/miniF2F/HEAD/README.md | 공식 저장소 README §License(raw·HEAD) — LICENSE 파일 부재 실측(404), README가 선언 원문. **폴더 4종**(종전 3종 표기는 `isabelle` 누락 · LIC-04 정정) · 우리가 쓰는 488 Lean은 Apache 2.0 |
| 15 | `olymmath` | OlymMATH | 공개 | https://huggingface.co/datasets/RUC-AIBOX/OlymMATH | 공식 데이터셋 카드 |
| 16 | `mathlib4` | Mathlib4 | Apache 2.0 | https://raw.githubusercontent.com/leanprover-community/mathlib4/HEAD/LICENSE | 공식 저장소 LICENSE(raw·HEAD) |
| 17 | `gsm8k` | GSM8K (문서 행 "GSM8K · MATH"의 앞) | MIT | https://raw.githubusercontent.com/openai/grade-school-math/HEAD/LICENSE | 공식 저장소 LICENSE(raw·HEAD) |
| 18 | `math-hendrycks` | MATH (문서 행 "GSM8K · MATH"의 뒤) | MIT | https://raw.githubusercontent.com/hendrycks/math/HEAD/LICENSE | 공식 저장소 LICENSE(raw·HEAD) |
| 19 | `openmathinstruct-1` | OpenMathInstruct-1 | NVIDIA License | https://huggingface.co/datasets/nvidia/OpenMathInstruct-1 | 공식 데이터셋 카드 |
| 20 | `dlmf` | DLMF | US Gov Work | https://dlmf.nist.gov/about/notices | 공식 사이트(경로 미확정 — 404 시 교체 후속) |

`source_id`는 **안정 슬러그**다 — 감사로그·스냅샷 디렉터리의 영속 키이므로 변경 금지
(URL은 바뀔 수 있어도 id는 유지).

### "14곳" 선언 대조 보고 (문서 실측 우선 — 차이 명시)

- **선언 출처**: `docs/legal/copyright_guide_v2.md` §11 Day 1-2 — "Tier 1 데이터셋 14개에 대해
  license_url, license_verified_at 기록" (2026-05-27 가이드 시점). 같은 가이드의 Tier 1 표를
  소스 단위로 세면 백본 4(NCIC·UK OGL·ACARA·Common Core) + 학습 5(NuminaMath 1.5·PRM800K·
  GSM8K·MATH·OpenMathInstruct-1) + AIHub 1 + PhET 1 + 검산 3(Mathlib·Isabelle AFP·Metamath)
  = **14** (국제 비교 3곳 제외 셈) — "14"는 이 시점 표의 계수로 추정된다.
- **정본(licensing_safety.md) 실측 = 20곳**. 차이 사유:
  1. 가이드 14 중 **4곳(UK OGL·ACARA·Common Core·Isabelle AFP)은 licensing_safety.md
     매트릭스에 행이 없다**(§등급 체계 산문·`dataset_catalog_v4.md`에만 등장). 정본 대조
     원칙상 이번 목록에서 제외 — 매트릭스에 행이 추가되면 그때 편입한다(OPS-56 축 후보).
  2. 매트릭스에는 가이드 표에 없는 ✅ 소스 10곳이 있다(학교알리미·OpenStax·Siyavula·
     Illustrative Math·NuminaMath-CoT/TIR·OmniMath·miniF2F·OlymMATH·DLMF) — 전부 편입.
  3. NuminaMath **1.5**는 매트릭스에 행이 없다(CoT/TIR만) → 제외 (1과 같은 원칙).
  4. MathNet(⚠️ 확인 필요·Tier 0 격리)·CK-12(NC)·SA류(AoPS·LibreTexts)·KICE는 Tier1이 아니다.
     단, 라이선스 *변경 모니터링* 관점에서 NRICH·MathNet은 확장 후보(§Review 주기의 명시
     모니터링 대상) — Tier1 승격이 아니라 **관찰 대상 별도 그룹**으로 후속 검토.

## 2. 저장 구조 (`data/licenses/` — git 추적, 커밋 가능한 증적)

```
data/licenses/
├── audit_log.jsonl                     # append-only 감사로그 (진실 원천 — 수정·삭제 금지)
├── runs/
│   └── <run_id>.json                   # run manifest — 실행 1회의 식별·계획·진행·결말
└── snapshots/
    └── <source_id>/
        ├── <sha256[:16]>.html|.txt|.bin  # content-addressed 스냅샷 (원문 바이트 그대로)
        └── <sha256[:16]>.meta.json       # 스냅샷 메타 (최초 수집 시각·URL·전체 SHA256)
```

- **content-addressed**: 파일명 = 본문 SHA256 앞 16 hex (전체 해시는 메타·감사로그에).
  같은 내용은 같은 파일명 → 재수집해도 파일이 늘지 않는다. 스냅샷 파일은 **불변**
  (재수집 시 덮어쓰지 않음 — 존재하면 쓰기 생략).
- **확장자**: Content-Type 기준 — html→`.html`, 그 외 text/JSON→`.txt`, 그 외→`.bin`.
- **run manifest**: 실행 시작 즉시 `status: "running"`으로 기록되고 소스마다 갱신된다.
  `"completed"`로 끝나지 않은 manifest = 중단된 실행의 증거(이전 실행 오독 방지).

## 3. 감사로그 규약 (`audit_log.jsonl`)

**append-only** — 라인 수정·삭제 금지. 실행마다 소스당 정확히 1라인. 각 라인은 기록 직후
flush+fsync된다(중간에 죽어도 그때까지의 관측이 남는다). 필드:

| 필드 | 타입 | 항상 | 의미 |
|---|---|---|---|
| `ts` | str | ✅ | 관측 시각 (UTC ISO8601) |
| `run_id` | str | ✅ | 이번 실행 식별자 (`YYYYMMDDThhmmssZ-<hex6>`) |
| `source_id` | str | ✅ | Tier1 소스 슬러그 |
| `url` | str | ✅ | 수집 URL |
| `event` | str | ✅ | `new` / `unchanged` / `changed` / `fetch_failed` |
| `http_status` | int | 응답 시 | HTTP 상태코드 |
| `content_type` | str | 성공 시 | 응답 Content-Type |
| `sha256` | str | 성공 시 | 본문 전체 SHA256 (바이트 기준) |
| `prev_sha256` | str | changed 시 | 직전 관측 해시 (변경 감지 증거) |
| `bytes` | int | 성공 시 | 본문 크기 |
| `snapshot_path` | str | 성공 시 | 보관소 기준 상대 경로 |
| `elapsed_ms` | int | ✅ | 소요 시간 |
| `error_type` | str | 실패 시 | `HTTP<코드>` / `Timeout` / 예외 타입명 |
| `error_detail` | str | 실패 시 | HTTP=본문 발췌(≤400B) · Timeout=타임아웃 사실 · 예외=메시지 |

### 멱등·변경 감지 판정 (변별력 규약)

- 판정 기준은 **본문 바이트의 SHA256뿐** — 정규화·표기 통일 없음. 수집 시각·헤더는
  메타에만 기록되어 동일성 판정을 오염하지 않는다(표기 차이 오탐 방지).
- `new` = 해당 소스의 첫 성공 관측 / `unchanged` = 직전 관측과 해시 동일(파일 신규 생성 0) /
  `changed` = 해시 상이(새 스냅샷 파일 + `prev_sha256` 기록).
- 직전 관측 해시는 감사로그를 스캔해 복원한다(로그가 진실 원천). 파싱 불가 라인은
  라인 번호+예외 타입명을 stderr에 남기고 건너뛴다(침묵 실패 금지).
- **알려진 한계**: 동적 요소(CSRF 토큰·타임스탬프)가 본문에 있는 페이지는 실제 약관이
  안 바뀌어도 `changed`가 발화할 수 있다(과탐 방향 — 놓침 방향이 아님). 약관 원문 보관이라는
  1차 가치는 영향 없다. 과탐이 소음이 되면 본문 정규화는 후속 태스크로 별도 설계한다.

## 4. 실행 규약

```
python scripts/ops/license_snapshot_archiver.py [--out data/licenses] [--sources id1,id2]
                                                [--timeout 30] [--delay 1.0] [--list]
```

- **exit code가 판정이다**: `0` 전곳 성공 · `1` **0곳 성공(측정 실패 — 0건 통과 위장 금지)** ·
  `2` 사용법 오류(알 수 없는 source_id 등) · `3` 부분 실패(성공·실패 혼재).
- 수집 예절: 실행 1회당 소스당 정확히 1요청(재시도는 다음 실행) · 요청 간 지연 기본 1.0s ·
  UA `WhyMathLicenseArchiver/1.0` 명시. 프록시는 표준 환경변수(`HTTPS_PROXY`)를 urllib
  기본 동작으로 존중(샌드박스·Kiki 머신 공통).
- 의존성: **표준 라이브러리만** (backend 패키지 import 금지 — Kiki 머신 단독 실행 가능).

## 4-A. 집행 완료 — 20/20 확보 (2026-08-31)

**카탈로그 20곳 전곳 확보.** 게이트 `G-license-snapshot-blocked-sources` **cleared**.

| 회차 | 환경 | 결과 |
|---|---|---|
| 1차 (08-30) | 원격 세션(샌드박스) | 6/20 — 14곳이 egress 프록시 403(조직 정책) |
| 2차 (08-31) | Kiki 머신(Phaiakes9) | 19/20 — 신규 13곳(`run_id=20260831T005458Z-b0b14e`) |
| 3차 (08-31) | Kiki 머신 | **20/20** — siyavula URL 정정 후 1/1(`run_id=20260831T013601Z-8daf15`) |

판정은 `python scripts/ops/license_snapshot_coverage.py` → **exit 0**(기계 판정). 부분 확보를
성공으로 읽지 않는 이 판정기가 없었다면 19/20에서 게이트가 닫혔을 것이다(PR #915 리뷰 P1).

### siyavula — 원인과 해소 (기록)

구 URL `https://www.siyavula.com/terms`는 **HTTP 404**였다. egress 차단이 아니라 URL 결함이며
(망 제약 없는 Kiki 머신에서도 동일), 재실행으로는 해소되지 않는 부류였다. 홈페이지 href 스캔으로
실제 경로 `https://www.siyavula.com/info/terms-and-conditions`를 발견해 카탈로그를 정정했다(#918).
같은 스캔에서 `/info/privacy-policy`도 키워드에 걸렸으나 **개인정보처리방침은 라이선스 조항이
아니므로 채택하지 않았다**.

### 내용 검증 결과 (성공 기준 2중의 두 번째 축)

수집 원문(158,035바이트)에서 실측: `creative commons` ×6 · `license`류 ×24 · `copyright` ×9 ·
`terms and conditions` ×26. 원문에 **CC BY 부여 조항이 실재**한다:

> "Some material on the site is licensed under a **Creative Commons Attribution Only License**.
> That means that anyone is free to Share, and Remix that content as long as he or she attributes
> the author…"

**⚠️ 적용 범위 단서(법적 주의)**: 같은 원문이 CC BY의 범위를 한정한다 — "**Some** material" ·
"**Only material that is clearly marked** with a Creative Commons license can be re-used without
permission". 즉 **사이트 전체가 CC BY가 아니라 명시 표기된 자료에 한정**된다. 귀속 문구도
저자명 + `From www.everythingmaths.co.za` 또는 `From siyavula.com` 표기를 요구한다.
매트릭스(`licensing_safety.md`) 반영 = **`LIC-05` 완료(2026-09-07)** — 같은 태스크의 전수 재점검에서
**Illustrative Math**도 같은 유형으로 드러났다: 약관 §7이 판(edition)별로 라이선스를 나눠, 초판
K–12 Math(2019–2021)는 CC BY 4.0이지만 **v.360(2024·TK 2025)은 CC BY-NC 4.0**으로 상업 이용을
명시 금지한다. 상용 서비스인 우리에겐 초판만 사용 가능하다.

> 이 단서는 URL 정합성만 봤다면 드러나지 않았다 — 리뷰가 요구한 **내용 검증** 스텝이
> 잡아낸 것이며, 스냅샷 확보의 실익이 "보관"을 넘어 **"대조 가능"**에 있음을 보여준다.

## 5. 집행 별항 (정본화 ≠ 집행)

- **이 문서·스크립트 = 정본화**. 주기 재수집(cron·분기 라이선스 점검 연동)은 **OPS-56 축과
  조율하는 후속 태스크** — 1차 집행은 **수동 1회 실행 증적**(감사로그·manifest·스냅샷이
  `data/licenses/`에 커밋됨)이다.
- 계약 동결: `tests/infra/test_license_snapshot_archiver.py` (성공/HTTP 실패/타임아웃/예외/
  변경 감지/멱등/즉시 flush/exit 코드 — 경로별 상이 신호, hermetic·네트워크 0).

### 5-A. 런북 프로브 실패 기록 4건 (완료 — 재실행 불요·교훈 보존용)

siyavula URL 확정 과제는 **2026-08-31 완료**됐다(§4-A). 그 과정에서 원격 세션이 작성한
PowerShell 블록이 **4번 실패**했고, 네 결함이 전부 같은 축으로 수렴한다 —
**실패가 성공처럼 보이거나, 실패 원인이 남지 않는다**. 다음 런북 작성자를 위해 남긴다.

| # | 결함 | 증상 | 교훈 |
|---|---|---|---|
| ① | `-UseBasicParsing` 누락 | PS 5.1이 IE 파싱 경고 대화상자를 띄워 **절차가 프롬프트에서 정지** | 복붙 런북은 사람 입력을 요구하는 지점이 없어야 한다 |
| ② | catch의 진단 문자열이 파이프라인 출력 | `return $null`에도 반환값 오염 → 호출부가 실패를 성공으로 오인 | 진단은 `Write-Host`로 — 반환값과 분리 |
| ③ | `$home` **자동 변수**에 대입 | 대입 거부 후 `if ($home)`이 홈 경로 문자열로 **참** → 가짜 성공 | 자동 변수(`$home`·`$host`·`$input`·`$error`·`$args`·`$pwd`) 회피 + 판정을 truthiness가 아니라 **필드 실재**로 |
| ④ | `if {...}` / `else {...}`를 **여러 번에 나눠 붙여넣기** | PS 대화형이 `if`를 완결 문으로 파싱 → `else`가 고아가 되어 `CommandNotFoundException`, **검증 스텝이 통째로 미실행** | 대화형 붙여넣기용 블록은 `if/else` 대신 **단일 문 흐름**으로 쓰거나 한 덩어리로 붙여넣게 명시 |

④는 특히 위험했다 — 커버리지는 통과했는데 **내용 검증만 조용히 건너뛰어졌다**. 성공 기준을
2중으로 잡아 두지 않았다면 "coverage=0이니 완료"로 닫혔을 것이다(실제 검증은 나중에 스냅샷이
커밋된 뒤 세션이 저장소에서 직접 수행했다 — 그것이 가능했던 이유는 증거가 git에 있었기 때문).

**구조적 원인**: 원격 세션은 PowerShell을 실행 검증할 수 없다(Windows 부재 + 대상 호스트
egress 403). 그런데 저장소 가드 `scripts/ops/check_ps_scripts.py`는 `scripts/**/*.ps1`만 훑어
**런북 마크다운 코드펜스가 검사 범위 밖**이다 — Kiki에게 건네는 PowerShell 대부분이 사는 곳이
정확히 그 사각이다. 가드 확장 = `OPS-57`(위 4종을 규칙화).

### Kiki 머신 수동 실행 (Windows PowerShell)

> **1. 과제**: 샌드박스 egress 정책에 막힌 **14곳**의 약관 스냅샷 수집 (게이트
> `G-license-snapshot-blocked-sources`).
> **2. 목적**: *확인 시점의* 약관 원문 보관 — **소급 불가**다. 나중에 약관이 바뀌면 "우리가 쓸
> 당시 조건이 이랬다"를 증명할 방법이 영구히 사라진다(저작권 K4 계약).
> **3. 절차**: origin/main에서 **작업 브랜치 생성**(로컬 main은 건드리지 않는다) → 아카이버
> 1회 실행(20곳 순회·이미 받은 6곳은 `unchanged`로 건너뜀·소스당 타임아웃, 총 1~3분) →
> **커버리지 판정**(exit code) → 커밋·브랜치 push → PR.
> **4. 성공 기준**: **`coverage=0`이 유일한 성공이다.** 아카이버 자신의 exit(0/3)이나 스냅샷
> 개수 증가는 **성공 기준이 아니다** — 20곳 중 1곳만 받아도 exit 3이고 개수는 늘기 때문에,
> 그것으로 판정하면 13곳이 영구 미확보인 채 게이트가 닫힌다. `coverage=1`이면 아직 미확보가
> 있는 것이고(출력에 미확보 id가 전건 나온다) 게이트는 열린 채로 둔다. `coverage=2`는 판정
> 불가(감사로그 파손 등)이니 출력을 그대로 알려 달라.
> **5. 실행 환경**: Windows PowerShell(=Phaiakes9 본체), 작업 디렉터리
> `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건 없음(표준 라이브러리만·서버·DB 불요).
> **6. 창 구분**: **새 창** 1개. 장기 점유 프로세스가 없어 같은 창에서 계속 작업 가능.

```powershell
# [실행 시스템: Windows PowerShell — 새 창. Phaiakes9 본체이므로 SSH·WSL 진입 불요]
cd C:\Users\kiki\Desktop\__AI\WhyMath

# origin/main 기준으로 작업 브랜치 생성 — 로컬 main을 병합·이동시키지 않는다
# (pull은 로컬 main이 갈라져 있으면 머지 커밋·충돌을 낸다 — HARN-06 실측 선례)
git fetch origin main
git checkout -B claude/lic-02-snapshot-capture origin/main

python scripts\ops\license_snapshot_archiver.py
echo "archiver=$LASTEXITCODE"    # 참고값 — 0=전곳 / 3=부분 / 1=0곳(네트워크 문제) / 2=사용법

# ★ 성공 판정은 이것 하나 — 0이라야 전곳 확보다
python scripts\ops\license_snapshot_coverage.py
echo "coverage=$LASTEXITCODE"    # 0=전곳 확보(게이트 clear 가능) / 1=미확보 있음 / 2=판정 불가
```

수집분 제출 (위 `coverage` 값과 무관하게, 받은 만큼은 반드시 커밋한다 —
부분 확보라도 그 스냅샷은 소급 불가 자산이다):

```powershell
# [실행 시스템: Windows PowerShell — 같은 창]
git add data\licenses
git commit -m "LIC-02 집행: 차단됐던 라이선스 약관 스냅샷 수집 (G-license-snapshot-blocked-sources)"
git push -u origin claude/lic-02-snapshot-capture
```

> **main에 직접 push하지 않는다** — 이 저장소는 PR·CI 경유가 기본값이고 main은 브랜치 보호
> 대상이다. push 후 알려주시면 다음 Claude 세션이 PR을 열고, `coverage=0`일 때만 게이트를
> clear한다(부분 확보면 게이트는 남은 id 목록과 함께 유지된다).

**왜 샌드박스에서 못 받았나 (실측·2026-08-30)**: 원격 세션의 egress 프록시가 14곳을
`Tunnel connection failed: 403 Forbidden`으로 거부했다 — 조직 egress 정책이며 프록시 README가
**"우회하지 말고 보고하라"**고 명시한다(CLAUDE.md "거부(deny)의 우회 금지"와 동일 취지).
코드 결함이 아니므로 아카이버 수정으로는 해소되지 않는다. 남은 실패는 감사로그에
`error_type`/`error_detail`로 전건 기록돼 있다.

---

**작성**: 2026-08-30 (LIC-02 — EOS-53 crosswalk 갭 G6). 목록 정본: `licensing_safety.md` 매트릭스.
스크립트↔이 문서의 source_id 동기는 `tests/infra/test_license_snapshot_archiver.py`가 기계 대조한다.
