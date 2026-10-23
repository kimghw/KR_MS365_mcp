"""OneDrive URL processor.

`download(url, target_dir)` 가 FileManager 의 진입점이다 — 요청마다 **새 downloader** 를
`root=target_dir` 로 만들어, 요청 사이에 공유되는 가변 상태(`downloader.temp_dir`)가 없다.
`process_url()`·`process_path()`·`self.downloader` 는 구버전 호출자 호환용이다.

로그에는 공유 URL·파일명을 싣지 않는다 (spec/spec_멀티유저.md ②-2.7, ②-9).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from ..limits import RequestLimits
from .client import OneDriveClient
from .downloader import OneDriveDownloader

logger = logging.getLogger(__name__)


class OneDriveProcessor:
    """Process OneDrive URLs and coordinate downloads."""

    def __init__(self, auth_manager: Any = None, *, token_provider: Any = None,
                 files_root: Any = None):
        """Initialize processor.

        Args:
            auth_manager: mode 0 전용 auth manager (없으면 공유 AuthManager 를 지연 사용)
            token_provider: mode 1 필수 — 사용자 고정 `BoundTokenProvider`
            files_root: mode 1 의 사용자 `files/` (다운로드 파일 생성 경계)
        """
        self.client = OneDriveClient(auth_manager, token_provider=token_provider, files_root=files_root)
        self.downloader = OneDriveDownloader(self.client)

    def parse_url(self, url: str) -> Dict[str, Any]:
        """Parse OneDrive URL to extract item information.

        Args:
            url: OneDrive URL

        Returns:
            Parsed URL information
        """
        parsed = urlparse(url)
        info = {
            'type': 'unknown',
            'url': url,
            'domain': parsed.netloc
        }

        # Check for share link (1drv.ms or onedrive.live.com)
        if '1drv.ms' in parsed.netloc or 'onedrive.live.com' in parsed.netloc:
            info['type'] = 'share'
            return info

        # Check for SharePoint/OneDrive for Business
        if 'sharepoint.com' in parsed.netloc:
            info['type'] = 'sharepoint'

            # Try to extract item ID from URL
            if '/personal/' in url:
                info['type'] = 'personal'
            elif '/_layouts/15/onedrive.aspx' in url:
                # Extract ID from query params
                params = parse_qs(parsed.query)
                if 'id' in params:
                    info['item_id'] = params['id'][0]

        return info

    def download(
        self,
        url: str,
        target_dir: Path,
        *,
        recursive: bool = True,
        limits: Optional[RequestLimits] = None,
    ) -> List[Dict[str, Any]]:
        """요청 전용 디렉터리 `target_dir` 로 받는다. 정리는 그 디렉터리를 만든 쪽이 한다."""
        target = Path(target_dir)
        url_info = self.parse_url(url)
        logger.info("Processing OneDrive %s URL", url_info['type'])
        downloader = OneDriveDownloader(self.client, root=target, limits=limits)
        results = downloader.download_by_url(url, output_dir=str(target), recursive=recursive)
        logger.info("Downloaded %d OneDrive items", len(results))
        return results

    def process_url(self, url: str, **kwargs) -> List[Dict[str, Any]]:
        """Process OneDrive URL and download files (구버전 호환 — 인스턴스 downloader 사용).

        Args:
            url: OneDrive URL
            **kwargs: Additional options

        Returns:
            List of downloaded items
        """
        try:
            # Parse URL
            url_info = self.parse_url(url)
            logger.info("Processing OneDrive %s URL", url_info['type'])

            # Download based on URL type
            output_dir = kwargs.get('output_dir')
            recursive = kwargs.get('recursive', True)

            results = self.downloader.download_by_url(
                url,
                output_dir=output_dir,
                recursive=recursive
            )

            logger.info("Downloaded %d OneDrive items", len(results))
            return results

        except Exception as e:
            logger.error("Failed to process OneDrive URL: %s", type(e).__name__)
            # Cleanup temp directory on failure only. On success the caller
            # still needs the downloaded files, so it must call cleanup()
            # after consuming them.
            if not kwargs.get('output_dir'):
                self.downloader.cleanup()
            raise

    def cleanup(self):
        """Clean up the temp download directory (call after consuming files)."""
        self.downloader.cleanup()

    def process_path(self, path: str, **kwargs) -> List[Dict[str, Any]]:
        """Process OneDrive path.

        Args:
            path: OneDrive path (e.g., /Documents/file.pdf)
            **kwargs: Additional options

        Returns:
            List of downloaded items
        """
        try:
            # Get item by path
            item = self.client.get_item_by_path(path)

            output_dir = kwargs.get('output_dir')
            recursive = kwargs.get('recursive', True)

            if 'folder' in item:
                # Download folder
                results = self.downloader.download_folder(
                    item['id'],
                    output_dir=output_dir,
                    recursive=recursive
                )
            else:
                # Download single file
                result = self.downloader.download_item(item, output_dir)
                results = [result]

            return results

        except Exception as e:
            logger.error("Failed to process OneDrive path: %s", type(e).__name__)
            raise
        finally:
            # Cleanup if using temp directory
            if not kwargs.get('output_dir'):
                self.downloader.cleanup()
