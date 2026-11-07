"""검증용 한글 5.0(.hwp) 파일 만들기 — 한글 프로그램 없이 파일 구조를 직접 쓴다.

한글 5.0 문서는 OLE 복합 문서(Compound File Binary, 버전 3) 안에
  FileHeader        : "HWP Document File" 서명, 버전, 속성(압축 여부)
  BodyText/Section0 : 문단 레코드(HWPTAG_PARA_TEXT = 67, UTF-16LE 글자)를 raw deflate로 압축한 스트림
이 들어 있는 형식이다. 여기서는 본문 읽기에 필요한 스트림만 담는다.
4096바이트보다 작은 스트림은 표준대로 미니 스트림(64바이트 단위)에 둔다.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

SECTOR, MINI, CUTOFF = 512, 64, 4096
ENDOFCHAIN, FREESECT, FATSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF


def _para_records(lines: list[str]) -> bytes:
    out = bytearray()
    for line in lines:
        # 탭(9)은 한 글자가 아니라 8글자(16바이트) 크기의 인라인 컨트롤: 코드 + 정보 6글자 + 코드
        line = line.replace("\t", "\t" + "\x00" * 6 + "\t")
        payload = (line + "\r").encode("utf-16-le")          # 문단 끝(13)
        out += struct.pack("<I", 67 | (len(payload) << 20)) + payload
    return bytes(out)


def _dir_entry(name: str, kind: int, left=NOSTREAM, right=NOSTREAM, child=NOSTREAM, start=ENDOFCHAIN, size=0) -> bytes:
    raw = (name + "\x00").encode("utf-16-le")
    e = raw.ljust(64, b"\x00") + struct.pack("<HBB", len(raw), kind, 1)          # 1 = 검은색 노드
    e += struct.pack("<III", left, right, child) + b"\x00" * 16 + struct.pack("<I", 0) + b"\x00" * 16
    return e + struct.pack("<IQ", start, size)


def _chain(start: int, n: int) -> list[int]:
    return [start + i + 1 for i in range(n - 1)] + [ENDOFCHAIN]


def write_hwp(path: Path, lines: list[str], compressed: bool = True) -> None:
    file_header = (b"HWP Document File".ljust(32, b"\x00")
                   + struct.pack("<II", 0x05000300, 1 if compressed else 0)).ljust(256, b"\x00")
    body = _para_records(lines)
    if compressed:
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        body = c.compress(body) + c.flush()
    streams = {"FileHeader": file_header, "Section0": body}

    # 작은 스트림 → 미니 스트림, 큰 스트림 → 일반 섹터
    mini_data, minifat, starts = bytearray(), [], {}
    for name, s in streams.items():
        if len(s) < CUTOFF:
            n = max(1, -(-len(s) // MINI))
            starts[name] = len(minifat)
            minifat += _chain(len(minifat), n)
            mini_data += s.ljust(n * MINI, b"\x00")
    big = [(k, v) for k, v in streams.items() if len(v) >= CUTOFF]
    # 섹터 배치: 0 = FAT, 1 = 디렉터리, 2 = 미니 FAT, 3.. = 미니 스트림 그릇, 그 뒤 = 큰 스트림
    n_container = max(1, -(-len(mini_data) // SECTOR))
    fat = [FATSECT, ENDOFCHAIN, ENDOFCHAIN] + _chain(3, n_container)
    nxt = 3 + n_container
    for name, s in big:
        n = -(-len(s) // SECTOR)
        starts[name] = nxt
        fat += _chain(nxt, n)
        nxt += n
    if len(fat) > SECTOR // 4:
        raise ValueError("예시 파일이 너무 큽니다")
    fat += [FREESECT] * (SECTOR // 4 - len(fat))
    minifat += [FREESECT] * (SECTOR // 4 - len(minifat))

    entries = (_dir_entry("Root Entry", 5, child=1, start=3, size=len(mini_data))
               + _dir_entry("FileHeader", 2, right=2, start=starts["FileHeader"], size=len(file_header))
               + _dir_entry("BodyText", 1, child=3)
               + _dir_entry("Section0", 2, start=starts["Section0"], size=len(body)))
    hdr = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
    hdr += struct.pack("<IIIIIIIII", 0, 1, 1, 0, CUTOFF, 2, 1, ENDOFCHAIN, 0)
    hdr += struct.pack("<I", 0) + struct.pack("<I", FREESECT) * 108                     # DIFAT: FAT은 0번 섹터
    data = bytearray(hdr)
    data += struct.pack(f"<{len(fat)}I", *fat)
    data += entries.ljust(SECTOR, b"\x00")
    data += struct.pack(f"<{len(minifat)}I", *minifat)
    data += bytes(mini_data).ljust(n_container * SECTOR, b"\x00")
    for _name, s in big:
        data += s.ljust(-(-len(s) // SECTOR) * SECTOR, b"\x00")
    Path(path).write_bytes(bytes(data))
