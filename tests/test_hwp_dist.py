"""배포용(암호화) HWP 본문 풀기와, 같은 줄의 행사 기간을 기한으로 잡지 않는 규칙."""
import os
import struct
import zlib
from datetime import date

import pytest

from seomu import parsers
from seomu.deadlines import best_deadlines


def test_aes_pure_python_matches_fips197():
    key = bytes(range(16))
    ct = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    assert parsers._aes128_ecb_decrypt_py(key, ct) == bytes.fromhex("00112233445566778899aabbccddeeff")
    assert parsers._aes128_ecb_decrypt_py(key, ct * 3) == bytes.fromhex("00112233445566778899aabbccddeeff") * 3


def _para(text: str) -> bytes:
    payload = text.encode("utf-16-le")
    return struct.pack("<I", parsers.HWPTAG_PARA_TEXT | (len(payload) << 20)) + payload


def test_distdoc_section_roundtrip():
    """배포용 문서 데이터(256바이트)에서 키를 꺼내 ViewText를 풀고, 문단 글자를 읽는다."""
    crypto = pytest.importorskip("cryptography.hazmat.primitives.ciphers")
    data = bytes(os.urandom(256))
    key = parsers._distdoc_key(data)
    plain = zlib.compress(_para("제출 기한: 2026. 12. 1.까지\r"))[2:-4]       # raw deflate (HWP 압축 방식)
    plain += b"\0" * (-len(plain) % 16)
    enc = crypto.Cipher(crypto.algorithms.AES(key), crypto.modes.ECB()).encryptor()
    raw = struct.pack("<I", parsers.HWPTAG_DISTRIBUTE_DOC_DATA | (256 << 20)) + data + enc.update(plain) + enc.finalize()
    out = parsers._distdoc_section(raw)
    assert out == plain
    assert parsers._aes128_ecb_decrypt_py(key, raw[260:]) == plain
    body = zlib.decompressobj(-15).decompress(out)
    texts = [parsers._hwp_para_text(p) for t, p in parsers._hwp_records(body) if t == parsers.HWPTAG_PARA_TEXT]
    assert "2026. 12. 1." in "".join(texts)


def test_event_period_on_same_line_is_not_deadline():
    text = ("2. 모의훈련(11.10.~11.11.)을 실시할 예정이오니 해당부서에서는 자체 모의훈련을 실시하고 "
            "11. 11.(수) 15시까지 일일상황보고 서식을 제출하여 주시기 바랍니다.")
    got = [(d["date"], d["time"]) for d in best_deadlines(text, date(2026, 11, 9))]
    assert got == [("2026-11-11", "15:00")]


def test_reanalyze_rereads_original_body_file(tmp_path, monkeypatch):
    """예전에 '배포용이라 못 읽음'으로 수집된 공문도 [다시 분석]을 누르면 저장해 둔 본문 원본을 다시 읽는다."""
    monkeypatch.setenv("SEOMU_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SEOMU_DOWNLOADS", str(tmp_path / "dl"))
    from seomu.api import Api
    import time
    api = Api()
    doc = tmp_path / "알림.hwp"
    doc.write_bytes(b"\xd0\xcf\x11\xe0")
    body = "모의훈련 실시 알림\n해당부서는 결과 보고서를 2026. 12. 1.까지 제출하여 주시기 바랍니다."
    state = {"ok": False}
    real = parsers.parse_file

    def fake(p, *a, **k):
        if str(p).endswith(".hwp"):
            if not state["ok"]:
                raise parsers.ParseError("배포용(암호화) HWP 문서는 읽을 수 없습니다")
            return body
        return real(p, *a, **k)
    monkeypatch.setattr(parsers, "parse_file", fake)

    def wait(job):
        for _ in range(200):
            j = api.job_status(job["job_id"])
            if j["status"] != "running":
                assert j["status"] == "done", j
                return j["result"]
            time.sleep(0.05)
    n = wait(api.collect_files([str(doc)], "", 0, False))
    assert n["analysis"].get("body_error")
    state["ok"] = True                                   # 새 버전: 배포용 HWP를 읽을 수 있다
    n2 = wait(api.reanalyze(n["id"]))
    assert "모의훈련" in n2["body"] and not n2["analysis"].get("body_error")
    assert any(d["date"] == "2026-12-01" for d in n2["analysis"]["deadlines"])
