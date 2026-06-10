"""食譜 JSON API（PWA 食譜分頁用）。

新增食譜仍走 Discord #🍳-食譜 頻道（需要連結抽取 pipeline）；
這裡只給 PWA 讀清單、改名、刪除。「隨機抽」在前端做——
清單已經整份在手上，前端 random 零延遲、離線也能抽。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from auth import require_token
from recipe.repo import list_recipes, rename, delete_recipe

router = APIRouter()


@router.get("/api/recipes", dependencies=[Depends(require_token)])
def api_list_recipes():
    """全部食譜（新到舊）。"""
    return {"recipes": list_recipes()}


class RenameBody(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("菜名不能是空白")
        return v


@router.put("/api/recipes/{recipe_id}", dependencies=[Depends(require_token)])
def api_rename_recipe(recipe_id: int, body: RenameBody):
    """改菜名（AI 抽歪了手動修）。"""
    rec = rename(recipe_id, body.name)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"找不到食譜 {recipe_id}")
    return {"recipe": rec}


@router.delete("/api/recipes/{recipe_id}", dependencies=[Depends(require_token)])
def api_delete_recipe(recipe_id: int):
    """刪一道食譜。"""
    if not delete_recipe(recipe_id):
        raise HTTPException(status_code=404, detail=f"找不到食譜 {recipe_id}")
    return {"ok": True}
