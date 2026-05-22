"""
mail_attachment_converter.py 단위 테스트

테스트 대상:
    - PdfConverter
    - WordConverter
    - HwpConverter
    - ExcelConverter
    - PowerPointConverter
    - PlainTextConverter
    - ConversionPipeline
"""

import pytest
from pathlib import Path
from io import BytesIO

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mail_attachment_converter import (
    FileConverter,
    PdfConverter,
    WordConverter,
    HwpConverter,
    ExcelConverter,
    PowerPointConverter,
    PlainTextConverter,
    ConversionPipeline,
    get_conversion_pipeline
)


class TestPlainTextConverter:
    """PlainTextConverter 테스트"""

    def setup_method(self):
        self.converter = PlainTextConverter()

    def test_supported_extensions(self):
        """지원 확장자 확인"""
        extensions = self.converter.supported_extensions
        assert ".txt" in extensions
        assert ".csv" in extensions
        assert ".json" in extensions
        assert ".xml" in extensions
        assert ".md" in extensions

    def test_supports_txt(self):
        """TXT 확장자 지원 확인"""
        assert self.converter.supports(".txt") is True
        assert self.converter.supports(".TXT") is True

    def test_supports_csv(self):
        """CSV 확장자 지원 확인"""
        assert self.converter.supports(".csv") is True

    def test_not_supports_pdf(self):
        """PDF 확장자 미지원 확인"""
        assert self.converter.supports(".pdf") is False

    def test_convert_utf8(self, sample_txt_content):
        """UTF-8 텍스트 변환"""
        result = self.converter.convert(sample_txt_content, "test.txt")
        assert "This is a plain text file." in result
        assert "Line 2." in result

    def test_convert_korean(self):
        """한국어 텍스트 변환"""
        content = "안녕하세요. 테스트입니다.".encode("utf-8")
        result = self.converter.convert(content, "korean.txt")
        assert "안녕하세요" in result

    def test_convert_csv(self, sample_csv_content):
        """CSV 파일 변환"""
        result = self.converter.convert(sample_csv_content, "data.csv")
        assert "name,age,city" in result
        assert "Alice,30,Seoul" in result

    def test_convert_cp949(self):
        """CP949 인코딩 텍스트 변환"""
        content = "한글 테스트".encode("cp949")
        result = self.converter.convert(content, "korean_cp949.txt")
        assert "한글" in result

    def test_convert_fallback_encoding(self):
        """인코딩 실패 시 fallback"""
        # 잘못된 바이트 시퀀스
        content = b"\xff\xfe\x00\x01invalid"
        result = self.converter.convert(content, "broken.txt")
        # errors='replace'로 처리되어야 함
        assert result is not None


class TestConversionPipeline:
    """ConversionPipeline 테스트"""

    def setup_method(self):
        self.pipeline = ConversionPipeline()

    def test_get_supported_extensions(self):
        """지원 확장자 목록 조회"""
        extensions = self.pipeline.get_supported_extensions()
        assert ".pdf" in extensions
        assert ".docx" in extensions
        assert ".xlsx" in extensions
        assert ".txt" in extensions

    def test_can_convert_pdf(self):
        """PDF 변환 가능 여부"""
        assert self.pipeline.can_convert("document.pdf") is True
        assert self.pipeline.can_convert("DOCUMENT.PDF") is True

    def test_can_convert_docx(self):
        """DOCX 변환 가능 여부"""
        assert self.pipeline.can_convert("document.docx") is True

    def test_can_convert_txt(self):
        """TXT 변환 가능 여부"""
        assert self.pipeline.can_convert("file.txt") is True

    def test_cannot_convert_unknown(self):
        """알 수 없는 형식 변환 불가"""
        assert self.pipeline.can_convert("file.xyz") is False
        assert self.pipeline.can_convert("file.exe") is False

    def test_get_converter_txt(self):
        """TXT 파일 변환기 조회"""
        converter = self.pipeline.get_converter("file.txt")
        assert converter is not None
        assert isinstance(converter, PlainTextConverter)

    def test_get_converter_pdf(self):
        """PDF 파일 변환기 조회"""
        converter = self.pipeline.get_converter("file.pdf")
        assert converter is not None
        assert isinstance(converter, PdfConverter)

    def test_get_converter_none(self):
        """알 수 없는 형식 변환기 None"""
        converter = self.pipeline.get_converter("file.unknown")
        assert converter is None

    def test_convert_txt(self, sample_txt_content):
        """TXT 파일 변환"""
        text, error = self.pipeline.convert(sample_txt_content, "test.txt")
        assert text is not None
        assert error is None
        assert "This is a plain text file." in text

    def test_convert_unsupported(self):
        """지원하지 않는 형식 변환 실패"""
        text, error = self.pipeline.convert(b"data", "file.xyz")
        assert text is None
        assert error is not None
        assert "지원하지 않는" in error

    def test_convert_to_txt_filename(self):
        """TXT 파일명 변환"""
        assert self.pipeline.convert_to_txt_filename("document.pdf") == "document.txt"
        assert self.pipeline.convert_to_txt_filename("file.docx") == "file.txt"
        assert self.pipeline.convert_to_txt_filename("data.xlsx") == "data.txt"


class TestPdfConverter:
    """PdfConverter 테스트"""

    def setup_method(self):
        self.converter = PdfConverter()

    def test_supported_extensions(self):
        """지원 확장자 확인"""
        assert self.converter.supported_extensions == [".pdf"]

    def test_supports_pdf(self):
        """PDF 확장자 지원"""
        assert self.converter.supports(".pdf") is True
        assert self.converter.supports(".PDF") is True

    def test_not_supports_docx(self):
        """DOCX 확장자 미지원"""
        assert self.converter.supports(".docx") is False

    def test_convert_requires_pdfplumber(self, sample_pdf_content):
        """pdfplumber 없으면 ImportError"""
        # 실제 pdfplumber가 설치되어 있으면 이 테스트는 다른 결과 발생
        try:
            import pdfplumber
            # pdfplumber가 있으면 변환 시도 (실패할 수 있음 - 잘못된 PDF)
            try:
                self.converter.convert(sample_pdf_content, "test.pdf")
            except Exception:
                pass  # 잘못된 PDF이므로 에러 가능
        except ImportError:
            with pytest.raises(ImportError):
                self.converter.convert(sample_pdf_content, "test.pdf")


class TestWordConverter:
    """WordConverter 테스트"""

    def setup_method(self):
        self.converter = WordConverter()

    def test_supported_extensions(self):
        """지원 확장자 확인"""
        extensions = self.converter.supported_extensions
        assert ".docx" in extensions
        assert ".doc" in extensions

    def test_supports_docx(self):
        """DOCX 확장자 지원"""
        assert self.converter.supports(".docx") is True

    def test_doc_not_implemented(self):
        """.doc 파일 미지원 (NotImplementedError)"""
        with pytest.raises(NotImplementedError):
            self.converter.convert(b"doc content", "old_file.doc")


class TestExcelConverter:
    """ExcelConverter 테스트"""

    def setup_method(self):
        self.converter = ExcelConverter()

    def test_supported_extensions(self):
        """지원 확장자 확인"""
        extensions = self.converter.supported_extensions
        assert ".xlsx" in extensions
        assert ".xls" in extensions

    def test_xls_not_implemented(self):
        """.xls 파일 미지원 (NotImplementedError)"""
        with pytest.raises(NotImplementedError):
            self.converter.convert(b"xls content", "old_file.xls")


class TestPowerPointConverter:
    """PowerPointConverter 테스트"""

    def setup_method(self):
        self.converter = PowerPointConverter()

    def test_supported_extensions(self):
        """지원 확장자 확인"""
        extensions = self.converter.supported_extensions
        assert ".pptx" in extensions
        assert ".ppt" in extensions

    def test_ppt_not_implemented(self):
        """.ppt 파일 미지원 (NotImplementedError)"""
        with pytest.raises(NotImplementedError):
            self.converter.convert(b"ppt content", "old_file.ppt")


class TestHwpConverter:
    """HwpConverter 테스트"""

    def setup_method(self):
        self.converter = HwpConverter()

    def test_supported_extensions(self):
        """지원 확장자 확인"""
        extensions = self.converter.supported_extensions
        assert ".hwp" in extensions
        assert ".hwpx" in extensions

    def test_supports_hwp(self):
        """HWP 확장자 지원"""
        assert self.converter.supports(".hwp") is True
        assert self.converter.supports(".hwpx") is True

    def test_html_to_text(self):
        """HTML → 텍스트 변환"""
        html = "<html><body><p>Hello World</p><br/>Line 2</body></html>"
        result = self.converter._html_to_text(html)
        assert "Hello World" in result

    def test_html_to_text_entities(self):
        """HTML 엔티티 변환"""
        html = "&nbsp;&lt;tag&gt;&amp;test&quot;"
        result = self.converter._html_to_text(html)
        assert "<tag>" in result
        assert "&test" in result


class TestGetConversionPipeline:
    """get_conversion_pipeline 싱글톤 테스트"""

    def test_singleton(self):
        """싱글톤 인스턴스 확인"""
        pipeline1 = get_conversion_pipeline()
        pipeline2 = get_conversion_pipeline()
        assert pipeline1 is pipeline2

    def test_is_conversion_pipeline(self):
        """ConversionPipeline 타입 확인"""
        pipeline = get_conversion_pipeline()
        assert isinstance(pipeline, ConversionPipeline)
