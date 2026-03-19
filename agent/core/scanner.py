import shutil
from pathlib import Path

from .config import BASE_DIR
from .exceptions import AgentError
from .models import CleanResponse, Rule, ScanResponse, ScannedEntry

PROJECT_ROOT = BASE_DIR.parent


def _to_abs_path(raw_path: str, base: Path | None = None) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        root = base or PROJECT_ROOT
        path = root / path
    return path.resolve(strict=False)


def _is_under_dir(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _dir_file_size(target: Path) -> int:
    if target.is_file():
        return target.stat().st_size

    total = 0
    for child in target.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _build_entry(item: Path, rule_root: Path) -> ScannedEntry:
    item_type = "dir" if item.is_dir() else "file"
    rel_path = item.relative_to(rule_root).as_posix()

    if item_type == "file":
        stat = item.stat()
        return ScannedEntry(
            path=rel_path,
            type="file",
            size=stat.st_size,
            mtime=stat.st_mtime,
        )

    dir_stat = item.stat()
    children = [_build_entry(child, rule_root) for child in sorted(item.iterdir(), key=lambda p: p.name)]

    return ScannedEntry(
        path=rel_path,
        type="dir",
        size=_dir_file_size(item),
        mtime=dir_stat.st_mtime,
        children=children,
    )


def _allowed_paths(rules: list[Rule]) -> set[Path]:
    return {_to_abs_path(rule.path) for rule in rules}


def scan_path(target_path: str, rules: list[Rule]) -> ScanResponse:
    allowed_paths = _allowed_paths(rules)
    target = _to_abs_path(target_path)

    if target not in allowed_paths:
        raise AgentError("路径不在允许扫描列表中", status_code=403)

    if not target.exists() or not target.is_dir():
        raise AgentError("扫描路径不存在或不是目录", status_code=400)

    entries: list[ScannedEntry] = []
    total_size = 0
    file_count = 0

    for item in sorted(target.iterdir(), key=lambda p: p.name):
        entry = _build_entry(item, target)
        entries.append(entry)
        total_size += entry.size
        if item.is_file():
            file_count += 1
        else:
            file_count += sum(1 for child in item.rglob("*") if child.is_file())

    return ScanResponse(total_size=total_size, file_count=file_count, files=entries)


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
        target = _to_abs_path(raw_path, base=allowed_root)

        if not _is_under_dir(target, allowed_root):
            failed_files.append(raw_path)
            continue

        if not target.exists():
            failed_files.append(raw_path)
            continue

        try:
            target_size = _dir_file_size(target)
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                failed_files.append(raw_path)
                continue
        except OSError:
            failed_files.append(raw_path)
            continue

        deleted_count += 1
        freed_size += target_size

    return CleanResponse(
        deleted_count=deleted_count,
        freed_size=freed_size,
        failed_files=failed_files,
    )
