# WhyMath 별도 웹 (webapp) — 공개 랜딩 + 운영 백오피스

> Next.js 15 App Router · React 19 · **정적 export**(`output: "export"` → `out/`)
> **단일 앱 · 2 빌드 타깃** — 공개 랜딩과 내부망 백오피스가 한 코드베이스를 쓰되 산출물은 갈린다.
> 정본 설계: [`docs/architecture/web_strategy.md`](../../../docs/architecture/web_strategy.md) ·
> [`docs/design/ui/04_admin_console_architecture.md`](../../../docs/design/ui/04_admin_console_architecture.md)

---

## 이 앱이 무엇이고 무엇이 아닌가

CLAUDE.md 슬라이스 89의 **③ "별도 웹"** 좌석이다. 학생 *학습 경험*은 Flutter 단일이고,
여기는 **유입·소개 표면**이다(web_strategy §1).

| 지금 있는 것 | 이후 들어올 것 | 여기에 절대 없는 것 |
|---|---|---|
| `app/(public)/` 공개 랜딩 1페이지 | 모듈 화면들 (ADMIN-07 검수 큐부터) | 학생 학습 기능 |
| `app/admin/` 운영 백오피스 셸 (ADMIN-06·내부망 한정) | 교사 웹 (Phase 3+·재평가 후) | 수학 판정·채점·오개념 진단 로직 |
| `robots.txt` · `sitemap.xml` | | 백오피스의 권한 판정·집계 (전부 BFF가 한다) |

`src/web/graphing-calculator/`(슬89 ④ 국소 비상구·Vite SPA)와는 **별개 앱**이다. 그쪽은
불가침이며 이 앱과 코드를 공유하지 않는다.

---

## 빌드 타깃이 둘인 이유 — 공개 산출물에 admin 0

`web_strategy` §2의 배포 요건이다: 코드는 공유하되 **공개 산출물에 admin 번들이 섞이면 안
된다**. 분리 수단은 Next의 `pageExtensions`다 — 라우트 파일(`page`·`layout`·`robots` …)을
파일명 확장자로 식별한다는 성질을 그대로 쓴다.

| 타깃 | 명령 | `pageExtensions` | 산출 라우트 |
|---|---|---|---|
| 공개(기본) | `npm run build` | `["tsx","ts"]` | `/` · `/robots.txt` · `/sitemap.xml` |
| 백오피스 | `npm run build:admin` | `["admin.tsx","admin.ts"]` | `/admin` |

그래서 **`app/admin/` 아래 라우트 파일은 전부 `.admin.tsx` 접미를 쓴다**(`page.admin.tsx`·
`layout.admin.tsx`). 접미가 하나라도 떨어지면 그 파일은 공개 빌드의 라우트가 된다 —
2026-09-22 주입 실측: 접미를 떼자 공개 빌드가 `out/admin/`을 만들었고 **그때도 `next build`는
exit 0이었다**. 빌드 성공은 판정자가 아니므로 CI가 *산출물*을 검사한다.

환경변수 `WHYMATH_WEB_TARGET`을 안 주면 **공개 빌드**로 수렴한다 — 실수의 방향이 안전한 쪽이다.

## 경계 — 기계로 동결된 것

`tests/infra/test_webapp_landing_governance.py`(랜딩)와
`tests/infra/test_webapp_admin_shell_governance.py`(백오피스 셸)가 CI(`infra-contracts` 잡)에서
상시 검사한다. **산출물** 축은 파일을 읽어서는 볼 수 없으므로 `webapp` 잡의 검사 스텝이 맡는다.

1. **수학 판정 0** — 정오 판정·채점·동치 판정의 단일 권위는 백엔드 L3(SymPy)다. 랜딩과
   백오피스 **둘 다**에 적용된다(04 §2 원칙1 — 표현≠의미는 백오피스도 예외가 아니다).
   graphing-calculator 쪽 동형 게이트는
   `src/web/graphing-calculator/test/no_math_judgement_governance.test.js`다.
2. **랜딩의 백엔드 호출 0** — v1 랜딩은 네트워크 호출을 하지 않는다. 베타 신청은 **외부 폼
   링크**만(web_strategy §3.2). 백오피스는 반대로 BFF를 부르는 것이 설계이므로 이 축의
   범위는 공개 소스로 한정된다.
3. **공개 빌드에 admin 코드 0** — 누출 경로가 둘이고 **서로 다른 검사가 잡는다**:
   ⓐ 접미 규약이 깨짐 → 공개 `out/`에 `/admin` 경로가 생긴다(경로 검사)
   ⓑ 공개 *클라이언트* 소스가 `app/admin/`을 import → 경로는 안 생기고 번들에만 실린다
   (**번들 표식 검사만** 잡는다 — 실측 확인). 소스 축은 랜딩 거버넌스 계약 ④가 본다.
4. **하드코딩 nav 0** — 좌측 내비의 항목·순서·라벨이 프런트에 없다. 백엔드 레지스트리에서
   파싱한 섹션 키·모듈 id·라벨·라우트가 admin 소스에 리터럴로 나타나면 RED (04 §2 원칙7).
5. **BFF 경유 · 메뉴 1회 호출** — admin 소스의 API 경로는 전부 `/v1/admin/`이고 `fetch(`는
   정확히 1곳이다(04 §3 — 코어 직접 호출 금지).
6. **토큰을 탭 밖으로 흘리지 않는다** — 탭을 넘어 남는 저장소·쿠키·URL 파라미터 0건.

추가로 **카피 가드**(효과 단정 금지)를 보조 탐지기로 둔다 — 아래 §법적 게이트 참조.

---

## 개발

```bash
cd src/web/webapp
npm ci            # lockfile 고정 설치 (CI와 동일)
npm run dev         # http://localhost:3000  (랜딩 / · 백오피스 /admin 둘 다 뜬다)
npm run lint        # eslint (next/core-web-vitals + next/typescript)
npm run build       # 공개 타깃 정적 export → out/
npm run build:admin # 백오피스 타깃 정적 export → out/  (공개 산출물과 같은 자리를 쓴다)
npm run typecheck   # tsc --noEmit — **두 타깃 소스를 모두** 덮는다
```

`npm run typecheck`가 별도 스텝인 이유: `next build`는 **그 타깃의 빌드 그래프에 있는 파일만**
타입 검사한다. 공개 빌드는 `app/admin/**`를 라우트로 안 잡으므로 백오피스 소스가 한 줄도
검사되지 않는다. `tsc`는 tsconfig include 전체를 보므로 그 사각을 덮는다.

두 빌드가 **같은 `out/`을 쓴다**(Next는 export 디렉터리를 바꿀 수 없다). 둘 다 만들려면
사이에 `out/`을 옮기거나 지운다 — CI가 그렇게 한다.

`out/`은 서버 런타임이 필요 없는 완전 정적 산출물이다. `node_modules/`·`.next/`·`out/`은
커밋하지 않는다(`.gitignore`) — CI가 매번 `npm ci`로 재현한다.

## 의존성 메모 — `overrides`로 postcss를 올려 둔 이유

`next@15.5.25`는 `postcss`를 **정확히 `8.4.31`로 핀**하는데, 그 버전은 권고 4건(`<=8.5.22`)에
걸린다. `npm audit fix`가 제시하는 유일한 경로는 **Next 16**이고, 그건 CLAUDE.md 스택 표
("React 19 + Next.js 15")를 바꾸는 일이라 MEMORY 결정 로그가 선결이다. 그래서 스택은 15에
두고 `package.json`의 `overrides`로 postcss만 `^8.5.28`로 올린다.

실측(2026-09-22): override 후 `npm audit` **0건**, `npm run lint`·`npm run build` 통과,
CSS 모듈 해시·`globals.css` 번들 포함 정상. 이 override와 Next 15 핀은 둘 다 *의도*이므로
`tests/infra/test_webapp_landing_governance.py` 계약 ⑦-b가 조용한 소실을 막는다 —
Next 16으로 올릴 때 그 테스트가 RED로 사람을 세운다.

---

## 환경변수 (전부 선택 — 미설정이 정상 기본값)

| 변수 | 용도 | 미설정 시 |
|---|---|---|
| `NEXT_PUBLIC_SITE_URL` | 배포 도메인 — `sitemap.xml`·OG의 절대 URL 기준 | `http://localhost:3000` (도메인 확정은 WEB-02·Kiki) |
| `NEXT_PUBLIC_BETA_FORM_URL` | 베타 신청 외부 폼 링크 | CTA가 링크 대신 **"준비 중"**으로 렌더 — 죽은 링크를 내보내지 않는다 |
| `NEXT_PUBLIC_WHYMATH_API_BASE_URL` | **백오피스 전용** — BFF 주소(내부망 API) | 콘솔이 "백엔드 주소가 이 빌드에 없습니다"를 표시하고 **아무 데도 요청하지 않는다**(상대 경로 폴백 금지 — 설정 누락이 기능 부재로 위장되지 않게) |
| `WHYMATH_WEB_TARGET` | 빌드 타깃 선택(`admin`만 의미 있음) | 공개 빌드 — `npm run build:admin`이 대신 넣어 준다 |

값이 확정되지 않은 자리에 그럴듯한 가짜 값을 박지 않는다. 미확정은 미확정으로 보여야
"누가 확정해야 하는가"가 드러난다.

---

## 백오피스 셸 운영 메모 (ADMIN-06)

- **내부망 한정** (04 §5) — 공개 인터넷에 올리지 않는다. 이 저장소에는 admin 산출물을 공개
  호스팅하는 설정이 없고, 그 부재를 거버넌스 테스트가 검사 범위를 명시한 채 확인한다.
  `robots: noindex`는 **2차 방어**일 뿐 배포 경계의 대체가 아니다.
- **CORS** — 브라우저가 API를 처음 부르는 지점이 여기다. 백엔드는 deny-by-default이므로
  (`WHYMATH_CORS_ALLOWED_ORIGINS` 기본 빈 값) 콘솔 origin을 명시해야 열린다. 안 열리면
  콘솔이 "백엔드에 닿지 못했습니다"와 함께 그 변수 이름을 말한다 — 브라우저는 차단된 응답을
  JS에 넘기지 않아 서버 로그에는 200만 찍히기 때문이다.
- **로그인** — 실 신원(카카오·네이버 OAuth)으로 발급된 액세스 토큰을 붙여 넣는다. 셸은
  OAuth 왕복을 다시 구현하지 않는다(인증 경로를 둘로 만들지 않는다). 토큰은 **그 탭에서만**
  살아 있다. **데모 계정은 서버가 403으로 막는다** — 클라는 토큰만으로 데모를 식별할 수
  없으므로(JWT에 발급 출처 표식이 없다) 흉내 검사를 넣지 않고 서버 판정을 그대로 보여 준다.
- **좌측 내비** — `GET /v1/admin/menu` 1회 호출로 전부 파생된다. 모듈을 추가하려면 백엔드
  `api/admin_module_registry.py`에 엔트리 하나만 넣는다. 프런트는 고칠 것이 없다.
- **지금 눌리는 항목이 없는 것은 정상이다** — 레지스트리 `status`가 `live`인 모듈이 0건이기
  때문이다(화면이 아직 없다). 존재를 숨기지 않고 비활성으로 보여 준다. ADMIN-07이 검수 큐
  화면을 올리며 그 엔트리를 `live`로 바꾸면 프런트 수정 없이 링크가 살아난다.

---

## 공개 전 선결 — 변호사 검토 게이트 (기계 대체 금지)

배포는 **WEB-02**가 소유하고, 그 선결이 게이트 `G-web01-landing-legal-review`다
(`python3 scripts/harness/backlog.py gates list`). 검토 항목 3종(web_strategy §3.4):

- **광고·마케팅 규제** — RCT 검증 전 "성적이 오른다" 류 효과 단정 금지·비교 광고 자문
- **웹접근성(KWCAG)** — 지능정보화기본법 §46의 적용 범위가 웹 개설로 실제 변동(법률 판단)
- **개인정보** — 외부 폼 채택 시 **처리위탁 고지**·수집 최소화·처리방침 문구

코드 쪽 카피 가드(금지 문구 스캔)는 위 거버넌스 테스트에 있으나 **보조 탐지기**다. 문자열
열거는 표현을 바꾸면 빠져나가므로, 효과 단정 여부의 최종 판정은 사람(변호사)이 한다.
CLAUDE.md "법령 유래 절차의 기계 대체 금지" 그대로다.
