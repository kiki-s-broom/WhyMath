"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import {
  fetchCmsAudit,
  fetchCmsDetail,
  patchCmsItem,
  reviewCmsItem,
  type CmsAudit,
  type CmsDetail,
  type CmsFieldMeta,
  type CmsResourceMeta,
  type CmsResult,
} from "../_lib/adminCmsApi";

import {
  CmsFailureBox,
  CmsNoticeView,
  cellText,
  describeCmsFailure,
  formatTime,
  shortId,
  type CmsNotice,
  type NoteResult,
} from "./CmsCommon";

import styles from "./Cms.module.css";

/**
 * 개념 외 리소스 1건의 상세·수정·검수·변경이력 (P3-12).
 *
 * 원칙(CLAUDE.md "표현 ≠ 의미")
 * ----------------------------
 * ① 편집 가능한 필드는 서버가 준 `detail.fields`뿐이다 — 상태·발행 컬럼은 서버가 애초에 내려주지 않고
 *    보내도 거부한다. 화면이 허용 목록을 따로 들고 있지 않다.
 * ② 길이·범위·허용 값의 판정은 서버(422)가 한다. 여기서는 숫자 형식(NaN)만 거른다.
 * ③ 낙관적 갱신 금지 — 저장·검수 뒤 표시값은 **서버가 돌려준 값**이다.
 * ④ 승인된 문항처럼 편집이 막힌 경우 서버의 사유(`edit_blocked_reason`)를 그대로 보인다.
 */

type FormState = Record<string, string>;

/** 서버 값 → 입력창 문자열. null은 빈 입력으로 둔다. */
function initialText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return String(value);
}

function buildForm(detail: CmsDetail): FormState {
  const form: FormState = {};
  for (const field of detail.fields) form[field.name] = initialText(detail.values[field.name]);
  return form;
}

type Converted = { ok: true; value: unknown } | { ok: false; error: string };

/**
 * 입력 문자열 → 서버로 보낼 값. **숫자 형식 오류만** 여기서 거른다(NaN은 JSON에서 null이 되어
 * 사용자가 쓴 값과 다른 요청이 나가므로). 길이·범위·필수 여부는 서버가 판정한다.
 */
function toRequestValue(field: CmsFieldMeta, text: string): Converted {
  if (field.kind === "int" || field.kind === "float") {
    const trimmed = text.trim();
    if (trimmed.length === 0) return { ok: true, value: null };
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) return { ok: false, error: "숫자를 입력하세요." };
    if (field.kind === "int" && !Number.isInteger(parsed)) {
      return { ok: false, error: "정수를 입력하세요." };
    }
    return { ok: true, value: parsed };
  }
  if (field.kind === "date") {
    const trimmed = text.trim();
    return { ok: true, value: trimmed.length === 0 ? null : trimmed };
  }
  return { ok: true, value: text };
}

function isLong(text: string): boolean {
  return text.length > 80 || text.includes("\n");
}

function FieldEditor(props: {
  field: CmsFieldMeta;
  id: string;
  value: string;
  error: string | undefined;
  disabled: boolean;
  onChange: (next: string) => void;
}) {
  const { field, id, value, error, disabled, onChange } = props;
  const hintParts: string[] = [];
  if (field.max_length !== null) hintParts.push("최대 " + String(field.max_length) + "자");
  if (field.nullable) hintParts.push("비워 두면 값 없음");
  return (
    <div className={styles.fieldRow}>
      <label className={styles.label} htmlFor={id}>
        {field.label_ko}
      </label>
      {field.kind === "longtext" ? (
        <textarea
          id={id}
          className={styles.textarea}
          rows={5}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : field.kind === "choice" ? (
        <select
          id={id}
          className={`${styles.select} ${styles.fieldInput}`}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        >
          {field.nullable && <option value="">(값 없음)</option>}
          {(field.choices ?? []).map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          className={`${styles.input} ${styles.fieldInput}`}
          type={field.kind === "date" ? "date" : "text"}
          inputMode={field.kind === "int" || field.kind === "float" ? "decimal" : undefined}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {hintParts.length > 0 && <p className={styles.hint}>{hintParts.join(" · ")}</p>}
      {error !== undefined && (
        <p className={styles.fieldError} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

interface Props {
  token: string;
  note: NoteResult;
  meta: CmsResourceMeta;
  pk: string;
  /** 저장·검수가 성공해 서버 값이 바뀌었을 때(목록 갱신용). */
  onChanged: () => void;
}

export function CmsResourceDetail({ token, note, meta, pk, onChanged }: Props) {
  const [state, setState] = useState<{ kind: "loading" } | CmsResult<CmsDetail>>({ kind: "loading" });
  const [form, setForm] = useState<FormState>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<CmsNotice>(null);
  const [busy, setBusy] = useState(false);
  const [audit, setAudit] = useState<null | { kind: "loading" } | CmsResult<CmsAudit>>(null);
  // 늦게 도착한 낡은 응답이 최신 화면을 덮지 않게 하는 요청 번호
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const result = await fetchCmsDetail(token, meta.key, pk);
    if (mine !== seq.current) return;
    note(result.kind);
    setState(result);
    if (result.kind === "ok") {
      setForm(buildForm(result.data));
      setFieldErrors({});
    }
  }, [token, note, meta.key, pk]);

  useEffect(() => {
    setState({ kind: "loading" });
    setAudit(null);
    setNotice(null);
    void load();
  }, [load]);

  async function save(detail: CmsDetail): Promise<void> {
    const changes: Record<string, unknown> = {};
    const errors: Record<string, string> = {};
    for (const field of detail.fields) {
      const text = form[field.name] ?? "";
      if (text === initialText(detail.values[field.name])) continue;
      const converted = toRequestValue(field, text);
      if (converted.ok) changes[field.name] = converted.value;
      else errors[field.name] = converted.error;
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;
    if (Object.keys(changes).length === 0) {
      setNotice({ tone: "info", text: "바뀐 값이 없어 저장하지 않았습니다." });
      return;
    }
    setBusy(true);
    const result = await patchCmsItem(token, meta.key, pk, changes);
    setBusy(false);
    note(result.kind);
    if (result.kind === "ok") {
      // 표시값은 항상 서버가 돌려준 값이다.
      setState({ kind: "ok", data: result.data.detail });
      setForm(buildForm(result.data.detail));
      setFieldErrors({});
      const reset =
        result.data.server_reset.length > 0
          ? " · 서버가 검수 표지를 안전한 쪽으로 되돌렸습니다: " + result.data.server_reset.join(", ")
          : "";
      setNotice({
        tone: "info",
        text:
          result.data.changed.length > 0
            ? "저장했습니다 — 바뀐 필드: " + result.data.changed.join(", ") + reset
            : "서버가 확인한 결과 바뀐 값이 없습니다.",
      });
      setAudit(null);
      onChanged();
      return;
    }
    setNotice({ tone: "failure", failure: result, what: "저장" });
    if (result.kind === "validation" && result.problem.field !== null) {
      setFieldErrors({ [result.problem.field]: result.problem.message });
    }
    // 충돌(승인된 문항 등)은 서버 상태가 바뀐 것이므로 최신 값을 다시 읽는다.
    if (result.kind === "conflict") await load();
  }

  async function review(decision: "reviewed" | "needs_review"): Promise<void> {
    setBusy(true);
    const result = await reviewCmsItem(token, meta.key, pk, decision);
    setBusy(false);
    note(result.kind);
    if (result.kind === "ok") {
      setNotice({
        tone: "info",
        text: result.data.changed
          ? "검수 표지를 바꿨습니다 — 현재: " + result.data.review_status
          : "이미 그 상태입니다 — 현재: " + result.data.review_status,
      });
      setAudit(null);
      await load();
      onChanged();
      return;
    }
    setNotice({ tone: "failure", failure: result, what: "검수" });
  }

  async function showAudit(): Promise<void> {
    if (meta.audit_type === null) return;
    setAudit({ kind: "loading" });
    const result = await fetchCmsAudit(token, meta.audit_type, pk);
    note(result.kind);
    setAudit(result);
  }

  if (state.kind === "loading") return <p className={styles.muted}>상세를 불러오는 중…</p>;
  if (state.kind !== "ok") {
    return (
      <CmsFailureBox
        text={describeCmsFailure(state, "상세")}
        onRetry={() => {
          setState({ kind: "loading" });
          void load();
        }}
      />
    );
  }

  const detail = state.data;
  const canEdit = detail.fields.length > 0 && detail.edit_blocked_reason === null;
  const titleId = "wm-cms-detail-" + meta.key;

  return (
    <article className={styles.detail} aria-labelledby={titleId}>
      <h3 id={titleId} className={styles.detailTitle} tabIndex={-1}>
        {meta.label_ko} 상세
      </h3>

      <dl className={styles.meta}>
        {meta.detail_columns.map((column) => {
          const text = cellText(detail.values[column]);
          return (
            <FragmentRow key={column} label={column}>
              {isLong(text) ? <pre className={styles.text}>{text}</pre> : text}
            </FragmentRow>
          );
        })}
      </dl>

      <CmsNoticeView notice={notice} />

      {detail.edit_blocked_reason !== null && (
        <p className={styles.blockedBox} role="note">
          수정할 수 없습니다 — {detail.edit_blocked_reason}
        </p>
      )}

      {canEdit && (
        <section className={styles.block} aria-label="수정">
          <h4 className={styles.blockTitle}>수정</h4>
          {detail.fields.map((field) => (
            <FieldEditor
              key={field.name}
              field={field}
              id={"wm-cms-field-" + field.name}
              value={form[field.name] ?? ""}
              error={fieldErrors[field.name]}
              disabled={busy}
              onChange={(next) => setForm((prev) => ({ ...prev, [field.name]: next }))}
            />
          ))}
          <div className={styles.actions}>
            <button
              className={styles.primaryButton}
              type="button"
              disabled={busy}
              onClick={() => void save(detail)}
            >
              {busy ? "처리 중…" : "저장"}
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              disabled={busy}
              onClick={() => {
                setForm(buildForm(detail));
                setFieldErrors({});
              }}
            >
              되돌리기
            </button>
          </div>
          <p className={styles.hint}>
            저장하면 서버가 검수 표지를 안전한 쪽(미검수)으로 되돌릴 수 있습니다. 상태·발행 값은 여기서
            바꿀 수 없습니다.
          </p>
        </section>
      )}

      {!canEdit && detail.edit_blocked_reason === null && !meta.read_only && (
        <p className={styles.muted}>이 계정은 조회 전용입니다(편집 권한 없음).</p>
      )}
      {meta.read_only && <p className={styles.muted}>이 항목은 읽기 전용입니다.</p>}

      {detail.can_review && (
        <section className={styles.block} aria-label="텍스트 검수">
          <h4 className={styles.blockTitle}>텍스트 검수</h4>
          <div className={styles.actions}>
            <button
              className={styles.actionButton}
              type="button"
              disabled={busy}
              onClick={() => void review("reviewed")}
            >
              검수 완료로 표시
            </button>
            <button
              className={styles.actionButton}
              type="button"
              disabled={busy}
              onClick={() => void review("needs_review")}
            >
              재검수 필요로 되돌리기
            </button>
          </div>
        </section>
      )}

      {meta.audit_type !== null && (
        <section className={styles.block} aria-label="변경이력">
          <h4 className={styles.blockTitle}>변경이력</h4>
          <button
            className={styles.secondaryButton}
            type="button"
            disabled={audit !== null && audit.kind === "loading"}
            onClick={() => void showAudit()}
          >
            변경이력 보기
          </button>
          <AuditView audit={audit} />
        </section>
      )}
    </article>
  );
}

function FragmentRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

/** 변경이력 표 — 동작만 남는다(어느 필드가 어떻게 바뀌었는지는 서버가 기록하지 않는다). */
export function AuditView({ audit }: { audit: null | { kind: "loading" } | CmsResult<CmsAudit> }) {
  if (audit === null) return null;
  if (audit.kind === "loading") return <p className={styles.muted}>이력을 불러오는 중…</p>;
  if (audit.kind !== "ok") {
    return <CmsFailureBox text={describeCmsFailure(audit, "변경이력")} />;
  }
  return (
    <div>
      {audit.data.items.length === 0 ? (
        <p className={styles.emptyBox}>기록된 변경이 없습니다(서버 응답: 0건).</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption className={styles.srOnly}>변경이력</caption>
            <thead>
              <tr>
                <th scope="col">시각</th>
                <th scope="col">동작</th>
                <th scope="col">수행자</th>
              </tr>
            </thead>
            <tbody>
              {audit.data.items.map((row, index) => (
                <tr key={index}>
                  <td>{formatTime(row.occurred_at)}</td>
                  <td>{row.action ?? "-"}</td>
                  <td className={styles.mono} title={row.actor_user_id}>
                    {shortId(row.actor_user_id)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className={styles.hint}>{audit.data.note}</p>
    </div>
  );
}
