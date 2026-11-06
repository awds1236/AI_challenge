"""할 일 제목: 공문 문장 → 짧은 할 일 제목, 예전 형식 제목 정리."""
from seomu.notice_text import short_task


def test_short_task_examples():
    cases = {
        "[공공기관 시민체감 서비스 개선방안 제출 요청] 시민이 체감할 수 있는 서비스 개선을 위해 각 처·실에서는 "
        "2027년부터 추진할 서비스 개선과제를 발굴하여 (붙임) 서식으로 작성, 제출하여 주": "서비스 개선과제 작성·제출",
        "참가 신청서(서식), 부서별 참석자 명단 제출": "참가 신청서·부서별 참석자 명단 제출",
        "개인정보 보호 실태 점검과 관련하여 각 부서에서는 자체 점검표를 작성하여 회신하여 주시기 바랍니다.": "자체 점검표 작성·회신",
        "참가신청서 제출": "참가신청서 제출",
        "조사표 회신": "조사표 회신",
    }
    for src, want in cases.items():
        assert short_task(src) == want, (src, short_task(src))


def test_short_task_cuts_at_word_boundary():
    s = short_task("부서별 정보보안 점검 결과와 개선 조치 계획 및 향후 추진 일정과 담당자 지정 현황 제출")
    assert len(s) <= 35 and s.endswith("…") and not s.endswith(" …")


def test_old_task_titles_are_tidied_on_start(tmp_path):
    from seomu.api import Api
    from seomu.config import Config
    from seomu.storage import Store
    home = tmp_path / "home"
    st = Store(Config(home).db_path)
    nid = st.add_notice("서비스 개선방안 제출 요청", "", str(tmp_path), "본문", [], {})
    st.add_task("[서비스 개선방안 제출 요청] 각 처·실에서는 개선과제를 발굴하여 제출하여 주시기 바랍니다", detail="공문: x",
                due="2026-11-10", notice_id=nid)
    st.add_task("[직접 쓴 메모] 이건 그대로", due="2026-11-11")
    st.close()
    api = Api(home)
    titles = {t["title"] for t in api.list_tasks()}
    assert "개선과제 발굴·제출" in titles and "[직접 쓴 메모] 이건 그대로" in titles
    t = next(t for t in api.list_tasks() if t["notice_id"])
    assert "내용: [서비스 개선방안 제출 요청]" in t["detail"]          # 원문은 상세에 남긴다
    api.shutdown()
