"""加密 PDF → 文字。銀行預設密碼是身分證字號（英文大寫）。"""
import io

from pypdf import PdfReader


def extract_text(data: bytes, password: str) -> str | None:
    """解不開或壞檔回 None（呼叫端計數成「解密失敗」），不丟例外。"""
    try:
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted and not r.decrypt(password.strip().upper()):
            return None
        return "\n".join(p.extract_text() or "" for p in r.pages)
    except Exception:
        return None
