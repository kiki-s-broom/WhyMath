"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchCmsAudit,
  fetchCmsVersion,
  fetchCmsVersions,
  rollbackCmsConcept,
  transitionCmsVersion,
  type CmsAudit,
  type CmsConceptDetail,
  type CmsVersionDetail,
  type CmsVersionSummary,
  type CmsResult,
} from "../_lib/adminCmsApi";

import {
  CmsFailureBox,
  CmsNoticeView,
  describeCmsFailure,
  formatTime,
  shortId,
  type CmsNotice,
  type NoteResult,
} from "./CmsCommon";
import { AuditView } from "./CmsResourceDetail";

import styles from "./Cms.module.css";

/**
 * 개념의 판(version) 이력·상태 전이·롤백 (P3-12).
 *
 * 원칙(CLAUDE.md "표현 ≠ 의미")
 * ----------------------------
 * ① **전이 규칙이 이 파일에 없다.** 어떤 버튼을 그릴지는 서버가 준 `allowed_actions`(전이표 ∩ 호출자
 *    권한)가 정한다. 라벨 사전은 *표시*일 뿐이고, 사전에 없는 액션도 원문 그대로 버튼이 된다.
 * ② 낡은 화면 판정은 서버가 한다 — 화면이 본 상태(`expected_status`)·발행본(`expected_published_*`)을
 *    그대로 보내고, 그사이 바뀌었으면 409를 받아 최신 값을 다시 읽는다.
 * ③ 낙관적 갱신 금지 — 전이·롤백 뒤에는 목록·상세를 **서버에서 다시 읽어** 그 값만 보인다.
 * ④ 발행·롤백은 학생이 보는 데이터를 바꾸지 않는다(서빙 경로가 이 테이블을 읽지 않는다) — 이 화면의
 *    "발행"은 콘텐츠 버전 대장의 상태다. 이 사실을 화면이 숨기지 않는다.
 */

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "초안",
  IN_REVIEW: "검토 중",
  IN_QA: "QA 중",
  APPROVED: "승인됨",
  PUBLISHED: "발행됨",
  DEPRECATED: "폐기 예정",
  RETIRED: "은퇴",
};

/** 표시 전용 라벨. 모르는 값은 서버 문자열 그대로(숨기지 않는다). */
function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

const ACTION_LABEL: Record<string, string> = {
  submit: "검토 제출",
  request_changes: "보완 요청",
  pass_review: "검토 통과",
  fail_qa: "QA 불합격",
  approve: "승인",
  publish: "발행",
  deprecate: "폐기 예정으로 표시",
  retire: "은퇴",
};

function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action;
}

type Loadable<T> = { kind: "loading" } | CmsResult<T>;

interface Props {
  token: string;
  note: NoteResult;
  detail: CmsConceptDetail;
  /** 호출자의 CMS 권한 이름들(`GET /resources`). 롤백 영역을 보일지에만 쓴다 — 보안 판정은 서버. */
  capabilities: string[];
  /** `deploy`면 롤백 영역을 함께 보인다. 버튼은 어느 쪽이든 서버의 `allowed_actions`만 따른다. */
  emphasis: "history" | "deploy";
  /** 전이·롤백이 성공해 서버 값이 바뀐 뒤(부모가 개념 상세·목록을 다시 읽는다). */
  onChanged: () => void;
}

export function CmsVersionPane({ token, note, detail, capabilities, emphasis, onChanged }: Props) {
  const [versions, setVersions] = useState<Loadable<CmsVersionSummary[]>>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [version, setVersion] = useState<Loadable<CmsVersionDetail> | null>(null);
  const [notice, setNotice] = useState<CmsNotice>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [rollbackAsk, setRollbackAsk] = useState(false);
  const [audit, setAudit] = useState<null | { kind: "loading" } | CmsResult<CmsAudit>>(null);
  const versionsSeq = useRef(0);
  const versionSeq = useRef(0);

  const conceptId = detail.concept_id;

  const loadVersions = useCallback(async () => {
    const mine = ++versionsSeq.current;
    const result = await fetchCmsVersions(token, conceptId);
    if (mine !== versionsSeq.current) return;
    note(result.kind);
    setVersions(result);
  }, [token, note, conceptId]);

  const loadVersion = useCallback(
    async (versionId: string) => {
      const mine = ++versionSeq.current;
      const result = await fetchCmsVersion(token, versionId);
      if (mine !== versionSeq.current) return;
      note(result.kind);
      setVersion(result);
    },
    [token, note],
  );

  useEffect(() => {
    setVersions({ kind: "loading" });
    void loadVersions();
  }, [loadVersions]);

  useEffect(() => {
    setPending(null);
    setAudit(null);
    if (selectedId === null) {
      versionSeq.current += 1;
      setVersion(null);
      return;
    }
    setVersion({ kind: "loading" });
    void loadVersion(selectedId);
  }, [selectedId, loadVersion]);

  async function runAction(summary: CmsVersionSummary, action: string): Promise<void> {
    setBusy(true);
    // `expected_status`는 사용자가 화면에서 본 상태 그대로다.
    const result = await transitionCmsVersion(token, summary.version_id, action, summary.status);
    setBusy(false);
    setPending(null);
    note(result.kind);
    if (result.kind === "ok") {
      setNotice({
        tone: "info",
        text:
          actionLabel(action) + " 처리했습니다 — v" + String(result.data.version_no) + ": " +
          statusLabel(summary.status) + " → " + statusLabel(result.data.status),
      });
    } else {
      setNotice({ tone: "failure", failure: result, what: actionLabel(action) });
    }
    // 표시값은 항상 서버 값 — 성공·충돌·없음이면 낙관적 갱신 없이 다시 읽는다.
    if (result.kind === "ok" || result.kind === "conflict" || result.kind === "not-found") {
      await Promise.all([loadVersions(), loadVersion(summary.version_id)]);
      setAudit(null);
      onChanged();
    }
  }

  async function runRollback(): Promise<void> {
    if (detail.published_version_id === null) return;
    setBusy(true);
    const result = await rollbackCmsConcept(token, conceptId, detail.published_version_id);
    setBusy(false);
    setRollbackAsk(false);
    note(result.kind);
    if (result.kind === "ok") {
      setNotice({
        tone: "info",
        text:
          "롤백했습니다 — 내려간 판 " + shortId(result.data.rolled_back_version_id) +
          " → 복구된 판 " + shortId(result.data.restored_version_id),
      });
    } else {
      setNotice({ tone: "failure", failure: result, what: "롤백" });
    }
    if (result.kind === "ok" || result.kind === "conflict" || result.kind === "not-found") {
      await loadVersions();
      if (selectedId !== null) await loadVersion(selectedId);
      setAudit(null);
      onChanged();
    }
  }

  async function showAudit(versionId: string): Promise<void> {
    setAudit({ kind: "loading" });
    const result = await fetchCmsAudit(token, "concept_version", versionId);
    note(result.kind);
    setAudit(result);
  }

  const canRollback =
    emphasis === "deploy" && capabilities.includes("publish") && detail.published_version_id !== null;

  return (
    <div>
      <p className={styles.subtitle}>
        현재 발행본: {detail.published_version_id === null ? "없음" : shortId(detail.published_version_id)}
        {" · "}최신 판 번호: {detail.latest_version_no === null ? "없음" : "v" + String(detail.latest_version_no)}
      </p>
      <p className={styles.hint}>
        이 화면의 발행·롤백은 콘텐츠 버전 대장의 상태 변경입니다. 학생에게 서빙되는 데이터는 이 대장을
        읽지 않으므로 여기서 바꿔도 학생 화면이 달라지지 않습니다.
      </p>

      {emphasis === "deploy" && !capabilities.includes("publish") && (
        <p className={styles.blockedBox} role="note">
          이 계정은 발행 권한이 없어 이력만 볼 수 있습니다. 발행·폐기·롤백은 권한이 있는 계정에게만
          서버가 허용합니다(이 문구는 안내일 뿐 차단은 서버가 합니다).
        </p>
      )}

      <CmsNoticeView notice={notice} />

      <VersionTable
        versions={versions}
        selectedId={selectedId}
        publishedId={detail.published_version_id}
        onSelect={(id) => {
          setNotice(null);
          setSelectedId(id);
        }}
        onRetry={() => {
          setVersions({ kind: "loading" });
          void loadVersions();
        }}
      />

      {canRollback && (
        <section className={styles.block} aria-label="롤백">
          <h4 className={styles.blockTitle}>롤백</h4>
          <button
            className={styles.actionButton}
            type="button"
            disabled={busy}
            aria-pressed={rollbackAsk}
            onClick={() => setRollbackAsk(true)}
          >
            직전 발행본으로 롤백
          </button>
          {rollbackAsk && (
            <div className={styles.confirm} role="group" aria-label="롤백 확인">
              <p className={styles.confirmText}>
                현재 발행본({shortId(detail.published_version_id ?? "")})을 내리고 직전 발행본으로
                복구합니다. 화면이 본 발행본 기준으로 요청되며, 그사이 다른 곳에서 바뀌었으면 서버가
                거부합니다.
              </p>
              <div className={styles.actions}>
                <button
                  className={styles.primaryButton}
                  type="button"
                  disabled={busy}
                  onClick={() => void runRollback()}
                >
                  {busy ? "처리 중…" : "확인"}
                </button>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  disabled={busy}
                  onClick={() => setRollbackAsk(false)}
                >
                  취소
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {version !== null && (
        <VersionDetailView
          state={version}
          busy={busy}
          pending={pending}
          audit={audit}
          onAsk={(action) => setPending(action)}
          onCancel={() => setPending(null)}
          onConfirm={(summary, action) => void runAction(summary, action)}
          onAudit={(id) => void showAudit(id)}
          onRetry={() => selectedId !== null && void loadVersion(selectedId)}
        />
      )}
    </div>
  );
}

function VersionTable(props: {
  versions: Loadable<CmsVersionSummary[]>;
  selectedId: string | null;
  publishedId: string | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
}) {
  const { versions } = props;
  if (versions.kind === "loading") return <p className={styles.muted}>판 목록을 불러오는 중…</p>;
  if (versions.kind !== "ok") {
    return <CmsFailureBox text={describeCmsFailure(versions, "판 목록")} onRetry={props.onRetry} />;
  }
  if (versions.data.length === 0) {
    // 서버가 200으로 "0건"이라고 답한 경우만 여기 온다 — 실패와 문구·모양을 다르게 한다.
    return (
      <p className={styles.emptyBox}>
        아직 만들어진 판이 없습니다(서버 응답: 0건). 개념 편집 화면에서 초안을 만들면 여기에 쌓입니다.
      </p>
    );
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption className={styles.srOnly}>판 목록 — 최신 판부터</caption>
        <thead>
          <tr>
            <th scope="col">판</th>
            <th scope="col">상태</th>
            <th scope="col">사유</th>
            <th scope="col">만든 시각</th>
            <th scope="col">발행 시각</th>
          </tr>
        </thead>
        <tbody>
          {versions.data.map((item) => {
            const selected = item.version_id === props.selectedId;
            return (
              <tr key={item.version_id} className={selected ? styles.rowSelected : undefined}>
                <th scope="row" className={styles.idCell}>
                  <button
                    className={styles.rowButton}
                    type="button"
                    aria-current={selected ? "true" : undefined}
                    title={item.version_id}
                    onClick={() => props.onSelect(item.version_id)}
                  >
                    v{item.version_no}
                    <span className={styles.srOnly}> 판 {item.version_id} 상세 열기</span>
                  </button>
                </th>
                <td>
                  {statusLabel(item.status)}
                  {item.version_id === props.publishedId ? " (현재 발행본)" : ""}
                </td>
                <td>{item.change_reason ?? "-"}</td>
                <td>{formatTime(item.created_at)}</td>
                <td>{formatTime(item.published_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function VersionDetailView(props: {
  state: Loadable<CmsVersionDetail>;
  busy: boolean;
  pending: string | null;
  audit: null | { kind: "loading" } | CmsResult<CmsAudit>;
  onAsk: (action: string) => void;
  onCancel: () => void;
  onConfirm: (summary: CmsVersionSummary, action: string) => void;
  onAudit: (versionId: string) => void;
  onRetry: () => void;
}) {
  const { state } = props;
  if (state.kind === "loading") return <p className={styles.muted}>판 상세를 불러오는 중…</p>;
  if (state.kind !== "ok") {
    return <CmsFailureBox text={describeCmsFailure(state, "판 상세")} onRetry={props.onRetry} />;
  }
  const { summary, payload, gate_records: gates } = state.data;
  return (
    <article className={styles.detail} aria-labelledby="wm-cms-version-title">
      <h3 id="wm-cms-version-title" className={styles.detailTitle} tabIndex={-1}>
        판 v{summary.version_no} 상세
      </h3>
      <dl className={styles.meta}>
        <dt>판 ID</dt>
        <dd className={styles.mono}>{summary.version_id}</dd>
        <dt>상태</dt>
        <dd>{statusLabel(summary.status)}</dd>
        <dt>작성자</dt>
        <dd className={styles.mono}>{summary.created_by ?? "-"}</dd>
        <dt>검토자</dt>
        <dd className={styles.mono}>{summary.reviewed_by ?? "-"}</dd>
        <dt>승인자</dt>
        <dd className={styles.mono}>{summary.approved_by ?? "-"}</dd>
        <dt>변경 사유</dt>
        <dd>{summary.change_reason ?? "-"}</dd>
        <dt>내용 해시</dt>
        <dd className={styles.mono}>{summary.content_hash ?? "-"}</dd>
      </dl>

      <section className={styles.block} aria-label="상태 전이">
        <h4 className={styles.blockTitle}>상태 전이</h4>
        {summary.allowed_actions.length === 0 ? (
          <p className={styles.muted}>이 상태에서 이 계정이 실행할 수 있는 처리가 없습니다.</p>
        ) : (
          <div className={styles.actions}>
            {summary.allowed_actions.map((action) => (
              <button
                key={action}
                className={styles.actionButton}
                type="button"
                disabled={props.busy}
                aria-pressed={props.pending === action}
                onClick={() => props.onAsk(action)}
              >
                {actionLabel(action)}
              </button>
            ))}
          </div>
        )}
        {props.pending !== null && (
          <div className={styles.confirm} role="group" aria-label={actionLabel(props.pending) + " 확인"}>
            <p className={styles.confirmText}>
              이 판을 <strong>{actionLabel(props.pending)}</strong> 처리하시겠습니까? 현재 상태(
              {statusLabel(summary.status)}) 기준으로 요청되며, 그사이 다른 곳에서 바뀌었으면 서버가
              거부합니다.
            </p>
            <div className={styles.actions}>
              <button
                className={styles.primaryButton}
                type="button"
                disabled={props.busy}
                onClick={() => props.pending !== null && props.onConfirm(summary, props.pending)}
              >
                {props.busy ? "처리 중…" : "확인"}
              </button>
              <button
                className={styles.secondaryButton}
                type="button"
                disabled={props.busy}
                onClick={props.onCancel}
              >
                취소
              </button>
            </div>
          </div>
        )}
      </section>

      <section className={styles.block} aria-label="게이트 통과 기록">
        <h4 className={styles.blockTitle}>게이트 통과 기록</h4>
        {gates.length === 0 ? (
          <p className={styles.muted}>(없음)</p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <caption className={styles.srOnly}>게이트 통과 기록</caption>
              <thead>
                <tr>
                  <th scope="col">게이트</th>
                  <th scope="col">전이</th>
                  <th scope="col">판정자</th>
                  <th scope="col">시각</th>
                  <th scope="col">점검 항목</th>
                </tr>
              </thead>
              <tbody>
                {gates.map((rec, index) => (
                  <tr key={index}>
                    <td>{rec.gate}</td>
                    <td>{rec.action}</td>
                    <td className={styles.mono}>{shortId(rec.judged_by)}</td>
                    <td>{formatTime(rec.judged_at)}</td>
                    <td>{rec.checks.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.block} aria-label="판 내용">
        <h4 className={styles.blockTitle}>판 내용(payload)</h4>
        <pre className={styles.json}>{JSON.stringify(payload, null, 2)}</pre>
      </section>

      <section className={styles.block} aria-label="변경이력">
        <h4 className={styles.blockTitle}>변경이력</h4>
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={props.audit !== null && props.audit.kind === "loading"}
          onClick={() => props.onAudit(summary.version_id)}
        >
          변경이력 보기
        </button>
        <AuditView audit={props.audit} />
      </section>
    </article>
  );
}
