"""Tests for OneDrive integration."""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from ..onedrive import OneDriveClient, OneDriveDownloader, OneDriveProcessor


class TestOneDriveClient(unittest.TestCase):
    """Test OneDrive client."""

    def setUp(self):
        """Setup test fixtures."""
        self.mock_auth = Mock()
        self.mock_auth.get_access_token.return_value = 'test_token'
        self.client = OneDriveClient(self.mock_auth)

    def test_get_headers(self):
        """Test authorization header generation."""
        headers = self.client._get_headers()
        self.assertEqual(headers['Authorization'], 'Bearer test_token')
        self.assertEqual(headers['Content-Type'], 'application/json')

    @patch('requests.get')
    def test_get_item_by_path(self, mock_get):
        """Test getting item by path."""
        mock_response = Mock()
        mock_response.json.return_value = {'id': '123', 'name': 'test.pdf'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = self.client.get_item_by_path('/Documents/test.pdf')

        self.assertEqual(result['id'], '123')
        self.assertEqual(result['name'], 'test.pdf')
        mock_get.assert_called_once()

    @patch('requests.get')
    def test_list_children(self, mock_get):
        """Test listing folder children."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'value': [
                {'id': '1', 'name': 'file1.pdf'},
                {'id': '2', 'name': 'file2.docx'}
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = self.client.list_children('folder_id')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'file1.pdf')


class TestOneDriveDownloader(unittest.TestCase):
    """Test OneDrive downloader."""

    def setUp(self):
        """Setup test fixtures."""
        self.mock_client = Mock(spec=OneDriveClient)
        self.downloader = OneDriveDownloader(self.mock_client)

    def test_download_file_item(self):
        """Test downloading a file item."""
        item = {
            'id': '123',
            'name': 'test.pdf',
            'size': 1024
        }

        self.mock_client.download_file.return_value = '/tmp/test.pdf'

        result = self.downloader.download_item(item)

        self.assertEqual(result['type'], 'file')
        self.assertEqual(result['name'], 'test.pdf')
        self.assertEqual(result['local_path'], '/tmp/test.pdf')
        self.mock_client.download_file.assert_called_once()

    def test_download_folder_item(self):
        """Test handling folder item."""
        item = {
            'id': '456',
            'name': 'TestFolder',
            'folder': {}
        }

        result = self.downloader.download_item(item)

        self.assertEqual(result['type'], 'folder')
        self.assertEqual(result['name'], 'TestFolder')
        # Should not call download_file for folders
        self.mock_client.download_file.assert_not_called()

    def test_cleanup(self):
        """Test temp directory cleanup."""
        import tempfile
        import shutil

        # Create a temp directory
        self.downloader.temp_dir = tempfile.mkdtemp()
        temp_path = self.downloader.temp_dir

        # Ensure it exists
        self.assertTrue(Path(temp_path).exists())

        # Cleanup
        self.downloader.cleanup()

        # Should be removed
        self.assertFalse(Path(temp_path).exists())
        self.assertIsNone(self.downloader.temp_dir)


class TestOneDriveProcessor(unittest.TestCase):
    """Test OneDrive processor."""

    def setUp(self):
        """Setup test fixtures."""
        self.mock_auth = Mock()
        self.processor = OneDriveProcessor(self.mock_auth)

    def test_parse_share_url(self):
        """Test parsing OneDrive share URLs."""
        # Test 1drv.ms URL
        info = self.processor.parse_url('https://1drv.ms/u/s!abc123')
        self.assertEqual(info['type'], 'share')

        # Test onedrive.live.com URL
        info = self.processor.parse_url('https://onedrive.live.com/?id=123')
        self.assertEqual(info['type'], 'share')

        # Test SharePoint URL
        info = self.processor.parse_url('https://company.sharepoint.com/sites/test')
        self.assertEqual(info['type'], 'sharepoint')

        # Test personal URL
        info = self.processor.parse_url('https://company.sharepoint.com/personal/user')
        self.assertEqual(info['type'], 'personal')

    @patch.object(OneDriveDownloader, 'download_by_url')
    def test_process_url(self, mock_download):
        """Test processing OneDrive URL."""
        mock_download.return_value = [
            {'type': 'file', 'name': 'test.pdf', 'local_path': '/tmp/test.pdf'}
        ]

        results = self.processor.process_url('https://1drv.ms/test')

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'test.pdf')
        mock_download.assert_called_once()


if __name__ == '__main__':
    unittest.main()