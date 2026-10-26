"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createCmsProposal,
  fetchCmsProposals,
  reviseCmsProposal,
  transitionCmsVersion,
  type CmsProposalRow,
  type CmsResult,
} from "../_lib/adminCmsApi";

import {
  CmsFailureBox,
  CmsNoticeView,
  actionLabel,
  describeCmsFailure,
  statusLabel,
  type CmsNotice,
  type NoteResult,
} from "./CmsCommon";

import styles from "./Cms.module.css";

/**
 * 신규 개념 제안 (P3-26) — 아직 개념 행이 **없는** 후보 개념의 생성·심사.
 *
 * 흐름: 제안(초안) → 제출 → 검토 → 승인 → **발행**. 발행하는 순간 서버(발행 게이트)가 개념 행을 만든다.
 * 제안은 발행 전에는 학생 화면에 보이지 않는 후보일 뿐이다.
 *
 * 경계(CLAUDE.md "표현 ≠ 의미"): 어떤 전이 버튼을 그릴지는 서버가 준 `allowed_actions`가 정한다
 * (기존 판 이력 화면과 같은 전이 함수 `transitionCmsVersion`을 쓴다). 코드·계층 규칙의 판정도 서버가 하며,
 * 화면은 서버가 거부한 사유를 해당 입력칸 아래에 보일 뿐이다. 권한이 없으면 서버가 403으로 막고
 * 화면은 안내 문구를 보인다.
 */

/** 계층 선택지 — 서버 스키마(`ConceptLevel`)의 값 그대로 보낸다. */
const LEVEL_CHOICES = ["단원", "소단원", "세부개념"] as const;

type Loadable<T> = { kind: "loading" } | CmsResult<T>;

interface Props {
  token: string;
  note: NoteResult;
  /** 제안 만들기 폼을 보일지(개념 편집 화면에서만). 목록·전이 버튼은 항상 보인다. */
  showCreate: boolean;
  /** 호출자의 CMS 권한 이름들(`GET /resources`) — 폼 안내에만 쓴다. 차단은 서버가 한다. */
  capabilities: string[];
  /** 제안이 발행돼 개념 행이 생겼을 수 있을 때(부모가 개념 목록을 다시 읽는다). */
  onChanged: () => void;
}

export function CmsProposalPanel({ token, note, showCreate, capabilities, onChanged }: Props) {
  const [proposals, setProposals] = useState<Loadable<CmsProposalRow[]>>({ kind: "loading" });
  const [notice, setNotice] = useState<CmsNotice>(null);
  const [busy, setBusy] = useState(false);
  // 전이 확인 대기: 어느 판의 어느 동작인가
  const [pending, setPending] = useState<{ versionId: string; action: string } | null>(null);
  // 수정 폼을 연 제안의 코드
  const [editing, setEditing] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const result = await fetchCmsProposals(token);
    if (mine !== seq.current) return;
    note(result.kind);
    setProposals(result);
  }, [token, note]);

  useEffect(() => {
    setProposals({ kind: "loading" });
    void load();
  }, [load]);

  async function runAction(row: CmsProposalRow, action: string): Promise<void> {
    if (busy) return;
    setBusy(true);
    // `expected_status`는 사용자가 화면에서 본 상태 그대로 — 낡았는지는 서버가 409로 판정한다.
    const result = await transitionCmsVersion(token, row.summary.version_id, action, row.summary.status);
    setBusy(false);
    setPending(null);
    note(result.kind);
    if (result.kind === "ok") {
      setNotice({
        tone: "info",
        text:
          row.summary.concept_code + ": " + actionLabel(action) + " 처리했습니다 — " +
          statusLabel(row.summary.status) + " → " + statusLabel(result.data.status) +
          (result.data.status === "PUBLISHED" ? ". 발행되어 개념이 만들어졌습니다." : ""),
      });
    } else {
      setNotice({ tone: "failure", failure: result, what: actionLabel(action) });
    }
    // 낙관적 갱신 금지 — 성공·충돌·없음이면 서버에서 다시 읽는다. 발행됐으면 개념 목록도 달라진다.
    if (result.kind === "ok" || result.kind === "conflict" || result.kind === "not-found") {
      await load();
      onChanged();
    }
  }

  return (
    <section className={styles.block} aria-label="신규 개념 제안">
      <h3 className={styles.detailTitle}>신규 개념 제안</h3>
      <p className={styles.hint}>
        제안은 <strong>아직 학생 화면에 보이지 않는 후보</strong>입니다. 제출 → 검토 → 승인을 거쳐{" "}
        <strong>발행해야 개념이 만들어지고</strong>, 그 순간부터 학생 경로가 읽을 수 있습니다.
      </p>

      <CmsNoticeView notice={notice} />

      {showCreate &&
        (capabilities.includes("edit") ? (
          <CreateForm
            token={token}
            note={note}
            onNotice={setNotice}
            onCreated={() => {
              void load();
            }}
          />
        ) : (
          <p className={styles.muted}>이 계정은 편집 권한이 없어 제안을 만들 수 없습니다(조회만 가능).</p>
        ))}

      <h4 className={styles.blockTitle}>열린 제안</h4>
      <ProposalList
        proposals={proposals}
        busy={busy}
        pending={pending}
        editing={editing}
        token={token}
        note={note}
        onAsk={(versionId, action) => setPending({ versionId, action })}
        onCancel={() => setPending(null)}
        onConfirm={(row, action) => void runAction(row, action)}
        onEdit={setEditing}
        onNotice={setNotice}
        onRevised={() => {
          setEditing(null);
          void load();
        }}
        onRetry={() => {
          setProposals({ kind: "loading" });
          void load();
        }}
      />
    </section>
  );
}

// ── 제안 만들기 ──────────────────────────────────────────────────────────

function CreateForm(props: {
  token: string;
  note: NoteResult;
  onNotice: (notice: CmsNotice) => void;
  onCreated: () => void;
}) {
  const [code, setCode] = useState("");
  const [nameKo, setNameKo] = useState("");
  const [level, setLevel] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(): Promise<void> {
    if (busy) return;
    const found: Record<string, string> = {};
    if (code.trim().length === 0) found.code = "개념 코드를 입력하세요.";
    if (nameKo.trim().length === 0) found.name_ko = "한글 이름을 입력하세요.";
    if (level.length === 0) found.level = "계층을 선택하세요.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setBusy(true);
    const trimmedReason = reason.trim();
    const result = await createCmsProposal(
      props.token,
      code.trim(),
      { name_ko: nameKo.trim(), level },
      trimmedReason.length > 0 ? trimmedReason : null,
    );
    setBusy(false);
    props.note(result.kind);
    if (result.kind === "ok") {
      props.onNotice({
        tone: "info",
        text:
          "제안 " + result.data.concept_code + "을(를) 초안으로 만들었습니다. 아직 개념이 아니며, " +
          "아래 열린 제안에서 제출·검토·승인·발행을 거쳐야 개념이 만들어집니다.",
      });
      setCode("");
      setNameKo("");
      setLevel("");
      setReason("");
      props.onCreated();
      return;
    }
    props.onNotice({ tone: "failure", failure: result, what: "신규 개념 제안" });
    // 서버가 가리킨 입력칸 아래에도 사유를 보인다(코드 형식 오류는 `code` 칸).
    if (result.kind === "validation" || result.kind === "conflict") {
      const field = result.problem.field ?? (result.problem.code === "code_taken" ? "code" : null);
      if (field !== null) setErrors({ [field]: result.problem.message });
    }
  }

  return (
    <div className={styles.block}>
      <h4 className={styles.blockTitle}>새 개념 제안하기</h4>

      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor="wm-cms-proposal-code">
          개념 코드 (2~64자, 영문·숫자·한글·점·밑줄·하이픈)
        </label>
        <input
          id="wm-cms-proposal-code"
          className={`${styles.input} ${styles.fieldInput}`}
          type="text"
          maxLength={64}
          value={code}
          disabled={busy}
          aria-invalid={errors.code !== undefined}
          onChange={(event) => setCode(event.target.value)}
        />
        {errors.code !== undefined && (
          <p className={styles.fieldError} role="alert">
            {errors.code}
          </p>
        )}
      </div>

      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor="wm-cms-proposal-name">
          한글 이름
        </label>
        <input
          id="wm-cms-proposal-name"
          className={`${styles.input} ${styles.fieldInput}`}
          type="text"
          maxLength={200}
          value={nameKo}
          disabled={busy}
          aria-invalid={errors.name_ko !== undefined}
          onChange={(event) => setNameKo(event.target.value)}
        />
        {errors.name_ko !== undefined && (
          <p className={styles.fieldError} role="alert">
            {errors.name_ko}
          </p>
        )}
      </div>

      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor="wm-cms-proposal-level">
          계층
        </label>
        <select
          id="wm-cms-proposal-level"
          className={styles.select}
          value={level}
          disabled={busy}
          aria-invalid={errors.level !== undefined}
          onChange={(event) => setLevel(event.target.value)}
        >
          <option value="">선택하세요</option>
          {LEVEL_CHOICES.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
        {errors.level !== undefined && (
          <p className={styles.fieldError} role="alert">
            {errors.level}
          </p>
        )}
      </div>

      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor="wm-cms-proposal-reason">
          제안 사유 (선택, 500자 이내 — 이력에 남습니다)
        </label>
        <input
          id="wm-cms-proposal-reason"
          className={`${styles.input} ${styles.fieldInput}`}
          type="text"
          maxLength={500}
          value={reason}
          disabled={busy}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>

      <div className={styles.actions}>
        <button className={styles.primaryButton} type="button" disabled={busy} onClick={() => void submit()}>
          {busy ? "처리 중…" : "제안 만들기"}
        </button>
      </div>
      <p className={styles.hint}>
        다른 정보(상위 개념·스킬 등)는 제안을 만든 뒤 &quot;내용 고치기&quot;로 더할 수 있습니다.
      </p>
    </div>
  );
}

// ── 열린 제안 목록 ───────────────────────────────────────────────────────

function ProposalList(props: {
  proposals: Loadable<CmsProposalRow[]>;
  busy: boolean;
  pending: { versionId: string; action: string } | null;
  editing: string | null;
  token: string;
  note: NoteResult;
  onAsk: (versionId: string, action: string) => void;
  onCancel: () => void;
  onConfirm: (row: CmsProposalRow, action: string) => void;
  onEdit: (code: string | null) => void;
  onNotice: (notice: CmsNotice) => void;
  onRevised: () => void;
  onRetry: () => void;
}) {
  const { proposals } = props;
  if (proposals.kind === "loading") return <p className={styles.muted}>제안 목록을 불러오는 중…</p>;
  if (proposals.kind !== "ok") {
    return <CmsFailureBox text={describeCmsFailure(proposals, "열린 제안 목록")} onRetry={props.onRetry} />;
  }
  if (proposals.data.length === 0) {
    return <p className={styles.emptyBox}>열린 제안이 없습니다(서버 응답: 0건).</p>;
  }
  return (
    <ul className={styles.proposalList}>
      {proposals.data.map((row) => {
        const { summary } = row;
        const asking = props.pending !== null && props.pending.versionId === summary.version_id;
        const editingThis = props.editing === summary.concept_code;
        return (
          <li key={summary.version_id} className={styles.proposalItem}>
            <p className={styles.label}>
              {summary.concept_code} {row.name_ko}
            </p>
            <p className={styles.hint}>
              계층: {row.level} · 판 v{summary.version_no} · 상태: {statusLabel(summary.status)}
              {summary.change_reason !== null ? " · 사유: " + summary.change_reason : ""}
            </p>

            <div className={styles.actions}>
              {summary.allowed_actions.map((action) => (
                <button
                  key={action}
                  className={styles.actionButton}
                  type="button"
                  disabled={props.busy}
                  aria-pressed={asking && props.pending?.action === action}
                  aria-label={summary.concept_code + " 제안 " + actionLabel(action)}
                  onClick={() => props.onAsk(summary.version_id, action)}
                >
                  {actionLabel(action)}
                </button>
              ))}
              <button
                className={styles.secondaryButton}
                type="button"
                disabled={props.busy}
                aria-pressed={editingThis}
                aria-label={summary.concept_code + " 제안 내용 고치기"}
                onClick={() => props.onEdit(editingThis ? null : summary.concept_code)}
              >
                내용 고치기
              </button>
            </div>
            {summary.allowed_actions.length === 0 && (
              <p className={styles.muted}>이 상태에서 이 계정이 실행할 수 있는 처리가 없습니다.</p>
            )}

            {asking && props.pending !== null && (
              <div
                className={styles.confirm}
                role="group"
                aria-label={actionLabel(props.pending.action) + " 확인"}
              >
                <p className={styles.confirmText}>
                  제안 <strong>{summary.concept_code}</strong>을(를) <strong>{actionLabel(props.pending.action)}</strong>{" "}
                  처리하시겠습니까? 현재 상태({statusLabel(summary.status)}) 기준으로 요청되며, 그사이 다른
                  곳에서 바뀌었으면 서버가 거부합니다.
                  {props.pending.action === "publish" &&
                    " 발행하면 이 코드의 개념이 실제로 만들어지고 되돌리기 어렵습니다."}
                </p>
                <div className={styles.actions}>
                  <button
                    className={styles.primaryButton}
                    type="button"
                    disabled={props.busy}
                    onClick={() => props.pending !== null && props.onConfirm(row, props.pending.action)}
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

            {editingThis && (
              <ReviseForm
                token={props.token}
                note={props.note}
                row={row}
                onNotice={props.onNotice}
                onRevised={props.onRevised}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

// ── 제안 수정(= 새 초안) ─────────────────────────────────────────────────

function ReviseForm(props: {
  token: string;
  note: NoteResult;
  row: CmsProposalRow;
  onNotice: (notice: CmsNotice) => void;
  onRevised: () => void;
}) {
  const { row } = props;
  const [nameKo, setNameKo] = useState(row.name_ko);
  const [level, setLevel] = useState(row.level);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const code = row.summary.concept_code;

  async function submit(): Promise<void> {
    if (busy) return;
    if (nameKo.trim().length === 0) {
      setError("한글 이름을 입력하세요.");
      return;
    }
    setError(null);
    // 바뀐 필드만 보낸다(서버가 직전 판 위에 병합한다).
    const changes: Record<string, unknown> = {};
    if (nameKo.trim() !== row.name_ko) changes.name_ko = nameKo.trim();
    if (level !== row.level) changes.level = level;
    const trimmedReason = reason.trim();

    setBusy(true);
    const result = await reviseCmsProposal(
      props.token,
      code,
      changes,
      trimmedReason.length > 0 ? trimmedReason : null,
    );
    setBusy(false);
    props.note(result.kind);
    if (result.kind === "ok") {
      props.onNotice({
        tone: "info",
        text: "제안 " + code + "의 새 초안 v" + String(result.data.version_no) + "을 만들었습니다.",
      });
      props.onRevised();
      return;
    }
    props.onNotice({ tone: "failure", failure: result, what: "제안 수정" });
    if (result.kind === "validation" && result.problem.field !== null) setError(result.problem.message);
  }

  const nameId = "wm-cms-revise-name-" + code;
  const levelId = "wm-cms-revise-level-" + code;
  const reasonId = "wm-cms-revise-reason-" + code;
  return (
    <div className={styles.confirm} role="group" aria-label={code + " 제안 고치기"}>
      <p className={styles.hint}>고치면 새 초안이 만들어지고, 다시 제출·검토·승인을 거쳐야 합니다.</p>
      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor={nameId}>
          한글 이름
        </label>
        <input
          id={nameId}
          className={`${styles.input} ${styles.fieldInput}`}
          type="text"
          maxLength={200}
          value={nameKo}
          disabled={busy}
          onChange={(event) => setNameKo(event.target.value)}
        />
      </div>
      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor={levelId}>
          계층
        </label>
        <select
          id={levelId}
          className={styles.select}
          value={level}
          disabled={busy}
          onChange={(event) => setLevel(event.target.value)}
        >
          {/* 서버가 준 현재 값이 선택지에 없어도 그대로 보인다(숨기지 않는다). */}
          {!LEVEL_CHOICES.some((choice) => choice === row.level) && <option value={row.level}>{row.level}</option>}
          {LEVEL_CHOICES.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      </div>
      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor={reasonId}>
          고치는 사유 (선택, 500자 이내)
        </label>
        <input
          id={reasonId}
          className={`${styles.input} ${styles.fieldInput}`}
          type="text"
          maxLength={500}
          value={reason}
          disabled={busy}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      {error !== null && (
        <p className={styles.fieldError} role="alert">
          {error}
        </p>
      )}
      <div className={styles.actions}>
        <button className={styles.primaryButton} type="button" disabled={busy} onClick={() => void submit()}>
          {busy ? "처리 중…" : "새 초안으로 저장"}
        </button>
      </div>
    </div>
  );
}
