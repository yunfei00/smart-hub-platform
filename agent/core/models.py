from pydantic import BaseModel, Field


class Rule(BaseModel):
    id: str
    name: str
    path: str
    description: str | None = None


class RulesResponse(BaseModel):
    rules: list[Rule]


class ScanRequest(BaseModel):
    path: str = Field(..., description="扫描目录（必须命中 rules.json 允许路径）")


class ScannedFile(BaseModel):
    path: str
    size: int
    mtime: float


class ScanResponse(BaseModel):
    total_size: int
    file_count: int
    files: list[ScannedFile]
