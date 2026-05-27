"""SP loader — single source of truth for all agent system prompts."""

import os
from typing import Optional

_SP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sp")

_cache: dict[str, str] = {}


def load_sp(name: str, use_cache: bool = True) -> str:
    """Load a system prompt file from sp/ directory.

    Args:
        name: SP 文件名（不含 .txt 后缀），如 "parser" 对应 sp/parser.txt
        use_cache: 是否使用缓存（默认 True，进程生命周期内只读一次文件）

    Returns:
        SP 文本内容

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 文件内容为空
    """
    if use_cache and name in _cache:
        return _cache[name]

    filepath = os.path.join(_SP_DIR, f"{name}.txt")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"SP file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        raise ValueError(f"SP file is empty: {filepath}")

    _cache[name] = content
    return content


def reload_sp(name: str) -> str:
    """强制重新加载 SP（跳过缓存）。"""
    _cache.pop(name, None)
    return load_sp(name, use_cache=False)


def get_sp_dir() -> str:
    """返回 sp/ 目录的绝对路径。"""
    return _SP_DIR


def list_sp_files() -> list[str]:
    """列出 sp/ 目录下所有 .txt 文件（不含扩展名）。"""
    if not os.path.isdir(_SP_DIR):
        return []
    return [
        f.replace(".txt", "")
        for f in os.listdir(_SP_DIR)
        if f.endswith(".txt")
    ]