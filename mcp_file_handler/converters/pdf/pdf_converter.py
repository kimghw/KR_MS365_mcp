"""PDF to text converter."""

from pathlib import Path
from typing import Optional, Dict, Any
import logging

from ...base_converter import BaseConverter
from ...request_scope import scope_work_dir
from ..image.ocr_converter import ocr_image

logger = logging.getLogger(__name__)


class PDFConverter(BaseConverter):
    """Convert PDF files to text."""

    def convert(self, file_path: str) -> str:
        """Convert PDF file to text.

        Args:
            file_path: Path to the PDF file

        Returns:
            Extracted text content
        """
        if not self.supports(file_path):
            raise ValueError(f"File {file_path} is not a PDF file")

        try:
            import pdfplumber

            text_content = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_content.append(page_text)

            return '\n\n'.join(text_content)

        except ImportError:
            logger.error("pdfplumber not installed. Install with: pip install pdfplumber")
            raise
        except Exception as e:
            logger.error("Error converting PDF: %s", type(e).__name__)
            raise

    def supports(self, file_path: str) -> bool:
        """Check if file is a PDF.

        Args:
            file_path: Path to check

        Returns:
            True if file has PDF extension
        """
        path = Path(file_path)
        return path.suffix.lower() == '.pdf'

    def convert_with_ocr(self, file_path: str) -> str:
        """Convert PDF with OCR for scanned documents.

        Args:
            file_path: Path to the PDF file

        Returns:
            OCR extracted text content
        """
        # mode 1: 페이지 이미지·OCR 임시파일은 요청 작업 디렉터리에만 (없으면 missing_principal)
        work_dir = scope_work_dir()

        try:
            import pdf2image
            import pytesseract  # noqa: F401 - 설치 여부 확인
            from PIL import Image  # noqa: F401

            # Convert PDF to images
            if work_dir is not None:
                images = pdf2image.convert_from_path(file_path, output_folder=str(work_dir))
            else:
                images = pdf2image.convert_from_path(file_path)

            # Extract text from each image using OCR
            text_content = []
            for i, image in enumerate(images):
                text = ocr_image(image, lang=self.config.get('ocr_lang', 'eng'))
                if text.strip():
                    text_content.append(f"--- Page {i+1} ---\n{text}")

            return '\n\n'.join(text_content)

        except ImportError as e:
            logger.error("Missing OCR dependencies: %s", type(e).__name__)
            logger.info("Install with: pip install pdf2image pytesseract pillow")
            raise
        except Exception as e:
            logger.error("Error in PDF OCR conversion: %s", type(e).__name__)
            raise