"use client";

import { useState } from "react";

import { deleteCmsConcept, type CmsConceptDetail } from "../_lib/adminCmsApi";

import { CmsNoticeView, type CmsNotice, type NoteResult } from "./CmsCommon";

import styles from "./Cms.module.css";

/**
 * 개념 삭제 (P3-26). **되돌릴 수 없는** 작업이라 확인 단계를 둔다.
 *
 * 지울 수 있는지는 화면이 판정하지 않는다 — 서버가 준 `delete_blocked_reason`(사유 문구)이 있으면
 * 버튼을 막고 그 문구를 **그대로** 보인다. 없을 때만 확인 후 요청하고, 그래도 서버가 다시 한 번
 * 판정해 거부할 수 있다(그사이 상태가 바뀐 경우). 권한이 없으면(`can_write_graph=false`) 버튼 대신 안내만 보인다.
 */

interface Props {
  token: string;
  note: NoteResult;
  detail: CmsConceptDetail;
  /** 삭제가 성공한 뒤 — 부모가 선택을 풀고 목록을 다시 읽는다. */
  onDeleted: (conceptCode: string) => void;
  /** 삭제가 거부돼 서버 값이 달라졌을 수 있을 때(부모가 상세를 다시 읽는다). */
  onChanged: () => void;
}

export function CmsConceptDeleteBox({ token, note, detail, onDeleted, onChanged }: Props) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<CmsNotice>(null);

  async function remove(): Promise<void> {
    if (busy) return;
    setBusy(true);
    const result = await deleteCmsConcept(token, detail.concept_id);
    setBusy(false);
    setAsking(false);
    note(result.kind);
    if (result.kind === "ok") {
      onDeleted(result.data.concept_code);
      return;
    }
    setNotice({ tone: "failure", failure: result, what: "개념 삭제" });
    // 거부 사유(발행본·관계·하위 개념 등)가 그사이 달라졌을 수 있다 — 서버 값을 다시 읽는다.
    if (result.kind === "conflict" || result.kind === "not-found") onChanged();
  }

  const blockedReason = detail.delete_blocked_reason;

  return (
    <section className={styles.block} aria-label="개념 삭제">
      <h4 className={styles.blockTitle}>개념 삭제</h4>
      <CmsNoticeView notice={notice} />

      {!detail.can_write_graph ? (
        <p className={styles.muted}>이 계정은 개념을 지울 권한이 없습니다(서버가 허용한 계정에게만 열립니다).</p>
      ) : (
        <>
          {blockedReason !== null && (
            <p className={styles.blockedBox} role="note">
              지울 수 없는 개념입니다. {blockedReason}
            </p>
          )}
          <div className={styles.actions}>
            <button
              className={styles.secondaryButton}
              type="button"
              disabled={busy || blockedReason !== null}
              aria-pressed={asking}
              onClick={() => setAsking(true)}
            >
              개념 삭제
            </button>
          </div>
          {asking && blockedReason === null && (
            <div className={styles.confirm} role="group" aria-label="개념 삭제 확인">
              <p className={styles.confirmText}>
                <strong>{detail.code}</strong> 개념을 지웁니다. <strong>되돌릴 수 없습니다.</strong> 판 이력은
                남지만 이 코드는 다시 쓸 수 없게 예약됩니다. 계속할까요?
              </p>
              <div className={styles.actions}>
                <button
                  className={styles.primaryButton}
                  type="button"
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  {busy ? "처리 중…" : "개념 지우기"}
                </button>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  disabled={busy}
                  onClick={() => setAsking(false)}
                >
                  취소
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
