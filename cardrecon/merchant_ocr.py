"""中信店名圖片 → 文字。店名格疊成一張 PNG 交給 codex 逐行照抄；行數對不上整批放棄（寧缺勿錯）。"""
import json
import struct
import unicodedata
import zlib

from codex_cli import codex_image

from . import config
from .types import Bitmap, Charge

PROMPT = ("圖片是信用卡帳單的店名欄，由上到下每一行是一筆。逐行照抄文字（全形英數字改成半形），"
          "不要合併、不要略過、不要猜測，看不清楚的字用 ? 代替。依序回傳每一行。")
SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
          "required": ["lines"], "additionalProperties": False}


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def to_png(bitmaps: list[Bitmap], scale: int = 2, gap: int = 6) -> bytes:
    """1-bit 圖片由上到下疊成 8-bit 灰階 PNG（白底黑字，放大 scale 倍，每張後面留 gap 列白）。純 stdlib。"""
    width = max(b.width for b in bitmaps) * scale
    white = b"\xff" * width
    rows: list[bytes] = []
    for b in bitmaps:
        stride = (b.width + 7) // 8
        for y in range(b.height):
            line = b.data[y * stride:(y + 1) * stride]
            px = bytearray()
            for x in range(b.width):
                bit = (line[x >> 3] >> (7 - (x & 7))) & 1
                px += (b"\x00" if bit == b.one_is_black else b"\xff") * scale
            row = b"\x00" + bytes(px).ljust(width, b"\xff")
            rows.extend([row] * scale)
        rows.extend([b"\x00" + white] * gap)
    ihdr = struct.pack(">IIBBBBB", width, len(rows), 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows))) + _chunk(b"IEND", b""))


def _read_batch(batch: list[Bitmap]) -> list[str | None]:
    try:
        out = codex_image(PROMPT, to_png(batch), "image/png", schema=SCHEMA)
        lines = json.loads(out)["lines"]
        if len(lines) != len(batch) or not all(isinstance(s, str) for s in lines):
            return [None] * len(batch)
        return [unicodedata.normalize("NFKC", s).strip() or None for s in lines]
    except Exception as e:
        print(f"⚠️ 店名讀圖失敗：{e}", flush=True)
        return [None] * len(batch)


def read_names(bitmaps: list[Bitmap]) -> list[str | None]:
    """每 OCR_BATCH 張一批讀；行數和張數不同、或例外，該批全部 None。"""
    out: list[str | None] = []
    for i in range(0, len(bitmaps), config.OCR_BATCH):
        out.extend(_read_batch(bitmaps[i:i + config.OCR_BATCH]))
    return out


def assign_by_key(charges: list[Charge], named: list[tuple[tuple, str | None]]) -> dict[int, str]:
    """把讀到的店名依 (刷卡日, 入帳日, 金額, 卡號) 對回刷卡。同鍵多筆依 line_no 排序、依序各取一個名字。"""
    pool: dict[tuple, list[str]] = {}
    for key, name in named:
        if name is not None:
            pool.setdefault(key, []).append(name)
    out: dict[int, str] = {}
    for c in sorted(charges, key=lambda c: c.line_no):
        if c.merchant:
            continue
        names = pool.get((c.charge_date, c.post_date, c.amount, c.card_last4))
        if names:
            out[c.line_no] = names.pop(0)
    return out
