from pathlib import Path

from .config import BASE_DIR
from .exceptions import AgentError
from .models import Rule, ScanResponse, ScannedFile

PROJECT_ROOT = BASE_DIR.parent


def _to_abs_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def scan_path(target_path: str, rules: list[Rule]) -> ScanResponse:
    allowed_paths = {_to_abs_path(rule.path) for rule in rules}
    target = _to_abs_path(target_path)

    if target not in allowed_paths:
        raise AgentError("路径不在允许扫描列表中", status_code=403)

    if not target.exists() or not target.is_dir():
        raise AgentError("扫描路径不存在或不是目录", status_code=400)

    files: list[ScannedFile] = []
    total_size = 0

    for file_path in target.rglob("*"):
        if not file_path.is_file():
            continue

        stat = file_path.stat()
        rel_path = file_path.relative_to(PROJECT_ROOT).as_posix()

        files.append(
            ScannedFile(path=rel_path, size=stat.st_size, mtime=stat.st_mtime)
        )
        total_size += stat.st_size

    return ScanResponse(total_size=total_size, file_count=len(files), files=files)
