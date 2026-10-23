"""OneDrive file and folder downloader.

원격 이름(Graph `name`)은 경로가 아니라 **단일 파일 이름**으로 다룬다
(spec/spec_멀티유저.md ②-7.4 규칙 4·6):

- 모든 로컬 경로는 `secure_files.safe_join(base, name)` 으로 만든다 — `../`, 절대경로,
  드라이브·UNC·ADS·예약 장치명은 이름 하나로 정화되고, 최종 경로가 base 안인지 확인한다.
- `root` 가 주어지면(FileManager 는 항상 요청 전용 디렉터리를 준다) 계산한 경로와
  클라이언트가 실제로 쓴 경로가 모두 root 안인지 다시 확인한다.
- 파일 쓰기는 클라이언트가 배타 생성한다(덮어쓰기 없음).

`limits`(`limits.RequestLimits`)가 있으면 받는 파일 수·폴더 깊이·파일 바이트·요청 예산을
적용한다(R09). 초과는 `LimitExceeded` 로 중단한다.

`temp_dir` 는 **구버전 호환용**이다(root·output_dir 없이 부를 때 이 인스턴스 전용 temp 를
만든다). FileManager 는 이 경로를 쓰지 않고 요청마다 새 downloader 를 root 와 함께 만든다 —
인스턴스 하나를 여러 요청이 공유하면 한 요청의 cleanup 이 다른 요청의 파일을 지운다.
mode 1 에서는 root 없이 시스템 temp 를 만들지 않는다.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp_common.secure_files import ensure_within, safe_join
from mcp_common.security_contracts import ErrorCode, SecurityError
from mcp_common.security_policy import multi_user_enabled

from ..limits import RequestLimits
from .client import OneDriveClient

logger = logging.getLogger(__name__)


class OneDriveDownloader:
    """Download files and folders from OneDrive."""

    def __init__(
        self,
        client: OneDriveClient,
        *,
        root: Optional[Path] = None,
        limits: Optional[RequestLimits] = None,
    ):
        """Initialize downloader.

        Args:
            client: OneDrive client instance
            root: 이 downloader 가 쓸 수 있는 최상위 디렉터리 (요청 전용 디렉터리)
            limits: 요청 상한 (파일 수·깊이·바이트). 없으면 제한 없음(구버전 호출자)
        """
        self.client = client
        self.temp_dir = None
        self.root = Path(root) if root is not None else None
        self.limits = limits

    def _base_dir(self, output_dir: Optional[str]) -> Path:
        if output_dir:
            return Path(output_dir)
        if self.root is not None:
            return self.root
        if multi_user_enabled():
            # 사용자 경계 없는 시스템 temp 로 새지 않게 한다
            raise SecurityError(ErrorCode.MISSING_PRINCIPAL)
        if not self.temp_dir:
            self.temp_dir = tempfile.mkdtemp(prefix='onedrive_')
        return Path(self.temp_dir)

    def _target(self, base: Path, name: Any, *, default: str) -> Path:
        path = safe_join(base, name, default=default)
        if self.root is not None:
            ensure_within(path, self.root)
        return path

    def download_item(self, item: Dict[str, Any],
                      output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Download a single item.

        Args:
            item: Item metadata from OneDrive
            output_dir: Optional output directory

        Returns:
            Download result with local path
        """
        base = self._base_dir(output_dir)
        is_folder = 'folder' in item
        output_path = self._target(base, item.get('name'), default='folder' if is_folder else 'file')

        if is_folder:
            return {
                'type': 'folder',
                'name': item['name'],
                'id': item['id'],
                'local_path': str(output_path)
            }

        # It's a file - download it (클라이언트가 배타 생성 — 실제 경로는 반환값)
        if self.limits is not None:
            self.limits.check_deadline()
            self.limits.count_file()
            local_path = self.client.download_file(item['id'], str(output_path), limits=self.limits)
        else:
            local_path = self.client.download_file(item['id'], str(output_path))
        if self.root is not None:
            ensure_within(Path(local_path), self.root)

        return {
            'type': 'file',
            'name': item['name'],
            'id': item['id'],
            'local_path': local_path,
            'size': item.get('size', 0)
        }

    def download_folder(self, folder_id: str,
                        output_dir: Optional[str] = None,
                        recursive: bool = True,
                        *,
                        depth: int = 0) -> List[Dict[str, Any]]:
        """Download all files in a folder.

        Args:
            folder_id: Folder ID
            output_dir: Optional output directory
            recursive: Download subfolders recursively
            depth: 재귀 깊이 (0 = 최상위). `limits.max_depth` 를 넘으면 중단

        Returns:
            List of download results
        """
        results = []

        if self.limits is not None:
            self.limits.check_depth(depth)
            self.limits.check_deadline()

        # 기준 디렉터리가 없으면 하위 폴더를 만들 수 없어 A/x.txt 와 B/x.txt 가 같은 곳에 덮어써진다
        base = self._base_dir(output_dir)

        # Get folder contents
        children = self.client.list_children(folder_id)

        for child in children:
            if 'folder' in child:
                if recursive:
                    # Create subfolder and download contents
                    subfolder_dir = self._target(base, child.get('name'), default='folder')
                    subfolder_dir.mkdir(parents=True, exist_ok=True)

                    sub_results = self.download_folder(
                        child['id'],
                        str(subfolder_dir),
                        recursive=True,
                        depth=depth + 1,
                    )
                    results.extend(sub_results)
                else:
                    # Just add folder info
                    results.append({
                        'type': 'folder',
                        'name': child['name'],
                        'id': child['id'],
                        'skipped': True
                    })
            else:
                # Download file
                result = self.download_item(child, str(base))
                results.append(result)

        return results

    def download_by_url(self, url: str,
                        output_dir: Optional[str] = None,
                        recursive: bool = True) -> List[Dict[str, Any]]:
        """Download from OneDrive URL.

        Args:
            url: OneDrive share URL
            output_dir: Optional output directory
            recursive: Download folders recursively

        Returns:
            List of download results
        """
        try:
            # Get item metadata from URL
            item = self.client.get_item_by_share_url(url)

            if 'folder' in item:
                logger.info("Downloading a OneDrive folder")
                return self.download_folder(item['id'], output_dir, recursive)

            logger.info("Downloading a OneDrive file")
            result = self.download_item(item, output_dir)
            return [result]

        except Exception as e:
            logger.error("Failed to download from OneDrive URL: %s", type(e).__name__)
            raise

    def cleanup(self):
        """Clean up the temp directory **this instance** created (root·output_dir 는 건드리지 않는다)."""
        if self.temp_dir:
            import shutil
            try:
                shutil.rmtree(self.temp_dir)
                logger.info("Cleaned up OneDrive temp directory")
            except Exception as e:
                logger.warning("Failed to clean up temp directory: %s", type(e).__name__)
            finally:
                self.temp_dir = None
