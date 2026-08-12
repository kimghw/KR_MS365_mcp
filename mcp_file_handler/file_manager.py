"""Main entry point for file conversion and management.

보안 주의:
    이 모듈은 MCP 도구를 통해 **호출자가 준 임의 경로**를 받는다. 파일/디렉터리를
    여는 모든 진입점은 `mcp_common.paths.resolve_safe_path()` 를 통과시켜 허용 루트
    (기본: 프로젝트 루트, `MCP_ALLOWED_PATHS` 로 확장) 밖의 접근을 거부한다.
    OneDrive 다운로드 임시 디렉터리는 서버가 직접 만든 것이므로 예외로 허용한다.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Iterable, List, Optional
import tempfile
import shutil
import logging

# Add parent directory to path for session imports
sys.path.append(str(Path(__file__).parent.parent))

from mcp_common.paths import PathNotAllowedError, allowed_roots, resolve_safe_path
from session.auth_manager import AuthManager
from .utils import FileDetector, setup_logger
from .metadata.manager import MetadataManager
from .onedrive.processor import OneDriveProcessor
from .config.settings import Settings

logger = setup_logger('file_manager')

# 로컬 경로가 아니라 원격 참조로 취급할 접두사 (경로 검증 대상 아님)
_REMOTE_PREFIXES = ('http://', 'https://', 'onedrive:')


def _is_remote_ref(value: Any) -> bool:
    """metadata file_url 등이 로컬 경로가 아닌 원격 URL 인지 판정."""
    return isinstance(value, str) and value.strip().lower().startswith(_REMOTE_PREFIXES)


def _allowed_roots_text() -> str:
    return ', '.join(str(root) for root in allowed_roots())


class FileManager:
    """Central manager for file conversion operations."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize FileManager.

        Args:
            config: Optional configuration dictionary
        """
        self.settings = Settings(config)
        self.file_detector = FileDetector()
        self.metadata_manager = MetadataManager(self.settings)
        self.auth_manager = AuthManager()
        self.onedrive_processor = OneDriveProcessor(self.auth_manager)

        # Setup logging
        setup_logger(
            level=self.settings.get('log_level', 'INFO'),
            log_file=self.settings.get('log_file')
        )

    # ------------------------------------------------------------------
    # 경로 검증 헬퍼
    # ------------------------------------------------------------------
    def _resolve_readable_path(
        self,
        path: Any,
        *,
        must_exist: bool = True,
        trusted_roots: Optional[Iterable[Any]] = None,
    ) -> Path:
        """읽기 대상 경로를 허용 루트 안의 절대 경로로 정규화한다.

        Args:
            path: 검증할 경로
            must_exist: 대상이 실제로 존재해야 하는지
            trusted_roots: 서버가 직접 만든 신뢰 루트(OneDrive 임시 다운로드 폴더 등).
                허용 루트 밖이어도 이 루트 하위면 통과시킨다.

        Raises:
            PathNotAllowedError: 허용 루트 밖이거나 해석 불가한 경로
            FileNotFoundError: must_exist=True 인데 대상이 없음
        """
        if trusted_roots:
            try:
                candidate = Path(path).expanduser().resolve()
            except (OSError, ValueError, TypeError):
                candidate = None

            if candidate is not None:
                for root in trusted_roots:
                    if not root:
                        continue
                    try:
                        candidate.relative_to(Path(root).expanduser().resolve())
                    except (ValueError, OSError, TypeError):
                        continue
                    if must_exist and not candidate.exists():
                        raise FileNotFoundError(f"File not found: {candidate}")
                    return candidate

        return resolve_safe_path(path, must_exist=must_exist)

    def _normalize_file_ref(self, file_url: str) -> str:
        """메타데이터 키로 쓸 파일 참조를 정규화한다.

        원격 URL 은 그대로 두고, 로컬 경로는 허용 루트 검증 후 절대 경로로 바꾼다.
        (허용 루트 밖이면 PathNotAllowedError 를 그대로 올린다.)
        """
        if _is_remote_ref(file_url):
            return file_url
        return str(resolve_safe_path(file_url, must_exist=False))

    def process(self, input_path: str, **kwargs) -> Dict[str, Any]:
        """Process file or URL for text extraction.

        Args:
            input_path: File path or URL to process
            **kwargs: Additional options

        Returns:
            Dictionary with extracted text and metadata
        """
        result = {
            'success': False,
            'text': '',
            'metadata': {},
            'errors': []
        }

        try:
            # Check if input is URL
            if self.file_detector.is_url(input_path):
                if self.file_detector.is_onedrive_url(input_path):
                    return self._process_onedrive_url(input_path, **kwargs)
                else:
                    result['errors'].append(f"Unsupported URL type: {input_path}")
                    return result

            # Process local file
            return self._process_local_file(input_path, **kwargs)

        except PathNotAllowedError as e:
            logger.warning(f"Rejected path {input_path}: {e}")
            result['errors'].append(
                f"허용되지 않은 경로입니다: {e} (허용 루트: {_allowed_roots_text()})"
            )
            return result
        except Exception as e:
            logger.error(f"Error processing {input_path}: {e}")
            result['errors'].append(str(e))
            return result

    def _process_local_file(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """Process local file.

        Args:
            file_path: Path to local file (허용 루트 검증을 거친다)
            **kwargs: Additional options.
                `_trusted_roots` 로 서버가 만든 임시 다운로드 루트를 넘길 수 있다.

        Returns:
            Processing result
        """
        result = {
            'success': False,
            'text': '',
            'metadata': {},
            'errors': []
        }

        trusted_roots = kwargs.pop('_trusted_roots', None)

        # 허용 루트 검증 + 존재 확인 (열기 직전 단일 관문)
        try:
            file_path = str(
                self._resolve_readable_path(
                    file_path, must_exist=True, trusted_roots=trusted_roots
                )
            )
        except PathNotAllowedError as e:
            logger.warning(f"Rejected path {file_path}: {e}")
            result['errors'].append(
                f"허용되지 않은 경로입니다: {e} (허용 루트: {_allowed_roots_text()})"
            )
            return result
        except FileNotFoundError as e:
            result['errors'].append(str(e))
            return result

        # Get converter
        converter = self.file_detector.get_converter(file_path)
        if not converter:
            result['errors'].append(f"No converter available for: {file_path}")
            return result

        try:
            # Extract text
            text = converter.convert(file_path)
            metadata = converter.get_metadata(file_path)

            # Store metadata if requested
            if kwargs.get('save_metadata', False):
                keywords = kwargs.get('keywords', [])
                self.metadata_manager.save(file_path, keywords, metadata)

            result.update({
                'success': True,
                'text': text,
                'metadata': metadata
            })

        except Exception as e:
            logger.error(f"Conversion failed for {file_path}: {e}")
            result['errors'].append(str(e))

        return result

    def _process_onedrive_url(self, url: str, **kwargs) -> Dict[str, Any]:
        """Process OneDrive URL.

        Args:
            url: OneDrive URL
            **kwargs: Additional options

        Returns:
            Processing result
        """
        result = {
            'success': False,
            'text': '',
            'metadata': {},
            'errors': []
        }

        # 다운로드 대상 디렉터리는 호출자가 줄 수 있으므로 쓰기 전에 검증한다.
        output_dir = kwargs.get('output_dir')
        if output_dir:
            try:
                kwargs['output_dir'] = str(resolve_safe_path(output_dir, must_exist=False))
            except PathNotAllowedError as e:
                result['errors'].append(
                    f"허용되지 않은 output_dir 입니다: {e} (허용 루트: {_allowed_roots_text()})"
                )
                return result

        try:
            # Parse URL and download
            items = self.onedrive_processor.process_url(url, **kwargs)

            if not items:
                result['errors'].append("No files downloaded from OneDrive")
                return result

            # 서버가 직접 만든 임시 다운로드 폴더는 허용 루트 밖이어도 신뢰한다.
            trusted_roots = [
                root
                for root in (
                    getattr(self.onedrive_processor.downloader, 'temp_dir', None),
                    kwargs.get('output_dir'),
                )
                if root
            ]

            # Process downloaded files
            all_text = []
            all_metadata = []

            for item in items:
                if item['type'] == 'file':
                    local_kwargs = dict(kwargs)
                    local_kwargs['_trusted_roots'] = trusted_roots
                    file_result = self._process_local_file(
                        item['local_path'],
                        **local_kwargs
                    )
                    if file_result['success']:
                        all_text.append(f"--- {item['name']} ---")
                        all_text.append(file_result['text'])
                        all_metadata.append(file_result['metadata'])
                    else:
                        result['errors'].extend(file_result['errors'])

            result.update({
                'success': len(all_text) > 0,
                'text': '\n\n'.join(all_text),
                'metadata': {
                    'source': 'onedrive',
                    'url': url,
                    'files_processed': len(all_metadata),
                    'file_metadata': all_metadata
                }
            })

        except Exception as e:
            logger.error(f"OneDrive processing failed for {url}: {e}")
            result['errors'].append(str(e))
        finally:
            # Temp files were kept alive so they could be read above;
            # clean them up now that processing is done.
            if not kwargs.get('output_dir'):
                self.onedrive_processor.cleanup()

        return result

    def process_directory(self, directory_path: str, **kwargs) -> List[Dict[str, Any]]:
        """Process all files in a directory.

        Args:
            directory_path: Path to directory (허용 루트 안이어야 한다)
            **kwargs: Additional options

        Returns:
            List of processing results

        Raises:
            PathNotAllowedError: 허용 루트 밖의 디렉터리
            FileNotFoundError: 존재하지 않는 경로
            NotADirectoryError: 디렉터리가 아님
            ValueError: pattern 이 절대 경로일 때

        조용히 빈 목록을 돌려주면 실패가 성공처럼 보이므로, 잘못된 입력은 예외로 올린다.
        """
        results: List[Dict[str, Any]] = []

        dir_path = resolve_safe_path(directory_path, must_exist=True)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        # Get file pattern from kwargs
        pattern = kwargs.get('pattern', '*') or '*'
        recursive = kwargs.get('recursive', False)

        # 절대 경로 패턴은 허용 루트 밖을 노릴 수 있으므로 거부한다.
        if Path(pattern).is_absolute():
            raise ValueError(f"pattern must be relative: {pattern}")

        # Find files
        if recursive:
            files = dir_path.rglob(pattern)
        else:
            files = dir_path.glob(pattern)

        for file_path in files:
            if not file_path.is_file():
                continue

            # 패턴/심볼릭 링크로 허용 루트를 벗어난 항목은 건너뛴다.
            try:
                safe_path = resolve_safe_path(file_path, must_exist=True)
            except (PathNotAllowedError, FileNotFoundError) as e:
                logger.warning(f"Skipped {file_path}: {e}")
                continue

            logger.info(f"Processing: {safe_path}")
            result = self.process(str(safe_path), **kwargs)
            result['file'] = str(safe_path)
            results.append(result)

        return results

    def save_metadata(self, file_url: str, keywords: List[str],
                      additional_metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Save metadata for a file.

        Args:
            file_url: File URL or path (로컬 경로면 허용 루트 검증 후 절대 경로로 정규화)
            keywords: List of keywords
            additional_metadata: Optional additional metadata

        Returns:
            True if successful

        Raises:
            PathNotAllowedError: 허용 루트 밖의 로컬 경로
        """
        file_url = self._normalize_file_ref(file_url)
        try:
            return self.metadata_manager.save(file_url, keywords, additional_metadata)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
            return False

    def search_metadata(self, **search_criteria) -> List[Dict[str, Any]]:
        """Search metadata.

        Args:
            **search_criteria: Search criteria

        Returns:
            List of matching metadata entries
        """
        # DB 예외는 삼키지 않는다: "결과 0건"은 storage 가 정상적으로 빈 리스트를
        # 반환하며, 실제 DB 예외는 상위 런타임에서 isError 로 승격되도록 전파한다.
        return self.metadata_manager.search(**search_criteria)

    def process_onedrive(self, url: str, **kwargs) -> Dict[str, Any]:
        """Process OneDrive URL for text extraction.

        Args:
            url: OneDrive URL
            **kwargs: Additional options

        Returns:
            Processing result dictionary
        """
        return self._process_onedrive_url(url, **kwargs)

    def get_metadata(self, file_url: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a file.

        Args:
            file_url: File URL or path (로컬 경로면 허용 루트 검증 후 절대 경로로 정규화)

        Returns:
            Metadata dictionary or None if not found

        Raises:
            PathNotAllowedError: 허용 루트 밖의 로컬 경로
        """
        file_url = self._normalize_file_ref(file_url)
        # 미존재는 None(정상 "결과 없음"), 실제 DB 예외는 실패로 전파한다.
        return self.metadata_manager.get(file_url)

    def delete_metadata(self, file_url: str) -> bool:
        """Delete metadata for a file.

        Args:
            file_url: File URL or path (로컬 경로면 허용 루트 검증 후 절대 경로로 정규화)

        Returns:
            True if successful

        Raises:
            PathNotAllowedError: 허용 루트 밖의 로컬 경로
        """
        file_url = self._normalize_file_ref(file_url)
        # 미존재/멱등 재삭제는 False(정상), 실제 DB 예외는 실패로 전파한다.
        return self.metadata_manager.delete(file_url)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='File to Text Converter')
    parser.add_argument('input', help='File path or URL to process')
    parser.add_argument('--output', '-o', help='Output file path')
    parser.add_argument('--keywords', '-k', nargs='+', help='Keywords for metadata')
    parser.add_argument('--save-metadata', action='store_true',
                        help='Save metadata to storage')
    parser.add_argument('--recursive', '-r', action='store_true',
                        help='Process directory recursively')
    parser.add_argument('--pattern', '-p', default='*',
                        help='File pattern for directory processing')

    args = parser.parse_args()

    # Initialize manager
    manager = FileManager()

    # Process input
    if Path(args.input).is_dir():
        try:
            results = manager.process_directory(
                args.input,
                recursive=args.recursive,
                pattern=args.pattern,
                keywords=args.keywords or [],
                save_metadata=args.save_metadata
            )
        except (PathNotAllowedError, OSError, ValueError) as e:
            print(f"Directory processing failed: {e}")
            sys.exit(1)

        for result in results:
            if result['success']:
                print(f"[OK] {result['file']}")
            else:
                print(f"[FAIL] {result['file']}: {result['errors']}")

    else:
        result = manager.process(
            args.input,
            keywords=args.keywords or [],
            save_metadata=args.save_metadata
        )

        if result['success']:
            if args.output:
                try:
                    output_path = resolve_safe_path(args.output, must_exist=False)
                except PathNotAllowedError as e:
                    print(f"Output path rejected: {e}")
                    sys.exit(1)
                output_path.write_text(result['text'], encoding='utf-8')
                print(f"Text saved to: {output_path}")
            else:
                print(result['text'])
        else:
            print(f"Conversion failed: {result['errors']}")
            sys.exit(1)


if __name__ == '__main__':
    main()