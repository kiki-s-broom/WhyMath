"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  createCmsDraft,
  fetchCmsVersion,
  fetchCmsVersions,
  type CmsConceptDetail,
  type CmsFailure,
  type CmsResourceMeta,
} from "../_lib/adminCmsApi";

import {
  CmsFailureBox,
  CmsNoticeView,
  cellText,
  describeCmsFailure,
  type CmsNotice,
  type NoteResult,
} from "./CmsCommon";
import { CmsResourcePanel } from "./CmsResourcePanel";

import styles from "./Cms.module.css";

/**
 * 개념 편집 — 살아있는 행(읽기 전용)·관계(읽기 전용)·**새 초안 만들기** (P3-12).
 *
 * 수정은 항상 **새 DRAFT 판**이다. 살아있는 개념 행을 직접 고치는 길이 CMS에 없고(서버가 발행 포인터·
 * 상태를 어떤 경로로도 쓰지 못하게 AST로 동결), 초안이 발행되기까지는 판 이력 화면의 전이(제출→검토→
 * 승인→발행)를 거쳐야 한다. 화면은 그 규칙을 모른다 — 폼이 보내는 것은 "바뀐 필드"뿐이다.
 *
 * 관계(선행/후행)를 읽기 전용으로 두는 이유: 원천 정본이 그래프 파일이라 DB 엣지를 CMS가 고치면 다음
 * 적재가 덮어쓴다. 쓰기를 열기 전에 정본 계약과 DAG 검사가 선행되어야 한다(후속 과제로 등재).
 */

type PayloadBase =
  | { kind: "loading" }
  | { kind: "ready"; payload: Record<string, unknown>; source: string }
  | CmsFailure;

/** 입력기 종류 — 서버가 준 **현재 값의 모양**으로 정한다(필드 이름 목록을 화면이 따로 들지 않는다). */
type EditorKind = "text" | "bool" | "number" | "list" | "json";

function kindOf(value: unknown): EditorKind {
  if (typeof value === "boolean") return "bool";
  if (typeof value === "number") return "number";
  if (typeof value === "string") return "text";
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) return "list";
  // null(미설정)이거나 모양을 모르는 값 — 느슨한 입력으로 받고 최종 판정은 서버가 한다.
  return "json";
}

function toText(kind: EditorKind, value: unknown): string {
  switch (kind) {
    case "bool":
      return value === true ? "true" : "false";
    case "list":
      return (value as string[]).join("\n");
    case "text":
      return value as string;
    case "number":
      return String(value);
    case "json":
      return value === null || value === undefined ? "" : JSON.stringify(value);
  }
}

type Converted = { ok: true; value: unknown } | { ok: false; error: string };

function fromText(kind: EditorKind, text: string): Converted {
  switch (kind) {
    case "bool":
      return { ok: true, value: text === "true" };
    case "list":
      return {
        ok: true,
        value: text
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line.length > 0),
      };
    case "text":
      return { ok: true, value: text };
    case "number": {
      const trimmed = text.trim();
      if (trimmed.length === 0) return { ok: true, value: null };
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? { ok: true, value: parsed } : { ok: false, error: "숫자를 입력하세요." };
    }
    case "json": {
      const trimmed = text.trim();
      if (trimmed.length === 0) return { ok: true, value: null };
      try {
        return { ok: true, value: JSON.parse(trimmed) as unknown };
      } catch {
        // JSON이 아니면 문자열로 받는다(예: 영문명·상위 개념 ID).
        return { ok: true, value: trimmed };
      }
    }
  }
}

/** 표시 전용 한글 이름. 사전에 없는 필드는 원래 이름 그대로 편집기에 나온다(숨기지 않는다). */
const PAYLOAD_LABEL: Record<string, string> = {
  name_ko: "한글 이름",
  name_en: "영문 이름",
  level: "계층(단원·소단원·세부개념)",
  parent_concept_id: "상위 개념 ID",
  aliases: "별칭(한 줄에 하나)",
  is_signature_korean: "한국 수능 특유 개념",
  cognitive_type: "인지 유형(한 줄에 하나)",
  behavior_skills: "연결 스킬(한 줄에 하나)",
  intrinsic_difficulty: "개념 난이도(1~5)",
  exam_frequency: "출제 빈도(0~1)",
  weight_in_curriculum: "교육과정 가중치(0~1)",
};

/** 스킬 연결이 일어나는 payload 필드 — 스킬 찾기 도우미가 이 필드에 id를 덧붙인다. */
const SKILL_FIELD = "behavior_skills";

interface Props {
  token: string;
  note: NoteResult;
  detail: CmsConceptDetail;
  /** 스킬 목록 선언(읽기 전용 리소스). 없으면 스킬 찾기 도우미를 보이지 않는다. */
  skillMeta: CmsResourceMeta | null;
  onChanged: () => void;
}

export function CmsConceptStudioPane({ token, note, detail, skillMeta, onChanged }: Props) {
  const [base, setBase] = useState<PayloadBase>({ kind: "loading" });
  const [notice, setNotice] = useState<CmsNotice>(null);

  /**
   * 초안의 기준을 서버와 **같은 규칙**으로 읽는다: 최신 판이 있으면 그 payload, 없으면 살아있는 행.
   * (서버가 `versions[0].payload`를 기준으로 병합하므로 화면이 다른 기준을 보면 "안 건드린 필드"가
   * 서버에서 다른 값으로 남는다.)
   */
  const loadBase = useCallback(async () => {
    const versions = await fetchCmsVersions(token, detail.concept_id);
    note(versions.kind);
    if (versions.kind !== "ok") {
      setBase(versions);
      return;
    }
    if (versions.data.length === 0) {
      setBase({ kind: "ready", payload: detail.live, source: "살아있는 개념 행" });
      return;
    }
    const newest = versions.data[0];
    const full = await fetchCmsVersion(token, newest.version_id);
    note(full.kind);
    if (full.kind !== "ok") {
      setBase(full);
      return;
    }
    setBase({
      kind: "ready",
      payload: full.data.payload,
      source: "최신 판 v" + String(newest.version_no) + " (" + newest.status + ")",
    });
  }, [token, note, detail.concept_id, detail.live]);

  useEffect(() => {
    setBase({ kind: "loading" });
    void loadBase();
  }, [loadBase]);

  return (
    <div>
      <section className={styles.block} aria-label="현재 개념 행">
        <h4 className={styles.blockTitle}>현재 개념 행 (읽기 전용)</h4>
        <dl className={styles.meta}>
          {Object.entries(detail.live).map(([key, value]) => (
            <Row key={key} label={PAYLOAD_LABEL[key] ?? key}>
              {cellText(value)}
            </Row>
          ))}
        </dl>
      </section>

      <section className={styles.block} aria-label="관계">
        <h4 className={styles.blockTitle}>관계 (읽기 전용)</h4>
        <EdgeList title="이 개념을 선행으로 삼는 관계" edges={detail.incoming} />
        <EdgeList title="이 개념이 선행으로 삼는 관계" edges={detail.outgoing} />
        <p className={styles.hint}>
          관계의 원천 정본이 그래프 파일이라 여기서는 고치지 않습니다(고치면 다음 적재가 덮어씁니다).
        </p>
      </section>

      <section className={styles.block} aria-label="새 초안">
        <h4 className={styles.blockTitle}>새 초안 만들기</h4>
        <CmsNoticeView notice={notice} />
        {!detail.can_edit ? (
          <p className={styles.muted}>이 계정은 조회 전용입니다(편집 권한 없음).</p>
        ) : base.kind === "loading" ? (
          <p className={styles.muted}>초안 기준을 불러오는 중…</p>
        ) : base.kind !== "ready" ? (
          <CmsFailureBox
            text={describeCmsFailure(base, "초안 기준")}
            onRetry={() => {
              setBase({ kind: "loading" });
              void loadBase();
            }}
          />
        ) : (
          <DraftForm
            // 기준이 바뀌면(새 초안 생성 후 재조회) 폼을 새로 시작한다.
            key={base.source + ":" + JSON.stringify(base.payload)}
            token={token}
            note={note}
            conceptId={detail.concept_id}
            payload={base.payload}
            source={base.source}
            skillMeta={skillMeta}
            onNotice={setNotice}
            onCreated={() => {
              onChanged();
              setBase({ kind: "loading" });
              void loadBase();
            }}
          />
        )}
      </section>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function EdgeList(props: { title: string; edges: CmsConceptDetail["incoming"] }) {
  return (
    <div>
      <p className={styles.label}>
        {props.title} ({props.edges.length}건)
      </p>
      {props.edges.length === 0 ? (
        <p className={styles.muted}>(없음)</p>
      ) : (
        <ul className={styles.edgeList}>
          {props.edges.map((edge) => (
            <li key={edge.other_concept_id + ":" + edge.edge_type}>
              {edge.other_code} {edge.other_name_ko} — {edge.edge_type}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DraftForm(props: {
  token: string;
  note: NoteResult;
  conceptId: string;
  payload: Record<string, unknown>;
  source: string;
  skillMeta: CmsResourceMeta | null;
  onNotice: (notice: CmsNotice) => void;
  onCreated: () => void;
}) {
  const { payload } = props;
  const keys = Object.keys(payload);
  const kinds: Record<string, EditorKind> = {};
  for (const key of keys) kinds[key] = kindOf(payload[key]);

  const [form, setForm] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const key of keys) initial[key] = toText(kinds[key], payload[key]);
    return initial;
  });
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  function appendSkill(skillId: string) {
    setForm((prev) => {
      const current = (prev[SKILL_FIELD] ?? "")
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0);
      if (current.includes(skillId)) return prev;
      return { ...prev, [SKILL_FIELD]: [...current, skillId].join("\n") };
    });
  }

  async function submit(): Promise<void> {
    const changes: Record<string, unknown> = {};
    const found: Record<string, string> = {};
    for (const key of keys) {
      const converted = fromText(kinds[key], form[key] ?? "");
      if (!converted.ok) {
        found[key] = converted.error;
        continue;
      }
      if (JSON.stringify(converted.value) !== JSON.stringify(payload[key])) {
        changes[key] = converted.value;
      }
    }
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setBusy(true);
    const trimmed = reason.trim();
    const result = await createCmsDraft(props.token, props.conceptId, changes, trimmed.length > 0 ? trimmed : null);
    setBusy(false);
    props.note(result.kind);
    if (result.kind === "ok") {
      props.onNotice({
        tone: "info",
        text:
          "초안 v" + String(result.data.version_no) + "을 만들었습니다(상태: " + result.data.status +
          "). 바뀐 필드: " + (Object.keys(changes).length > 0 ? Object.keys(changes).join(", ") : "없음") +
          ". 제출·검토·승인·발행은 판 이력 화면에서 진행합니다.",
      });
      props.onCreated();
      return;
    }
    props.onNotice({ tone: "failure", failure: result, what: "초안 생성" });
    if (result.kind === "validation" && result.problem.field !== null) {
      setErrors({ [result.problem.field]: result.problem.message });
    }
  }

  return (
    <div>
      <p className={styles.hint}>기준: {props.source}. 바뀐 필드만 서버로 보냅니다.</p>
      {keys.map((key) => {
        const id = "wm-cms-draft-" + key;
        const kind = kinds[key];
        const label = PAYLOAD_LABEL[key] ?? key;
        return (
          <div className={styles.fieldRow} key={key}>
            {kind === "bool" ? (
              <label className={styles.label} htmlFor={id}>
                <input
                  id={id}
                  className={styles.checkbox}
                  type="checkbox"
                  checked={form[key] === "true"}
                  disabled={busy}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, [key]: event.target.checked ? "true" : "false" }))
                  }
                />{" "}
                {label}
              </label>
            ) : (
              <>
                <label className={styles.label} htmlFor={id}>
                  {label}
                </label>
                {kind === "list" ? (
                  <textarea
                    id={id}
                    className={styles.textarea}
                    rows={3}
                    value={form[key] ?? ""}
                    disabled={busy}
                    onChange={(event) => setForm((prev) => ({ ...prev, [key]: event.target.value }))}
                  />
                ) : (
                  <input
                    id={id}
                    className={`${styles.input} ${styles.fieldInput}`}
                    type="text"
                    value={form[key] ?? ""}
                    disabled={busy}
                    onChange={(event) => setForm((prev) => ({ ...prev, [key]: event.target.value }))}
                  />
                )}
              </>
            )}
            {kind === "json" && (
              <p className={styles.hint}>비워 두면 값 없음. 숫자는 그대로 입력하세요.</p>
            )}
            {errors[key] !== undefined && (
              <p className={styles.fieldError} role="alert">
                {errors[key]}
              </p>
            )}
            {key === SKILL_FIELD && props.skillMeta !== null && (
              <details>
                <summary>스킬 찾기</summary>
                <CmsResourcePanel
                  token={props.token}
                  note={props.note}
                  meta={props.skillMeta}
                  pickLabel="추가"
                  pageSize={8}
                  onPickRow={(row) => {
                    const meta = props.skillMeta;
                    if (meta !== null) appendSkill(cellText(row[meta.pk_column]));
                  }}
                />
              </details>
            )}
          </div>
        );
      })}

      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor="wm-cms-draft-reason">
          변경 사유 (선택, 500자 이내 — 이력에 남습니다)
        </label>
        <input
          id="wm-cms-draft-reason"
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
          {busy ? "처리 중…" : "초안 만들기"}
        </button>
      </div>
    </div>
  );
}
