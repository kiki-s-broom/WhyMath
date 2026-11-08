| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| `whymath_backend.db.session.get_engine` (+ `config.get_settings`의 `db_disable_pool=True` 사본으로 NullPool) | 없음 | 연결 URL을 옛 Settings(`WHYMATH_DATABASE_URL`)에서 그대로 읽기 위해. 기동은 정상이라 지시서 "막히면"(직접 `create_async_engine`) 조건에 해당하지 않음. 단 `db/__init__.py`가 ORM 모델 전체를 import해 옛 모듈 102개가 함께 로드된다(실측). NullPool은 `with` 없는 TestClient가 요청마다 새 이벤트 루프를 만들기 때문 | S4 |
| `whymath_backend.l3.providers.factory.build_cloud_provider` + `l3.router.Router.route`(결정 1개) | 지시서의 대체안 "tutor.py에 직접 HTTP 50줄"은 쓰지 않음 | 팩토리 단독 import가 옛 모듈 40개로 지시서 "하지 말 것"의 20개 기준을 넘지만, 공통 규칙 8(팩토리 경유만·직접 호출 금지)이 작업 지시보다 우선한다. `generate`가 `RoutingDecision`을 요구해 라우터 경유로 받았고, 그래서 데이터 반출 게이트가 적용된다(실측 결정 cloud_mid · EXPORT_ALLOWED) | S4 |
