"""OneDrive file and folder downloader."""

import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

from .client import OneDriveClient

logger = logging.getLogger(__name__)


class OneDriveDownloader:
    """Download files and folders from OneDrive."""

    def __init__(self, client: OneDriveClient):
        """Initialize downloader.

        Args:
            client: OneDrive client instance
        """
        self.client = client
        self.temp_dir = None

    def download_item(self, item: Dict[str, Any],
                      output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Download a single item.

        Args:
            item: Item metadata from OneDrive
            output_dir: Optional output directory

        Returns:
            Download result with local path
        """
        if not output_dir:
            if not self.temp_dir:
                self.temp_dir = tempfile.mkdtemp(prefix='onedrive_')
            output_dir = self.temp_dir

        output_path = Path(output_dir) / item['name']

        if 'folder' in item:
            # It's a folder
            return {
                'type': 'folder',
                'name': item['name'],
                'id': item['id'],
                'local_path': str(output_path)
            }

        # It's a file - download it
        local_path = self.client.download_file(item['id'], str(output_path))

        return {
            'type': 'file',
            'name': item['name'],
            'id': item['id'],
            'local_path': local_path,
            'size': item.get('size', 0)
        }

    def download_folder(self, folder_id: str,
                        output_dir: Optional[str] = None,
                        recursive: bool = True) -> List[Dict[str, Any]]:
        """Download all files in a folder.

        Args:
            folder_id: Folder ID
            output_dir: Optional output directory
            recursive: Download subfolders recursively

        Returns:
            List of download results
        """
        results = []

        # Get folder contents
        children = self.client.list_children(folder_id)

        for child in children:
            if 'folder' in child:
                if recursive:
                    # Create subfolder and download contents
                    subfolder_dir = Path(output_dir) / child['name'] if output_dir else None
                    if subfolder_dir:
                        subfolder_dir.mkdir(parents=True, exist_ok=True)

                    sub_results = self.download_folder(
                        child['id'],
                        str(subfolder_dir) if subfolder_dir else None,
                        recursive=True
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
                result = self.download_item(child, output_dir)
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
                # Download folder contents
                logger.info(f"Downloading folder: {item['name']}")
                return self.download_folder(item['id'], output_dir, recursive)
            else:
                # Download single file
                logger.info(f"Downloading file: {item['name']}")
                result = self.download_item(item, output_dir)
                return [result]

        except Exception as e:
            logger.error(f"Failed to download from URL {url}: {e}")
            raise

    def cleanup(self):
        """Clean up temporary files."""
        if self.temp_dir:
            import shutil
            try:
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")
            finally:
                self.temp_dir = None