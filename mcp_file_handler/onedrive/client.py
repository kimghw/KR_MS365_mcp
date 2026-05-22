"""OneDrive API client using AuthManager."""

import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging
import requests

# Add parent directory for session imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from session.auth_manager import AuthManager

logger = logging.getLogger(__name__)


class OneDriveClient:
    """OneDrive API client."""

    def __init__(self, auth_manager: Optional[AuthManager] = None):
        """Initialize OneDrive client.

        Args:
            auth_manager: AuthManager instance for authentication
        """
        self.auth_manager = auth_manager or AuthManager()
        self.base_url = 'https://graph.microsoft.com/v1.0'

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers.

        Returns:
            Headers with authorization token
        """
        token = self.auth_manager.get_access_token()
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

    def get_item_by_path(self, path: str) -> Dict[str, Any]:
        """Get item metadata by path.

        Args:
            path: OneDrive path

        Returns:
            Item metadata
        """
        url = f"{self.base_url}/me/drive/root:/{path}"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def get_item_by_id(self, item_id: str) -> Dict[str, Any]:
        """Get item metadata by ID.

        Args:
            item_id: OneDrive item ID

        Returns:
            Item metadata
        """
        url = f"{self.base_url}/me/drive/items/{item_id}"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def get_item_by_share_url(self, share_url: str) -> Dict[str, Any]:
        """Get item metadata from share URL.

        Args:
            share_url: OneDrive share URL

        Returns:
            Item metadata
        """
        import base64

        # Encode the share URL
        encoded_url = base64.urlsafe_b64encode(
            share_url.encode('utf-8')
        ).rstrip(b'=').decode('utf-8')

        url = f"{self.base_url}/shares/{encoded_url}/driveItem"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def list_children(self, item_id: str) -> List[Dict[str, Any]]:
        """List children of a folder.

        Args:
            item_id: Folder item ID

        Returns:
            List of child items
        """
        url = f"{self.base_url}/me/drive/items/{item_id}/children"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json().get('value', [])

    def download_file(self, item_id: str, output_path: str) -> str:
        """Download file by ID.

        Args:
            item_id: File item ID
            output_path: Local path to save file

        Returns:
            Path to downloaded file
        """
        # Get download URL
        url = f"{self.base_url}/me/drive/items/{item_id}/content"
        response = requests.get(
            url,
            headers=self._get_headers(),
            allow_redirects=False
        )

        if response.status_code == 302:
            # Follow redirect to download
            download_url = response.headers['Location']
            download_response = requests.get(download_url, stream=True)
            download_response.raise_for_status()

            # Save file
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)

            with open(output, 'wb') as f:
                for chunk in download_response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Downloaded: {output}")
            return str(output)

        response.raise_for_status()
        return output_path

    def get_file_content(self, item_id: str) -> bytes:
        """Get file content directly.

        Args:
            item_id: File item ID

        Returns:
            File content as bytes
        """
        url = f"{self.base_url}/me/drive/items/{item_id}/content"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.content