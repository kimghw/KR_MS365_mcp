"""Image to text converter using OCR."""

from pathlib import Path
import logging
from typing import Optional

from ...base_converter import BaseConverter

logger = logging.getLogger(__name__)


class OCRConverter(BaseConverter):
    """Convert images to text using OCR."""

    def convert(self, file_path: str) -> str:
        """Convert image file to text using OCR.

        Args:
            file_path: Path to the image file

        Returns:
            OCR extracted text content
        """
        if not self.supports(file_path):
            raise ValueError(f"File {file_path} is not a supported image format")

        try:
            import pytesseract
            from PIL import Image

            # Open and process image
            image = Image.open(file_path)

            # Get OCR language from config, default to English
            lang = self.config.get('ocr_lang', 'eng')

            # Perform OCR
            text = pytesseract.image_to_string(image, lang=lang)

            # Clean up text
            text = text.strip()
            if not text:
                return "No text found in image"

            return text

        except ImportError:
            logger.error("pytesseract or Pillow not installed.")
            logger.info("Install with: pip install pytesseract pillow")
            logger.info("Also install tesseract-ocr system package")
            raise
        except Exception as e:
            logger.error(f"Error in OCR conversion of {file_path}: {e}")
            raise

    def supports(self, file_path: str) -> bool:
        """Check if file is a supported image format.

        Args:
            file_path: Path to check

        Returns:
            True if file has image extension
        """
        path = Path(file_path)
        supported_formats = [
            '.png', '.jpg', '.jpeg', '.gif', '.bmp',
            '.tiff', '.tif', '.webp', '.ico'
        ]
        return path.suffix.lower() in supported_formats

    def preprocess_image(self, file_path: str) -> Optional[str]:
        """Preprocess image for better OCR results.

        Args:
            file_path: Path to the image file

        Returns:
            Path to preprocessed image or None
        """
        try:
            from PIL import Image, ImageEnhance, ImageFilter
            import tempfile

            image = Image.open(file_path)

            # Convert to grayscale
            if image.mode != 'L':
                image = image.convert('L')

            # Enhance contrast
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)

            # Apply sharpening filter
            image = image.filter(ImageFilter.SHARPEN)

            # Save preprocessed image
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                image.save(tmp.name)
                return tmp.name

        except Exception as e:
            logger.warning(f"Image preprocessing failed: {e}")
            return None