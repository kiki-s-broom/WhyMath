/* 원자적 JSON 저장 (HARN-206) — 임시 파일에 쓰고 rename 한다.
   이 모듈이 앱 안에서 파일을 *쓰는* 유일한 곳이다. 작업공간의 backlog/ 경로를 여기로 넘기는
   호출이 없어야 한다(거버넌스 테스트 tests/unit/governance.test.ts가 소스를 스캔한다). */
import { promises as fs } from "node:fs";
import path from "node:path";

export async function readJson<T>(file: string): Promise<T | null> {
  try {
    const text = await fs.readFile(file, "utf8");
    return JSON.parse(text) as T;
  } catch (err) {
    const e = err as NodeJS.ErrnoException;
    if (e && e.code === "ENOENT") return null;
    // 손상된 파일은 조용히 null로 접지 않는다 — 호출자가 사유를 보게 예외 타입명을 붙여 던진다
    throw new Error(`${e?.name ?? "Error"}: ${file} 읽기 실패 — ${e?.message ?? String(err)}`);
  }
}

export async function atomicWriteJson(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  const text = JSON.stringify(value, null, 2) + "\n";
  try {
    await fs.writeFile(tmp, text, "utf8");
    await fs.rename(tmp, file);
  } catch (err) {
    try { await fs.unlink(tmp); } catch { /* 임시 파일이 없으면 그만 */ }
    throw err;
  }
}

export async function removeFile(file: string): Promise<boolean> {
  try {
    await fs.unlink(file);
    return true;
  } catch (err) {
    const e = err as NodeJS.ErrnoException;
    if (e && e.code === "ENOENT") return false;
    throw err;
  }
}
