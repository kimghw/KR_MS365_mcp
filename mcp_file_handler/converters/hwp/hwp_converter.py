"""HWP (Hangul Word Processor) to text converter."""

from pathlib import Path
import logging
import struct
import zlib

from ...base_converter import BaseConverter

logger = logging.getLogger(__name__)


class HWPConverter(BaseConverter):
    """Convert HWP files to text."""

    def convert(self, file_path: str) -> str:
        """Convert HWP file to text.

        Args:
            file_path: Path to the HWP file

        Returns:
            Extracted text content
        """
        if not self.supports(file_path):
            raise ValueError(f"File {file_path} is not a HWP file")

        try:
            # Try pyhwp first if available
            return self._convert_with_pyhwp(file_path)
        except (ImportError, Exception):
            # Fallback to olefile-based extraction
            try:
                return self._convert_with_olefile(file_path)
            except Exception as e:
                logger.error(f"Error converting HWP {file_path}: {e}")
                raise

    def _convert_with_pyhwp(self, file_path: str) -> str:
        """Convert using pyhwp library.

        Args:
            file_path: Path to the HWP file

        Returns:
            Extracted text content
        """
        import pyhwp

        hwp = pyhwp.HWPDocument(file_path)
        text_content = []

        for section in hwp.sections:
            for para in section.paragraphs:
                text = para.get_text()
                if text.strip():
                    text_content.append(text)

        return '\n\n'.join(text_content)

    def _convert_with_olefile(self, file_path: str) -> str:
        """Convert using olefile library for basic text extraction.

        Args:
            file_path: Path to the HWP file

        Returns:
            Basic extracted text content
        """
        import olefile

        ole = olefile.OleFileIO(file_path)
        text_content = []

        # Try to extract text from BodyText streams
        for stream_path in ole.listdir():
            if 'BodyText' in stream_path:
                try:
                    data = ole.openstream(stream_path).read()
                    # HWP files may use compression
                    if data[:4] == b'HWP5':
                        # Try to decompress if compressed
                        try:
                            data = zlib.decompress(data[4:])
                        except:
                            pass

                    # Extract readable text (basic approach)
                    text = data.decode('utf-16-le', errors='ignore')
                    cleaned_text = ''.join(char for char in text if char.isprintable())
                    if cleaned_text.strip():
                        text_content.append(cleaned_text)
                except:
                    continue

        ole.close()
        return '\n\n'.join(text_content) if text_content else "Unable to extract text from HWP file"

    def supports(self, file_path: str) -> bool:
        """Check if file is a HWP.

        Args:
            file_path: Path to check

        Returns:
            True if file has HWP extension
        """
        path = Path(file_path)
        return path.suffix.lower() == '.hwp'