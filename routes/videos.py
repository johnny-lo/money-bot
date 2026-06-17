"""歷史影片 JSON API（PWA 🎥 分頁用）。

新增影片走 Discord 頻道（需連結抽取 pipeline）；這裡給 PWA 讀清單 + 編輯主題/標籤/刪除。
回全部、前端再過濾（與 /api/food/places 一致）。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from auth import require_token
from video import repo

router = APIRouter()


@router.get("/api/videos", dependencies=[Depends(require_token)])
def api_list_videos():
    """全部影片（新到舊，每筆附 tags + thumbnail）。"""
    return {"videos": repo.list_videos()}


class UpdateBody(BaseModel):
    title: str | None = None
    topic: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("標題不能是空白")
        return v

    @field_validator("topic")
    @classmethod
    def topic_strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class TagBody(BaseModel):
    tag: str

    @field_validator("tag")
    @classmethod
    def tag_not_blank(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("標籤不能是空白")
        return v


@router.put("/api/videos/{video_id}", dependencies=[Depends(require_token)])
def api_update_video(video_id: int, body: UpdateBody):
    """改標題 / 設主題（只送有改的欄位）。"""
    out = None
    if body.title is not None:
        out = repo.rename(video_id, body.title)
        if out is None:
            raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    if body.topic is not None:
        out = repo.set_topic(video_id, body.topic)
        if out is None:
            raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    if out is None:
        out = repo.get(video_id)
        if out is None:
            raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    return {"video": out}


@router.post("/api/videos/{video_id}/tags", dependencies=[Depends(require_token)])
def api_add_tag(video_id: int, body: TagBody):
    """加一個標籤。"""
    if not repo.add_tag(video_id, body.tag):
        raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    return {"video": repo.get(video_id)}


@router.delete("/api/videos/{video_id}/tags/{tag}", dependencies=[Depends(require_token)])
def api_remove_tag(video_id: int, tag: str):
    """刪一個標籤（tag 走 path param，前端 encodeURIComponent）。"""
    if not repo.remove_tag(video_id, tag):
        raise HTTPException(status_code=404, detail="找不到該標籤")
    return {"ok": True}


@router.delete("/api/videos/{video_id}", dependencies=[Depends(require_token)])
def api_delete_video(video_id: int):
    """刪一支影片（連帶刪標籤）。"""
    if not repo.delete_video(video_id):
        raise HTTPException(status_code=404, detail=f"找不到影片 {video_id}")
    return {"ok": True}
