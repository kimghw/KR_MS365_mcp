"""OneDrive URL processor."""

import re
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Any, Optional
import logging

from .client import OneDriveClient
from .downloader import OneDriveDownloader

logger = logging.getLogger(__name__)


class OneDriveProcessor:
    """Process OneDrive URLs and coordinate downloads."""

    def __init__(self, auth_manager):
        """Initialize processor.

        Args:
            auth_manager: AuthManager instance
        """
        self.client = OneDriveClient(auth_manager)
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

    def process_url(self, url: str, **kwargs) -> List[Dict[str, Any]]:
        """Process OneDrive URL and download files.

        Args:
            url: OneDrive URL
            **kwargs: Additional options

        Returns:
            List of downloaded items
        """
        try:
            # Parse URL
            url_info = self.parse_url(url)
            logger.info(f"Processing {url_info['type']} URL: {url}")

            # Download based on URL type
            output_dir = kwargs.get('output_dir')
            recursive = kwargs.get('recursive', True)

            results = self.downloader.download_by_url(
                url,
                output_dir=output_dir,
                recursive=recursive
            )

            logger.info(f"Downloaded {len(results)} items from {url}")
            return results

        except Exception as e:
            logger.error(f"Failed to process URL {url}: {e}")
            raise
        finally:
            # Cleanup if using temp directory
            if not kwargs.get('output_dir'):
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
            logger.error(f"Failed to process path {path}: {e}")
            raise
        finally:
            # Cleanup if using temp directory
            if not kwargs.get('output_dir'):
                self.downloader.cleanup()