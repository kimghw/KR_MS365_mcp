"""
파일 경로 허용 목록.

FileHandler / editor 는 호출자가 준 임의 경로를 그대로 열거나 생성한다.
네트워크에 노출된 서버에서는 곧바로 로컬 파일 유출/생성 경로가 된다.
여기서 허용 루트 밖의 경로를 거부한다.

허용 루트 결정:
  1. MCP_ALLOWED_PATHS (os.pathsep 로 구분, 예: Windows 는 ';')
  2. 없으면 프로젝트 루트 + (있다면) MCP_DATA_DIR

심볼릭 링크/`..` 는 realpath 로 해소한 뒤 비교하므로 traversal 로 우회할 수 없다.
"""

import os
from pathlib import Path
from typing import Iterable, List, Optional, Union

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

PathLike = Union[str, "os.PathLike[str]"]


class PathNotAllowedError(Exception):
    """허용되지 않은 경로 접근."""


def allowed_roots() -> List[Path]:
    """현재 설정된 허용 루트 목록."""
    configured = os.environ.get("MCP_ALLOWED_PATHS")
    roots: List[Path] = []
    if configured:
        for entry in configured.split(os.pathsep):
            entry = entry.strip().strip('"')
            if entry:
                try:
                    roots.append(Path(entry).expanduser().resolve())
                except OSError:
                    continue
    if not roots:
        roots.append(_PROJECT_ROOT)
        data_dir = os.environ.get("MCP_DATA_DIR")
        if data_dir:
            try:
                roots.append(Path(data_dir).expanduser().resolve())
            except OSError:
                pass
    return roots


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def is_allowed(path: PathLike, roots: Optional[Iterable[Path]] = None) -> bool:
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError):
        return False
    return any(_is_within(resolved, root) for root in (roots or allowed_roots()))


def resolve_safe_path(path: PathLike, *, must_exist: bool = False) -> Path:
    """
    허용 루트 안의 절대 경로로 정규화해서 돌려준다.

    Raises:
        PathNotAllowedError: 허용 루트 밖이거나 해석할 수 없는 경로
        FileNotFoundError: must_exist=True 인데 대상이 없음
    """
    if path is None or str(path).strip() == "":
        raise PathNotAllowedError("empty path")

    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise PathNotAllowedError(f"cannot resolve path: {path!r} ({exc})") from exc

    roots = allowed_roots()
    if not any(_is_within(resolved, root) for root in roots):
        raise PathNotAllowedError(
            f"path outside allowed roots: {resolved} "
            f"(allowed: {', '.join(str(r) for r in roots)}; "
            f"set MCP_ALLOWED_PATHS to widen)"
        )

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"path does not exist: {resolved}")

    return resolved
