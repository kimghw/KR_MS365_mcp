"""Main entry point for file conversion and management."""

import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import tempfile
import shutil
import logging

# Add parent directory to path for session imports
sys.path.append(str(Path(__file__).parent.parent))

from session.auth_manager import AuthManager
from .utils import FileDetector, setup_logger
from .metadata.manager import MetadataManager
from .onedrive.processor import OneDriveProcessor
from .config.settings import Settings

# Import mcp_service decorator
from mcp_editor.mcp_service_registry.mcp_service_decorator import mcp_service

logger = setup_logger('file_manager')


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

    @mcp_service(
        tool_name="convert_file_to_text",
        server_name="file_handler",
        service_name="process",
        category="file_conversion",
        tags=["file", "conversion", "text-extraction"],
        priority=10,
        description="Process file or URL for text extraction with support for PDF, DOCX, HWP, Excel, Images, and OneDrive URLs",
        related_objects=["mcp_file_handler.file_manager.FileManager"]
    )
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

        except Exception as e:
            logger.error(f"Error processing {input_path}: {e}")
            result['errors'].append(str(e))
            return result

    def _process_local_file(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """Process local file.

        Args:
            file_path: Path to local file
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

        # Check file exists
        if not Path(file_path).exists():
            result['errors'].append(f"File not found: {file_path}")
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

        try:
            # Parse URL and download
            items = self.onedrive_processor.process_url(url, **kwargs)

            if not items:
                result['errors'].append("No files downloaded from OneDrive")
                return result

            # Process downloaded files
            all_text = []
            all_metadata = []

            for item in items:
                if item['type'] == 'file':
                    file_result = self._process_local_file(
                        item['local_path'],
                        **kwargs
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

        return result

    @mcp_service(
        tool_name="process_directory",
        server_name="file_handler",
        service_name="process_directory",
        category="file_conversion",
        tags=["directory", "batch", "conversion"],
        priority=8,
        description="Process all files in a directory with optional recursive scanning",
        related_objects=["mcp_file_handler.file_manager.FileManager"]
    )
    def process_directory(self, directory_path: str, **kwargs) -> List[Dict[str, Any]]:
        """Process all files in a directory.

        Args:
            directory_path: Path to directory
            **kwargs: Additional options

        Returns:
            List of processing results
        """
        results = []
        dir_path = Path(directory_path)

        if not dir_path.exists() or not dir_path.is_dir():
            logger.error(f"Invalid directory: {directory_path}")
            return results

        # Get file pattern from kwargs
        pattern = kwargs.get('pattern', '*')
        recursive = kwargs.get('recursive', False)

        # Find files
        if recursive:
            files = dir_path.rglob(pattern)
        else:
            files = dir_path.glob(pattern)

        for file_path in files:
            if file_path.is_file():
                logger.info(f"Processing: {file_path}")
                result = self.process(str(file_path), **kwargs)
                result['file'] = str(file_path)
                results.append(result)

        return results

    @mcp_service(
        tool_name="save_file_metadata",
        server_name="file_handler",
        service_name="save_metadata",
        category="metadata",
        tags=["metadata", "storage", "keywords"],
        priority=5,
        description="Save metadata for a processed file with keywords and additional information",
        related_objects=["mcp_file_handler.file_manager.FileManager"]
    )
    def save_metadata(self, file_url: str, keywords: List[str],
                      additional_metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Save metadata for a file.

        Args:
            file_url: File URL or path
            keywords: List of keywords
            additional_metadata: Optional additional metadata

        Returns:
            True if successful
        """
        try:
            return self.metadata_manager.save(file_url, keywords, additional_metadata)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
            return False

    @mcp_service(
        tool_name="search_metadata",
        server_name="file_handler",
        service_name="search_metadata",
        category="metadata",
        tags=["metadata", "search", "query"],
        priority=5,
        description="Search file metadata by various criteria (keywords, date, file type, etc.)",
        related_objects=["mcp_file_handler.file_manager.FileManager"]
    )
    def search_metadata(self, **search_criteria) -> List[Dict[str, Any]]:
        """Search metadata.

        Args:
            **search_criteria: Search criteria

        Returns:
            List of matching metadata entries
        """
        try:
            return self.metadata_manager.search(**search_criteria)
        except Exception as e:
            logger.error(f"Metadata search failed: {e}")
            return []

    @mcp_service(
        tool_name="convert_onedrive_to_text",
        server_name="file_handler",
        service_name="process_onedrive",
        category="file_conversion",
        tags=["onedrive", "cloud", "conversion"],
        priority=9,
        description="Convert OneDrive file or folder to text",
        related_objects=["mcp_file_handler.file_manager.FileManager"]
    )
    def process_onedrive(self, url: str, **kwargs) -> Dict[str, Any]:
        """Process OneDrive URL for text extraction.

        Args:
            url: OneDrive URL
            **kwargs: Additional options

        Returns:
            Processing result dictionary
        """
        return self._process_onedrive_url(url, **kwargs)

    @mcp_service(
        tool_name="get_file_metadata",
        server_name="file_handler",
        service_name="get_metadata",
        category="metadata",
        tags=["metadata", "retrieval"],
        priority=5,
        description="Get metadata for a specific file by URL",
        related_objects=["mcp_file_handler.file_manager.FileManager"]
    )
    def get_metadata(self, file_url: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a file.

        Args:
            file_url: File URL or path

        Returns:
            Metadata dictionary or None if not found
        """
        try:
            return self.metadata_manager.get(file_url)
        except Exception as e:
            logger.error(f"Failed to get metadata: {e}")
            return None

    @mcp_service(
        tool_name="delete_file_metadata",
        server_name="file_handler",
        service_name="delete_metadata",
        category="metadata",
        tags=["metadata", "deletion"],
        priority=3,
        description="Delete metadata for a specific file",
        related_objects=["mcp_file_handler.file_manager.FileManager"]
    )
    def delete_metadata(self, file_url: str) -> bool:
        """Delete metadata for a file.

        Args:
            file_url: File URL or path

        Returns:
            True if successful
        """
        try:
            return self.metadata_manager.delete(file_url)
        except Exception as e:
            logger.error(f"Failed to delete metadata: {e}")
            return False


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
        results = manager.process_directory(
            args.input,
            recursive=args.recursive,
            pattern=args.pattern,
            keywords=args.keywords or [],
            save_metadata=args.save_metadata
        )

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
                Path(args.output).write_text(result['text'])
                print(f"Text saved to: {args.output}")
            else:
                print(result['text'])
        else:
            print(f"Conversion failed: {result['errors']}")
            sys.exit(1)


if __name__ == '__main__':
    main()