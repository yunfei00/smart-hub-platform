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


class CleanRequest(BaseModel):
    rule_id: str = Field(..., description="规则 ID")
    files: list[str] = Field(default_factory=list, description="待删除文件路径列表")


class CleanResponse(BaseModel):
    deleted_count: int
    freed_size: int
    failed_files: list[str]
