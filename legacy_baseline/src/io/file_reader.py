from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Iterable

from src.schemas.contracts import SourceFile


SUPPORTED_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
}


def list_input_files(input_dir: str | Path) -> list[SourceFile]:
    """扫描输入目录并返回文件元信息列表。

    Args:
        input_dir: 输入资料所在目录。

    Returns:
        按文件名排序后的 SourceFile 列表。
    """
    root = Path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"输入目录不存在: {root}")

    files: list[SourceFile] = []
    for path in sorted(_iter_files(root), key=lambda item: item.name.lower()):
        suffix = path.suffix.lower()
        stat_result = path.stat()
        files.append(
            SourceFile(
                path=path,
                file_name=path.name,
                suffix=suffix,
                file_type=detect_file_type(path),
                size_bytes=stat_result.st_size,
                modified_at=datetime.fromtimestamp(stat_result.st_mtime),
            )
        )

    return files


def compute_file_hash(file_path: str | Path) -> str:
    """计算文件内容的稳定 SHA256 哈希。

    Args:
        file_path: 待计算哈希的文件路径。

    Returns:
        文件内容哈希。
    """
    path = Path(file_path)
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_file_type(file_path: str | Path) -> str:
    """根据文件后缀判断基础文件类型。

    Args:
        file_path: 待识别的文件路径。

    Returns:
        规范化的文件类型字符串。
    """
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".doc", ".docx"}:
        return "word"
    if suffix in {".ppt", ".pptx"}:
        return "ppt"
    if suffix in {".xls", ".xlsx"}:
        return "spreadsheet"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        return "image"
    if suffix in {".txt", ".md"}:
        return "text"
    return "unknown"


def collect_file_meta(file_path: str | Path) -> SourceFile:
    """收集单个文件的基础元信息。

    Args:
        file_path: 待收集元信息的文件路径。

    Returns:
        SourceFile 对象。
    """
    path = Path(file_path)
    stat_result = path.stat()
    return SourceFile(
        path=path,
        file_name=path.name,
        suffix=path.suffix.lower(),
        file_type=detect_file_type(path),
        size_bytes=stat_result.st_size,
        modified_at=datetime.fromtimestamp(stat_result.st_mtime),
    )


def _iter_files(root: Path) -> Iterable[Path]:
    """递归遍历目录下的所有文件。

    Args:
        root: 待遍历的根目录。

    Returns:
        目录下所有文件路径的迭代器。
    """
    for path in root.rglob("*"):
        if path.is_file():
            yield path
