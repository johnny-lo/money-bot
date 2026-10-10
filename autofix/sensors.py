"""三種感測器的入口與簽名。呼叫端只管「失敗了／成功了」，計次與派發交給 incidents。"""
import os
import traceback

from autofix import incidents


def login_failed(label: int, masked: str, exc) -> None:
    incidents.raise_incident(
        "einvoice_login", f"載具{label}", f"載具{label} 發票登入連續失敗",
        {"masked": masked, "attempts": list(getattr(exc, "attempts", []))[-8:],
         "error": str(exc)[:500]},
        dedupe_key=incidents.now_tw().date().isoformat(),
    )


def login_ok(label: int) -> None:
    incidents.clear("einvoice_login", f"載具{label}")


def extract_failed(module: str, platform: str, url: str, exc: Exception) -> None:
    incidents.raise_incident(
        "link_extract", f"{module}:{platform}", f"{module} 的 {platform} 連結抽取連續失敗",
        {"module": module, "platform": platform, "urls": [url],
         "error": f"{type(exc).__name__}: {str(exc)[:300]}"},
        dedupe_key=url,
    )


def extract_ok(module: str, platform: str) -> None:
    incidents.clear("link_extract", f"{module}:{platform}")


def job_signature(job_id: str, exc: BaseException, root: str = "/app/") -> str:
    """job|例外類別|最內層 repo frame 的 相對路徑:函式。刻意不含行號——修正會讓行號漂移。"""
    where = "?"
    for fr in traceback.extract_tb(exc.__traceback__):
        fn = os.path.abspath(fr.filename)
        if fn.startswith(root) and "site-packages" not in fn:
            where = f"{os.path.relpath(fn, root)}:{fr.name}"
    return f"{job_id}|{type(exc).__name__}|{where}"


def job_failed(job_id: str, exc: BaseException, tb: str) -> None:
    incidents.raise_incident(
        "scheduler_job", job_signature(job_id, exc), f"排程 {job_id} 連續拋例外",
        {"job_id": job_id, "error": f"{type(exc).__name__}: {str(exc)[:300]}",
         "traceback": (tb or "")[-3000:]},
        dedupe_key=incidents.now_tw().isoformat(),
    )


def job_ok(job_id: str) -> None:
    incidents.clear("scheduler_job", f"{job_id}|", prefix=True)
