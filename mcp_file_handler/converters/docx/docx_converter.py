"""DOCX to text converter."""

from pathlib import Path
import logging

from ...base_converter import BaseConverter

logger = logging.getLogger(__name__)


class DOCXConverter(BaseConverter):
    """Convert Microsoft Word DOCX files to text."""

    def convert(self, file_path: str) -> str:
        """Convert DOCX file to text.

        Args:
            file_path: Path to the DOCX file

        Returns:
            Extracted text content
        """
        if not self.supports(file_path):
            raise ValueError(f"File {file_path} is not a DOCX file")

        try:
            from docx import Document

            doc = Document(file_path)
            text_content = []

            # Extract text from paragraphs
            for para in doc.paragraphs:
                if para.text.strip():
                    text_content.append(para.text)

            # Extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        if cell.text.strip():
                            row_text.append(cell.text.strip())
                    if row_text:
                        text_content.append(' | '.join(row_text))

            return '\n\n'.join(text_content)

        except ImportError:
            logger.error("python-docx not installed. Install with: pip install python-docx")
            raise
        except Exception as e:
            logger.error(f"Error converting DOCX {file_path}: {e}")
            raise

    def supports(self, file_path: str) -> bool:
        """Check if file is a DOCX.

        Args:
            file_path: Path to check

        Returns:
            True if file has DOCX extension
        """
        path = Path(file_path)
        return path.suffix.lower() in ['.docx', '.doc']