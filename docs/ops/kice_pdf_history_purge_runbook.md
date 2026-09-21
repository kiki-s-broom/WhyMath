# KICE 연구보고서 PDF 제거 — 실행 기록 및 교훈 (LIC-07 ①③ 실행분)

> **상태: 제거 실행 + 재유입 방지 가드 완료 (2026-09-06)** · 판정 기준: main `3f2b39c1`
> **정본은 `backlog/tasks/LIC-07-kice-report-pdf-git-history.yaml`이지 이 문서가 아니다** —
> 태스크 `status`를 보고 판단하라(§7).
> **결과**: 두 브랜치 삭제로 PDF 제거 완료. 새 clone에서 KICE blob **0건** 실측(§2).
> **이 문서는 지시서가 아니라 기록이다** — 처음 설계했던 *브랜치 재작성* 방식은 실행 중
> **이 저장소에서 구조적으로 불가능**함이 드러났고, 실제로 통한 방법은 그게 아니었다.

---

## 1. 무엇을 제거했나

| blob | 크기 | 문서 |
|---|---|---|
| `35cb705abfef4f7fbee7b2e6b77d68a6c25f272d` | 4.82 MB | 연구보고 CRC 2017-5-6 · 고등학교 수학과 평가기준 개발 연구 |
| `7e1d471e69b2d4135310cd53c4eca98d1b32b5a1` | 5.91 MB | 연구보고 CRC 2016-2-6 · 초·중학교 수학과 평가기준 개발 연구 |

판권장 직접 추출로 확인: 발행처 한국교육과정평가원, ISBN 979-11-5788-529-9 / -347-9,
**"※ 본 자료 내용의 무단 복제를 금함"**. 고시가 아니라 **연구보고서**이므로
`docs/data/licensing_safety.md`의 'NCIC 구분' 후자(해설서·연구보고서 = 영리 차단·C등급)에 해당한다.

**제거하지 않은 것**: `data/ncic/raw/curriculum_math_2022.pdf`는 p1이
`교육부 고시 제2022-33호 [별책 8] 수학과 교육과정` — **고시**라 저작권법 §7 제1호상 보호받지
못하는 저작물이다. 자체 사업계획서 PDF/docx·하네스 zip도 자체 저작물이라 대상이 아니다.

## 2. 실제로 한 일

`main`은 두 blob을 담지 않았다(`git merge-base --is-ancestor 388f7921 origin/main` → false).
보유 ref는 정체된 브랜치 2개와 닫힌 PR #739의 `refs/pull/739/head`뿐이었다. 그래서
**두 브랜치를 삭제**했다 — 히스토리 재작성 0, main 무변경, 협업자 재clone 불요.

```
git push origin --delete claude/human-bottleneck-tasks-6dszy0
git push origin --delete merge/human-bottleneck-6dszy0
```

**삭제 전 소실 0 증명**(이게 본체다 — 증명 없는 삭제는 미병합 고립 5회차가 된다):

- 두 브랜치가 main에 없는 커밋 21건을 담았고 그중 **MISC-01·MISC-03·PB-02 구현이 main 미착지**였다.
- 그러나 그 구현은 **`claude/subject-problems-theory-check-7n9n72`에 그대로 있고, 그 브랜치는
  KICE blob 0건**이다. 기능 마커 5/5 보존(시각화 배선 6=6 · shadow 51→52 · config 플래그 1=1 ·
  유사문항 서빙 7=7 · 코퍼스 글롭 10=10), 핵심 파일 6개는 **blob SHA 바이트 동일**.
- 6dszy0에만 있던 파일 4개는 MISC-04 분이고 **전부 main에 이미 있다**(3개 바이트 동일,
  alembic 1개는 main이 후속판 — PR #821 회수분).

**최종 확인**(완전히 새 clone에서). 아래는 **그대로 재실행 가능한** 형태다 — 초안은
`wm-verify`로 들어가지 않고 SHA도 생략 부호(`35cb705a…`)를 써서, blob이 있어도 항상 0건을 내는
*무조건 통과하는 검증*이었다(PR #1008 리뷰 지적). 법적 증적 명령에서는 치명적이라 교체했다.

```powershell
cd C:\Users\kiki\Desktop\__AI
$Blobs = "^(35cb705abfef4f7fbee7b2e6b77d68a6c25f272d|7e1d471e69b2d4135310cd53c4eca98d1b32b5a1) "
Remove-Item -Recurse -Force .\wm-verify -ErrorAction SilentlyContinue
git clone https://github.com/kiki-s-broom/WhyMath.git wm-verify
$objs = git -C wm-verify rev-list --objects --all
$rc = $LASTEXITCODE
$n = ($objs | Select-String -Pattern $Blobs).Count
Write-Host "rev-list exit=$rc · KICE blob=$n 건   (exit 0 이고 0건이어야 성공)"
```

**성공 기준**: `exit=0` **그리고** `0 건`. 건수만 보면 clone·조회가 실패해도 0건으로 보이므로
종료 상태를 함께 판정한다.

**이 검사의 변별력 근거**: 같은 `$Blobs` 패턴을 삭제 *전* 같은 명령 형태로 돌렸을 때 —

```
refs/heads/main                                  -> blob 0 건
refs/heads/claude/human-bottleneck-tasks-6dszy0  -> blob 2 건
refs/heads/merge/human-bottleneck-6dszy0         -> blob 2 건
```

즉 이 패턴은 blob이 있으면 **실제로 찾아낸다**(2건). 성공·실패 양쪽에서 다른 값을 내므로
0건이라는 결과가 의미를 가진다. 같은 실측이 "main은 깨끗하다"도 함께 증명해 §2의 삭제 전략을
성립시켰다.

**초안 패턴의 반례(실측)**: 삭제된 커밋을 아직 담고 있는 ref(`refs/pull/739/head`)에
두 패턴을 각각 돌린 결과 —

| 패턴 | blob 보유 ref | 정상 ref |
|---|---|---|
| 전체 SHA (현행) | **2건** | 0건 |
| 생략 부호 `35cb705a…` (초안) | **0건** | 0건 |

초안은 blob이 *있는데도* 0건을 냈다. 즉 어떤 저장소에 돌려도 통과하는 검사였고, 그것을 법적
제거 증적으로 쓸 뻔했다.

## 3. 왜 브랜치 재작성은 실패했나 — 재사용 가능한 교훈

처음 런북은 `git filter-repo --refs <두 브랜치> --strip-blobs-with-ids`로 **PDF만 들어내고
커밋 21건은 보존**하는 방식이었다. 실행하니 blob은 사라졌고 파일도 온전했는데(자가검증 1·3축
통과) **2축이 실패**했다:

```
1) blob   : A=0 M=0                    ✔
2) commits: A=726/21  M=729/21         ✘  (기대 21 또는 20)
3) marker : coach True  ci True        ✔
```

원인 — **이 저장소는 커밋이 전부 서명(`gpgsig`, SSH 서명)돼 있다**(표본 200건 중 200건).
`filter-repo`의 엔진인 `git fast-export`는 **서명을 버린다.** 그래서 PDF와 무관한 조상 705건까지
SHA가 바뀌었고, 브랜치가 main에서 통째로 분리됐다:

| | 재작성 전 | 재작성 후 |
|---|---|---|
| A 전체 커밋 | 757 | 757 |
| main과 공유 | 736 | **31** |

main을 `--refs`에 함께 넣으면 공유 이력은 맞겠지만 그건 **main 재작성**이라 불가.
즉 **서명된 저장소에서 "브랜치만 재작성" 경로는 구조적으로 막혀 있다.**

> **일반화**: 서명된 저장소에서 `filter-repo`/`filter-branch`로 *일부 ref만* 재작성하면, 재작성한
> ref가 나머지와 이력을 공유하지 못하게 된다. 히스토리에서 무언가를 지워야 한다면 먼저
> **그 ref를 지울 수 있는지**(내용이 다른 곳에 보존돼 있는지)를 보라. 삭제가 되면 재작성은
> 필요 없고, 재작성이 필요하면 전체 ref를 함께 재작성하는 수밖에 없다(= 사실상 저장소 재출발).

## 4. 자가검증 설계가 실제로 한 일

**2축이 없었으면 그대로 push했을 것이다.** blob 0건(1축)과 파일 보존(3축)만으로는 "브랜치가
main에서 떨어져 나갔다"를 볼 수 없다. 검증 축은 *성공을 확인*하는 게 아니라 *다른 방식의 실패를
각각* 잡아야 한다는 사례다(CLAUDE.md "변별력 없는 검증 스텝 금지").

같은 실행에서 **검증 스텝 자체의 결함도 두 개** 드러났다:

- **커밋 수 기대값을 `21/18`로 못박았던 초안** — `388f7921`이 PDF 2개만 담은 커밋이라 재작성 시
  빈 커밋으로 정리되면 20이 된다. *정상 상태에서 실패하는* 검증이었다. `pre` 또는 `pre-1`로 교체.
- **내용 마커를 한글(`재생성`) grep으로 잡으려던 안** — PowerShell 콘솔 인코딩에 따라 정상
  상태에서도 매치가 어긋난다. **blob SHA 대조**(ASCII만)로 교체 — 변별력도 더 높다.

## 5. 실행 환경에서 드러난 함정

- **`pip install git-filter-repo` 후 `git filter-repo`가 PATH에 없다**(Windows 사용자 설치).
  pip이 출력한 경로를 그대로 세션 PATH에 얹어야 한다:
  `$env:Path = "C:\Users\kiki\AppData\Roaming\Python\Python313\Scripts;" + $env:Path`
- **`git filter-repo --version`이 버전이 아닌 SHA 형태(`a40bce548d2c`)를 출력**하고
  `git_filter_repo.__version__`도 없다. **버전 문자열로 도구 정상 여부를 판정하지 말 것** —
  `--dry-run`(refs 무변경)으로 기능 검증하는 편이 정확하다.

## 6. 남은 한계 (알면서 남김)

`refs/pull/739/head`(닫힌 PR #739)는 서버 측 ref라 **저장소 소유자도 git으로 지울 수 없다.**
다만 **일반 `git clone`은 `refs/pull/*`을 가져오지 않으므로** 통상 배포 경로에서는 제거가
완료됐다(§2 최종 확인). 완전 제거는 GitHub Support 요청(저장소·PR #739·blob SHA 2건 명시)이며
웹 폼 작업이라 이 문서 범위 밖이다. `LIC-07` ⑨에 동일 내용이 기록돼 있다.

## 7. 재유입 방지 가드 (acceptance ④ — 착지)

2026-08-08에 PDF가 들어온 경로를 닫았다. **3중**이다:

| 층 | 무엇 | 막는 것 |
|---|---|---|
| ⓪ | `.gitignore`의 '저작권 위험 원본 문서' 블록 | `git add`로 그냥 스테이징되는 것. 사고 당시 아카이브(`*.zip`)만 있었고 **PDF·hwp·오피스는 규칙이 아예 없었다**(실측) |
| ① | `check_source_document_binaries.py` 확장자 축 | `git add -f`로 뚫고 들어온 원본 |
| ② | 같은 스크립트의 **매직 바이트** 축 | 확장자 위장(`보고서.pdf` → `보고서.txt`) |

가드는 **자기 1차 방어선의 실재도 검사한다**(⓪) — `.gitignore` 규칙이 지워지면 red. 허용 목록은
사유가 붙은 영구 예외이고, 실재하지 않는 항목이 남으면 **죽은 예외**로 red다. 전수 스캔이
성립하지 않으면 통과가 아니라 **exit 2**(측정 실패를 0건 통과로 위장 금지).

**변별력 실증**(정상 초록은 보호의 증거가 아니다 — CLAUDE.md 2026-09-01):
`tests/infra/test_source_document_binary_guard.py` 14건이 위반을 실제로 주입해 red를 요구한다 —
사고 당시 파일명 그대로의 PDF · hwp · docx · zip · 확장자 위장 PDF · 위장 xlsx · 죽은 예외 ·
`.gitignore` 규칙 삭제 · 얇은 인벤토리 · git 아닌 디렉터리. **대칭 축**도 둔다(진짜 텍스트 파일은
통과 — 모든 `.txt`를 잡는 가드가 아니라는 증명).

**배선 실재성**은 `test_source_document_binary_guard_wiring.py`가 동결한다. 특히 이 잡이
`needs: changes`에 종속되면 **PDF 하나만 추가하는 PR에서 skip되고 GitHub는 skipped를 required
check 충족으로 센다** — 가드가 존재하는 바로 그 상황에서 돌지 않게 되므로 별도 계약으로 막았다.

**남은 공백(알면서)**: 확장자를 바꾼 **구형 `.hwp`**(OLE 복합문서)는 매직 축이 보지 않아
통과한다. 또 이 가드는 *원본 파일*을 잡지 *텍스트로 옮겨 적은 본문*은 잡지 못한다 — 그쪽은
policy-guard의 패턴 축과 사람 검수 몫이다.
