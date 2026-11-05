"""AI 응답 시간 측정 — 이 PC의 실제 모델(내장 엔진 또는 Ollama)로 잰다.

사용: python tools/bench_ai.py
- 예시 공문 분석 2건(두 번째는 고정 지시문 캐시 재사용), 예시 내규로 규정 Q&A 1건, 메일 다듬기 1건을 실행하고
  첫 글자까지 걸린 시간과 전체 시간을 보여 준다. 설정(settings.json)의 엔진·모델을 그대로 쓴다.
"""
from __future__ import annotations

import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from seomu.analyzer import analyze  # noqa: E402
from seomu.api import Api  # noqa: E402
from seomu.mail import POLISH_PROMPT  # noqa: E402
from seomu.parsers import parse_file  # noqa: E402
from seomu.rag import RAGEngine  # noqa: E402
from seomu.storage import Store  # noqa: E402


def timed(label: str, fn):
    first: list[float] = []
    t0 = time.perf_counter()
    out = fn(lambda _t: first or first.append(time.perf_counter() - t0))
    total = time.perf_counter() - t0
    ttft = f"{first[0]:6.1f}초" if first else "   -  "
    print(f"{label:<28} 첫 글자 {ttft} / 전체 {total:6.1f}초")
    return out


def main() -> int:
    api = Api()
    client = api._client()
    s = api._cfg.settings
    st = client.status()
    if not st.get("ok"):
        print("AI 엔진을 사용할 수 없습니다:", st.get("error"))
        return 1
    model = client.pick_chat_model(s.chat_model)
    print(f"엔진: {api._engine_kind()} / 모델: {model}\n")

    t0 = time.perf_counter()
    client.preload(model)
    print(f"{'모델 불러오기':<28} {time.perf_counter() - t0:6.1f}초")

    body = parse_file(ROOT / "sample_data" / "notice" / "예시_공문.html")
    files = [{"ok": True, "path": str(p)} for p in (ROOT / "sample_data" / "notice" / "files").glob("*")]
    timed("공문 분석 #1", lambda _cb: analyze("청렴 교육 행사 참여 요청", body, files, client, model, s.num_ctx, date.today()))
    body2 = body.replace("청렴 교육", "안전 점검").replace("11. 13.", "11. 20.")
    timed("공문 분석 #2 (캐시 재사용)", lambda _cb: analyze("안전 점검 참여 요청", body2, files, client, model, s.num_ctx, date.today()))

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "b.db")

        class Cfg:
            regulation_dirs = [str(ROOT / "sample_data" / "regulations")]
            embed_model = ""
            chat_model = s.chat_model
            top_k = s.top_k
            temperature = s.temperature
            num_ctx = s.num_ctx
        rag = RAGEngine(store, lambda: client, lambda: Cfg)
        rag.reindex()
        timed("규정 Q&A", lambda cb: rag.answer("출장 다녀오면 복명서는 언제까지 내야 하나요?", on_token=cb))
        store.close()

    draft = "각 부서에서는 2026. 11. 13.(금)까지 참가 신청서를 제출해 주시기 바랍니다. 문의는 감사관 청렴팀으로 해 주세요."
    timed("메일 다듬기", lambda cb: client.chat([{"role": "user", "content": POLISH_PROMPT.format(body=draft)}], model,
                                               num_ctx=s.num_ctx, on_token=cb, max_tokens=int(len(draft) * 1.1) + 160))
    api.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
