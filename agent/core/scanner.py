from pathlib import Path

from .config import BASE_DIR
from .exceptions import AgentError
from .models import CleanResponse, Rule, ScanResponse, ScannedFile

PROJECT_ROOT = BASE_DIR.parent


def _to_abs_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def _is_under_dir(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


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


def clean_files(rule_id: str, files: list[str], rules: list[Rule]) -> CleanResponse:
    rule = next((item for item in rules if item.id == rule_id), None)
    if rule is None:
        raise AgentError("规则不存在", status_code=404)

    allowed_root = _to_abs_path(rule.path)
    if not allowed_root.exists() or not allowed_root.is_dir():
        raise AgentError("规则路径不存在或不是目录", status_code=400)

    deleted_count = 0
    freed_size = 0
    failed_files: list[str] = []

    for raw_path in files:
        target = _to_abs_path(raw_path)

        if not _is_under_dir(target, allowed_root):
            failed_files.append(raw_path)
            continue

        if not target.exists() or not target.is_file():
            failed_files.append(raw_path)
            continue

        try:
            file_size = target.stat().st_size
            target.unlink()
        except OSError:
            failed_files.append(raw_path)
            continue

        deleted_count += 1
        freed_size += file_size

    return CleanResponse(
        deleted_count=deleted_count,
        freed_size=freed_size,
        failed_files=failed_files,
    )
