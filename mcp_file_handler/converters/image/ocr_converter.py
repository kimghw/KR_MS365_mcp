"""Image to text converter using OCR.

임시파일 정책 (spec/spec_멀티유저.md ②-2.5, ②-7.4 규칙 9):

- mode 1 에서는 OCR 이 만드는 모든 임시파일(전처리 이미지·tesseract 입력/출력)을 **요청
  작업 디렉터리**(`request_scope.scope_work_dir()` = `files/tmp/<request_id>/`) 안에만
  만든다. pytesseract 는 출력 파일을 시스템 temp 에 만들기 때문에(디렉터리 지정 불가)
  mode 1 은 tesseract 를 직접 실행해 결과를 stdout 으로 받고, 프로세스의 TEMP/TMP 도
  요청 디렉터리로 돌린다. 요청 scope 가 없으면 실패한다 — 시스템 temp 로 새지 않는다.
- mode 0 은 기존 pytesseract 경로를 그대로 쓴다.

로그에는 파일 경로와 예외 원문을 싣지 않는다.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from mcp_common.secure_files import create_exclusive
from mcp_common.security_policy import multi_user_enabled

from ...base_converter import BaseConverter
from ...request_scope import scope_work_dir

logger = logging.getLogger(__name__)

#: tesseract 1회 실행 제한(초)
OCR_TIMEOUT_SECONDS = 120


def _tesseract_cmd() -> str:
    try:
        import pytesseract

        return pytesseract.pytesseract.tesseract_cmd
    except (ImportError, AttributeError):
        return 'tesseract'


def ocr_image(image: Any, lang: str = 'eng') -> str:
    """PIL 이미지 → 텍스트. mode 1 은 임시파일을 요청 디렉터리에만 만든다."""
    if not multi_user_enabled():
        import pytesseract

        return pytesseract.image_to_string(image, lang=lang)

    work_dir = scope_work_dir()  # 없으면 missing_principal — 시스템 temp 로 대체하지 않는다
    source, handle = create_exclusive(Path(work_dir), 'ocr_input.png', root=Path(work_dir))
    with handle:
        image.save(handle, format='PNG')
    env = dict(os.environ, TEMP=str(work_dir), TMP=str(work_dir), TMPDIR=str(work_dir))
    try:
        proc = subprocess.run(
            [_tesseract_cmd(), str(source), 'stdout', '-l', lang],
            capture_output=True,
            cwd=str(work_dir),
            env=env,
            timeout=OCR_TIMEOUT_SECONDS,
            check=False,
        )
    finally:
        try:
            source.unlink()
        except OSError:
            pass
    if proc.returncode != 0:
        # stderr 원문(경로가 섞일 수 있음)은 싣지 않는다
        raise RuntimeError(f"tesseract failed (exit {proc.returncode})")
    return proc.stdout.decode('utf-8', errors='replace')


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
            raise ValueError("File is not a supported image format")

        try:
            import pytesseract  # noqa: F401 - 설치 여부 확인 (mode 1 도 tesseract_cmd 를 쓴다)
            from PIL import Image

            # Get OCR language from config, default to English
            lang = self.config.get('ocr_lang', 'eng')

            # Open and process image (with 로 닫아야 Windows 에서 요청 디렉터리 정리가 된다)
            with Image.open(file_path) as image:
                text = ocr_image(image, lang=lang)

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
            logger.error("Error in OCR conversion: %s", type(e).__name__)
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

    def preprocess_image(self, file_path: str, work_dir: Optional[Path] = None) -> Optional[str]:
        """Preprocess image for better OCR results.

        Args:
            file_path: Path to the image file
            work_dir: 결과를 둘 디렉터리. 없으면 요청 작업 디렉터리(mode 1 필수),
                mode 0 에서 그것도 없으면 시스템 temp(기존 동작).

        Returns:
            Path to preprocessed image or None
        """
        # 디렉터리 결정은 try 밖에서 — mode 1 의 scope 누락(missing_principal)을 삼키지 않는다
        directory = Path(work_dir) if work_dir is not None else scope_work_dir()

        try:
            from PIL import Image, ImageEnhance, ImageFilter

            with Image.open(file_path) as source:
                image = source

                # Convert to grayscale
                if image.mode != 'L':
                    image = image.convert('L')

                # Enhance contrast
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(2.0)

                # Apply sharpening filter
                image = image.filter(ImageFilter.SHARPEN)

                if directory is None:
                    # mode 0 기존 동작
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        image.save(tmp.name)
                        return tmp.name

                path, handle = create_exclusive(directory, 'ocr_preprocessed.png', root=directory)
                with handle:
                    image.save(handle, format='PNG')
                return str(path)

        except Exception as e:
            logger.warning("Image preprocessing failed: %s", type(e).__name__)
            return None
