# 06. 디자인 시스템 (학생 앱 토큰·테마 정본)

> **성격**: 학생 Flutter 앱(`src/mobile/`)의 **디자인 토큰·테마 정본**. 색·간격·타이포·다크모드·정서 안전·접근성 규약을 한 곳에 모은다.
>
> **정본 경계**: 여기는 *무엇이 정의됐고 어떻게 쓰는가*(what/how)를 기술한다. *왜 그런가*(정서 안전·반게임화의 근거)는 `../architecture/05_interaction.md`·`../../CLAUDE.md`, *코딩 규약*은 `../standards/coding_flutter.md`(디자인 토큰 절), *넓은 계획*(연령대·모드별 테마 스위칭)은 [02 §6](02_student_ui_master_plan.md)에 있다. 충돌 시 코드(`lib/theme/`)가 최종 사실이다.
>
> **착지 이력**: MOB-09(색/테마·다크모드) → MOB-10(간격·타이포 부분) → MOB-11(토큰 이관 완결). 색·간격·타이포 토큰이 앱 전반에 일관 적용됨(매직 색·`fontSize`·바 numeric 간격 리터럴 0).

---

## 1. 파일 지도 (`src/mobile/lib/theme/`)

| 파일 | 내용 |
|---|---|
| `app_theme.dart` | `WhyMathTheme.light`/`dark` — `ThemeData`(색 롤·정서 안전 override·M3) |
| `brand_colors.dart` | `BrandColors` — OAuth 사업자 색(카카오·네이버)·정서 팔레트 **예외** |
| `spacing.dart` | `AppSpacing` — 4pt 리듬 간격 스케일 + 오프리듬 미세값 |
| `test/theme_test.dart` | 정서 안전 회귀 게이트(error 롤 앰버 hue 동결) |

앱 배선: `app.dart`가 `theme: WhyMathTheme.light` + `darkTheme: WhyMathTheme.dark` + `themeMode: ThemeMode.system`.

---

## 2. 색 (Color)

- **정본 = `ColorScheme.fromSeed(seedColor: Colors.indigo)`** — 라이트/다크 각각 `brightness`로 생성. `useMaterial3: true`. 커스텀 롤 값을 손으로 나열하지 않고 seed에서 파생한다(M3 대비·조화 보장).
- **화면은 색을 하드코딩하지 않는다** — `Theme.of(context).colorScheme.<role>`만 참조. 앱이 실제로 쓰는 롤: `primary`·`primaryContainer`/`onPrimaryContainer`·`secondaryContainer`/`onSecondaryContainer`·`surfaceContainer`/`High`/`Highest`·`onSurfaceVariant`.
- **정서 안전 override(핵심)**: M3 `error` 롤(기본 빨강)을 **앰버(주의)로 재정의**한다(`copyWith(error/onError/errorContainer/onErrorContainer=…)`, hue≈40~44°). 오답·오류를 *질책의 빨강*이 아니라 *주의의 앰버*로 — 코드 어디서 `colorScheme.error`를 쓰더라도 빨강이 안 나오게 **토큰에서 강제**한다. `theme_test.dart`가 라이트/다크 error·errorContainer의 hue를 앰버 범위[30,75]로 동결해 회귀를 막는다.
- **브랜드 예외**: `BrandColors.kakao`(`0xFFFEE500`)·`onKakao`·`naver`(`0xFF03C75A`)·`onNaver`는 OAuth 사업자 규정 색이라 정서 팔레트(빨강 금지 등)의 적용 대상이 **아니다**. 정서 신호(오답·주의)에는 절대 쓰지 않는다.

---

## 3. 간격 (Spacing — `AppSpacing`)

`SizedBox` 간격·`EdgeInsets` 패딩(`all`/`symmetric`/`only`/`fromLTRB`)에 **매직 넘버 대신 이 토큰**을 쓴다.

**4pt 리듬 스케일(정본)**

| 토큰 | px | 용도 |
|---|---|---|
| `xs` | 4 | 미세 간격(아이콘-라벨) |
| `sm` | 8 | 기본 간격(가장 빈번) |
| `md` | 12 | 요소 간 간격 |
| `lg` | 16 | 블록·카드 패딩 |
| `xl` | 20 | 섹션 간 간격 |
| `xxl` | 24 | 큰 섹션·화면 패딩 |
| `xxxl` | 32 | 주요 구획 간격 |
| `huge` | 48 | 대형 여백 |

**오프리듬 미세값**(밀집 UI 보존용·4pt 밖): `hairline`=2·`xs6`=6·`sm10`=10·`md14`=14. 기존 조밀 UI(배지·칩·버블 내부)의 값을 *그대로* 보존하기 위한 토큰이다. **새 코드는 리듬 스케일을 우선**하고, 이 값들은 시각 검증이 가능한 시점에 리듬으로 흡수할지 재검토한다(후속 "리듬 정리").

---

## 4. 타이포그래피 (Typography)

- **정본 = M3 기본 `TextTheme` 스케일** — 커스텀 `TextTheme` 오버라이드를 두지 **않는다**(전역 회귀 방지·M3 스케일이 이미 좋은 타입 램프).
- **매직 `fontSize` 금지** — `Theme.of(context).textTheme.<role>`만 쓴다(예: `bodyLarge`≈16·`bodyMedium`≈14·`bodySmall`≈12·`titleMedium`·`labelMedium` 등). 앱 전역에 잔여 `fontSize` 리터럴 0.
- **강조는 색이 아니라 굵기로도 가능** — `CoachEmphasisText`는 색 대신 `FontWeight.w700`으로 강조(색맹 친화·"색만으로 정보 전달 금지" 준수).

---

## 5. 다크 모드

- `MaterialApp`에 `theme`(라이트)+`darkTheme`(다크)+`themeMode: ThemeMode.system` — **시스템 설정을 따라 자동 전환**.
- 라이트 외형은 기존 seed(indigo) 유지라 변화 없음. 다크는 `fromSeed(brightness: dark)`로 파생.
- 화면이 색 롤만 참조하므로 다크 대응은 테마 한 곳에서 처리된다(화면 수정 불요). error=앰버 override는 다크에서도 밝은 앰버로 유지.

---

## 6. 정서 안전 (Emotional Safety — 토큰에서 강제)

`CLAUDE.md`·`coding_flutter.md`의 하드 원칙을 토큰·컴포넌트 레벨에서 구조적으로 지킨다.

- **빨강 금지** — `error` 롤을 앰버로 재정의(§2)·앱 전역 빨강 색 리터럴 0. `theme_test.dart`가 회귀 차단.
- **게이미피케이션 금지** — 랭킹·스트릭·카운트다운·보상 연출 없음(로딩은 은근한 `LinearProgressIndicator`만).
- **부정 표현 금지** — 오답/틀림을 중립 surface 톤 + 은근한 문구(`CoachSignalCard`: "다시 볼 단계가 있어요")로 표현. "틀렸다" 단정·정답값·수정법 미노출(답 미루기·낙인 금지).

---

## 7. 접근성 규약 (Accessibility)

**목표 준수 레벨 = WCAG 2.1 AA**(KWCAG 2.2 AA는 본 프로젝트가 실제로 검사하는 항목 — 텍스트 대비 4.5:1·탭
영역 크기·라벨 — 에서 실질적으로 동등하다고 보고 이 레벨 하나로 정본 선언한다. AAA는 목표하지 않는다).

이 표가 접근성 준수의 *현재 달성 현황 정본*이다(`coding_flutter.md`는 목표 레벨만 선언하고 이 표를 가리킨다 —
"100%" 같은 완료 주장은 하지 않는다). **자동 검증 착지(MOB-13/14, 배율 축 A11Y-01)** — 구조적으로 안전한
단순 화면부터 `meetsGuideline` 위젯 테스트(`test/accessibility_test.dart`)로 회귀를 막는다.

| 항목 | 목표 | 현황 |
|---|---|---|
| 텍스트 대비 | 4.5:1 이상 | 🟡 explore/home/me + 조밀 위젯(`SceneRenderer`·`CoachSignalCard`)을 `textContrastGuideline`로 라이트/다크 검증(MOB-13/14), 배율 1.0×/1.3×/2.0×까지 확대(A11Y-01). chat·ocr *전체 화면 상태*(활성 문제·메시지·인식 후 cue)는 미검증. **예외**: 네이버 로그인 버튼(브랜드 규정 초록+흰색·≈2.3:1)은 사업자색이라 대비 테스트 제외 |
| 탭 영역 | 48dp 이상 | 🟡 M3 기본 컴포넌트 충족 + explore/home/me guideline 검증(배율 1.0×/1.3×/2.0×, A11Y-01). chat 문제 배너 탭에 라벨·button 시맨틱(MOB-13) + 최소 48dp 보장(MOB-14·`maxHeight` clamp로 MOB-02 상한 불침범) |
| Semantics 라벨 | 아이콘 버튼·탭 목적지 라벨 | 🟡 아이콘 버튼 `tooltip`·셸 탭 label·OCR 영역 카드·chat 배너(MOB-13) 라벨 보유. `SceneRenderer`의 시각화 placeholder(`_VisualizationSeed`)도 단일 `Semantics` 라벨 부착(A11Y-01). 전면 감사는 후속 |
| 색만으로 정보 전달 금지 | 굵기·아이콘·문구 병행 | 🟢 `CoachEmphasisText`(굵기)·신호는 아이콘+문구·정오 채색 전무 |
| TTS | `SpeechSpec` 소비(클라 합성) | 🔴 후속 — **"곧"이 아니라 트리거 대기**. 서버 축은 완비(`POST /v1/speech/latex`)이나 클라 합성 의존이 없다(`flutter_tts` Gradle 비호환 실측으로 제거). 발화 조건 = ⓐ 실기기 Gradle 호환을 재검증한 대체 의존 확보 **또는** ⓑ 시각·청각 약자 학생의 파일럿 참여 **또는** ⓒ 교육기관 납품 결정 (`service_operations_gap_review.md` §5-④) |

→ **후속(각 항목은 소유 태스크 또는 발화 트리거를 가진다 — 소유 없는 "후속"은 영구 미상환이 된다)**:
- chat·problem *전체 화면 상태*(활성 문제·메시지) 대비·배율 검증 + **커버리지 드리프트 가드**(새 화면이 게이트 밖으로 조용히 늘지 않게) → **`A11Y-02`** 소유(2026-10-05 OPS-40 회수 등재 — 고립 브랜치 `5t5lmv`의 설계 승계).
- ocr *인식 후 cue* 상태 검증 → `A11Y-02` 범위 밖. 트리거 = OCR 실기기 경로가 파일럿에서 실사용될 때.
- Semantics 라벨 **전면** 감사 → 트리거 대기(현재는 아이콘 버튼·탭·배너·시각화 placeholder만 보유). 전면 감사는 화면 집합이 안정된 뒤가 옳다.
- TTS(`SpeechSpec`) → 위 표 TTS 행의 ⓐⓑⓒ 트리거 참조.

---

## 8. 사용 규칙 (요약)

1. **색은 `colorScheme` 롤**, **간격은 `AppSpacing`**, **타입은 `textTheme` 롤** — raw 리터럴 금지.
2. 오답·주의는 앰버(`colorScheme.error` 계열), 빨강 금지.
3. 브랜드 색(`BrandColors`)은 OAuth 버튼 전용, 정서 신호에 쓰지 않음.
4. 새 간격은 4pt 리듬(`xs`~`huge`) 우선, 오프리듬 토큰은 기존 조밀 UI 보존에만.
5. 커스텀 `TextTheme`·컴포넌트 테마 대폭 오버라이드 지양(전역 회귀 위험).

### 후속 (미구현)

- 오프리듬 값 **리듬 정리**(시각 검증 가능 시점) · **골든 테스트**(`golden_toolkit` 선언만·사용 0) · **접근성 자동 검증**(§7) · **모드/연령대 테마 스위칭**(`ModeConfig.primary_color`·연령 프로파일·[02 §6]) · **공유 컴포넌트 추출**(카드·섹션 헤더 등 반복 패턴).

---

**버전**: 1.0 | **작성**: 2026-07-25 | **정본 코드**: `src/mobile/lib/theme/` · **다음 검토**: 리듬 정리 / 테마 스위칭 착수 시점
