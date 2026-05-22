"""
OneNote Agent - AI 기반 페이지 요약/검색
HTML 파싱, Claude Code SDK 호출, 요약/키워드 추출, 관련 페이지 검색
"""

import os
import re
import hashlib
import asyncio
import logging
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import yaml

from .graph_onenote_client import GraphOneNoteClient
from .onenote_db_service import OneNoteDBService

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "summarize_config.yaml",
)


# ============================================================================
# HTML 파싱
# ============================================================================

@dataclass
class Paragraph:
    """OneNote HTML에서 추출한 단락"""
    index: int
    text: str
    data_id: Optional[str] = None


class OneNoteHTMLParser(HTMLParser):
    """
    OneNote 페이지 HTML에서 단락을 추출하는 파서.
    <p>, <h1>~<h6>, <li> 태그를 단락으로 처리.
    """

    def __init__(self):
        super().__init__()
        self._paragraphs: List[Paragraph] = []
        self._current_text = ""
        self._current_data_id = None
        self._in_paragraph = False
        self._in_body = False
        self._para_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"}
        self._skip_tags = {"script", "style", "head"}
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "body":
            self._in_body = True
            return

        if tag in self._skip_tags:
            self._skip_depth += 1
            return

        if self._in_body and tag in self._para_tags and self._skip_depth == 0:
            self._in_paragraph = True
            self._current_text = ""
            self._current_data_id = attrs_dict.get("data-id")

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
            return

        if tag == "body":
            self._in_body = False
            return

        if self._in_paragraph and tag in self._para_tags:
            text = self._current_text.strip()
            if text:
                self._paragraphs.append(Paragraph(
                    index=len(self._paragraphs),
                    text=text,
                    data_id=self._current_data_id,
                ))
            self._in_paragraph = False
            self._current_text = ""

    def handle_data(self, data):
        if self._in_paragraph and self._skip_depth == 0:
            self._current_text += data

    def get_paragraphs(self) -> List[Paragraph]:
        return self._paragraphs


def parse_html_to_paragraphs(html_content: str) -> List[Paragraph]:
    """OneNote HTML을 단락 리스트로 파싱"""
    parser = OneNoteHTMLParser()
    parser.feed(html_content)
    return parser.get_paragraphs()


def html_to_plain_text(html_content: str) -> str:
    """HTML을 평문 텍스트로 변환"""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def compute_content_hash(html_content: str) -> str:
    """콘텐츠 변경 감지용 SHA256 해시"""
    return hashlib.sha256(html_content.encode('utf-8')).hexdigest()


# ============================================================================
# 설정
# ============================================================================

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """YAML 설정 파일 로드"""
    path = config_path or _DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        logger.warning(f"Config file not found: {path}, using defaults")
        return _default_config()

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _default_config() -> Dict[str, Any]:
    """기본 설정 (fallback)"""
    return {
        "summarization": {
            "page_summary": {
                "max_length": 500,
                "prompt": "다음 내용을 500자 이내로 요약해 주세요.\n\n페이지 제목: {page_title}\n\n{page_content}\n\n요약:",
            },
            "paragraph_summary": {
                "max_length": 200,
                "prompt": "다음 문단을 200자 이내로 요약해 주세요.\n\n{paragraph_text}\n\n요약:",
            },
            "keyword_extraction": {
                "count": 10,
                "prompt": "다음 내용에서 키워드를 {keyword_count}개 추출해 주세요. 쉼표로 구분.\n\n{page_title}\n\n{page_content}\n\n키워드:",
            },
        },
        "claude_sdk": {
            "model": "claude-sonnet-4-5-20250929",
            "max_turns": 1,
            "allowed_tools": [],
        },
    }


# ============================================================================
# Claude Code SDK
# ============================================================================

def is_sdk_available() -> bool:
    """Claude Code SDK 사용 가능 여부 확인 (현재 Claude Code 세션 기반)"""
    try:
        import claude_code_sdk  # noqa: F401
    except ImportError:
        return False
    return True


async def _call_claude_sdk(prompt: str, config: Dict[str, Any]) -> str:
    """Claude Code SDK로 프롬프트 전송 후 텍스트 응답 반환. SDK 미설치 시 빈 문자열."""
    try:
        from claude_code_sdk import query, ClaudeCodeOptions, AssistantMessage, TextBlock
    except ImportError:
        logger.debug("claude_code_sdk not installed, skipping")
        return ""

    sdk_config = config.get("claude_sdk", {})

    options = ClaudeCodeOptions(
        allowed_tools=sdk_config.get("allowed_tools", []),
        max_turns=sdk_config.get("max_turns", 1),
        model=sdk_config.get("model"),
    )

    try:
        response_texts = []
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_texts.append(block.text)
        return "\n".join(response_texts).strip()
    except Exception as e:
        logger.warning(f"Claude SDK 호출 실패: {e}")
        return ""


# ============================================================================
# 요약 파이프라인
# ============================================================================

async def _run_summarize(
    html_content: str,
    page_title: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    전체 요약 파이프라인: 페이지 요약 + 키워드 추출 (SDK 호출 2회, 병렬)

    Returns:
        {"summary": str, "keywords": [str, ...], "content_hash": str}
    """
    if config is None:
        config = load_config()

    summarization_config = config.get("summarization", {})

    # 1. HTML → 평문 변환 + 해시
    plain_text = html_to_plain_text(html_content)
    content_hash = compute_content_hash(html_content)

    # 2. 전체 페이지 요약 + 키워드 추출 (병렬 SDK 호출)
    page_summary_config = summarization_config.get("page_summary", {})
    page_prompt = page_summary_config.get("prompt", "").format(
        page_title=page_title,
        page_content=plain_text[:8000],
    )

    keyword_config = summarization_config.get("keyword_extraction", {})
    keyword_count = keyword_config.get("count", 10)
    keyword_prompt = keyword_config.get("prompt", "").format(
        page_title=page_title,
        page_content=plain_text[:8000],
        keyword_count=keyword_count,
    )

    summary_raw, keywords_raw = await asyncio.gather(
        _call_claude_sdk(page_prompt, config),
        _call_claude_sdk(keyword_prompt, config),
    )

    max_length = page_summary_config.get("max_length", 500)
    summary = summary_raw[:max_length]
    keywords = [kw.strip() for kw in keywords_raw.split(",") if kw.strip()][:keyword_count]

    return {
        "summary": summary,
        "keywords": keywords,
        "content_hash": content_hash,
    }


# ============================================================================
# OneNoteAgent 클래스
# ============================================================================

class OneNoteAgent:
    """
    AI 기반 OneNote 페이지 분석 에이전트

    - 페이지 요약 생성 (Claude Code SDK)
    - 키워드 추출
    - 관련 페이지 검색
    """

    def __init__(
        self,
        client: GraphOneNoteClient,
        db_service: OneNoteDBService,
    ):
        self._client = client
        self._db_service = db_service

    async def summarize_page(
        self,
        user_email: str,
        page_id: str,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        페이지 요약 생성/갱신

        Args:
            user_email: 사용자 이메일
            page_id: 페이지 ID
            force_refresh: True이면 캐시 무시하고 재생성

        Returns:
            요약 결과 (summary, keywords, cached)
        """
        if not is_sdk_available():
            return {
                "success": False,
                "skipped": True,
                "message": "Claude Code SDK가 설치되지 않았습니다.",
            }

        # 1. 페이지 HTML 가져오기
        content_result = await self._client.get_page_content(page_id, user_email)
        if not content_result.get("success"):
            return {
                "success": False,
                "error": content_result.get("error", "페이지 내용 조회 실패"),
            }

        html_content = content_result.get("content", "")
        page_title = content_result.get("title", "")

        # 2. 콘텐츠 해시로 변경 감지
        content_hash = compute_content_hash(html_content)

        if not force_refresh:
            existing = self._db_service.get_summary(page_id)
            if existing and existing.get("content_hash") == content_hash:
                return {
                    "success": True,
                    "cached": True,
                    "page_id": page_id,
                    "page_title": page_title,
                    "summary": existing["summary"],
                    "keywords": existing.get("keywords", []),
                    "content_hash": content_hash,
                    "summarized_at": existing.get("summarized_at"),
                }

        # 3. AI 요약 실행
        config = load_config()
        summary_result = await _run_summarize(html_content, page_title, config)

        # 4. DB 저장
        self._db_service.save_summary(
            page_id=page_id,
            user_id=user_email,
            page_title=page_title,
            summary=summary_result["summary"],
            paragraph_summaries=[],
            keywords=summary_result["keywords"],
            content_hash=summary_result["content_hash"],
        )

        return {
            "success": True,
            "cached": False,
            "page_id": page_id,
            "page_title": page_title,
            "summary": summary_result["summary"],
            "keywords": summary_result["keywords"],
            "content_hash": summary_result["content_hash"],
        }

    async def get_page_summary(
        self,
        user_email: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """저장된 페이지 요약 조회"""
        summary = self._db_service.get_summary(page_id)
        if summary:
            return {"success": True, **summary}
        return {"success": False, "message": f"페이지 '{page_id}'의 요약이 없습니다."}

    async def list_summarized_pages(
        self,
        user_email: str,
    ) -> Dict[str, Any]:
        """요약된 페이지 목록 조회"""
        summaries = self._db_service.list_summaries(user_email)
        return {
            "success": True,
            "pages": summaries,
            "count": len(summaries),
        }

    async def search_pages(
        self,
        user_email: str,
        query: str,
        section_id: Optional[str] = None,
        concurrency: int = 5,
    ) -> Dict[str, Any]:
        """
        섹션 내 페이지를 병렬로 순회하며 질의와 관련된 페이지를 찾아 요약 반환

        Args:
            user_email: 사용자 이메일
            query: 검색 질의 (예: "디지털트윈 관련 내용")
            section_id: 섹션 ID (없으면 전체 페이지 대상)
            concurrency: 동시 처리 수 (기본 5)

        Returns:
            관련 페이지 목록과 요약
        """
        if not is_sdk_available():
            return {
                "success": False,
                "skipped": True,
                "message": "Claude Code SDK가 설치되지 않았습니다.",
            }

        # 1. 페이지 목록 조회
        pages_result = await self._client.list_pages(
            user_email, section_id=section_id
        )
        if not pages_result.get("success"):
            return {
                "success": False,
                "error": pages_result.get("error", "페이지 목록 조회 실패"),
            }

        pages = pages_result.get("pages", [])
        if not pages:
            return {
                "success": True,
                "results": [],
                "count": 0,
                "message": "페이지가 없습니다.",
            }

        config = load_config()

        # 2. 각 페이지의 콘텐츠를 가져와서 관련성 판단 + 요약 (세마포어로 동시성 제한)
        semaphore = asyncio.Semaphore(concurrency)

        async def _analyze_page(
            page: Dict[str, Any],
        ) -> Optional[Dict[str, Any]]:
            page_id = page.get("id")
            page_title = page.get("title", "")

            async with semaphore:
                content_result = await self._client.get_page_content(
                    page_id, user_email
                )
                if not content_result.get("success"):
                    return None

                html_content = content_result.get("content", "")
                plain_text = html_to_plain_text(html_content)

                if not plain_text or len(plain_text.strip()) < 30:
                    return None

                prompt = (
                    f"다음 페이지 내용이 질의와 관련이 있는지 판단하고, "
                    f"관련이 있으면 핵심 내용을 3줄 이내로 요약해 주세요.\n\n"
                    f"[질의]\n{query}\n\n"
                    f"[페이지 제목]\n{page_title}\n\n"
                    f"[페이지 내용]\n{plain_text[:6000]}\n\n"
                    f"반드시 아래 형식으로만 응답하세요:\n"
                    f"관련여부: 예 또는 아니오\n"
                    f"요약: (관련이 있는 경우만 요약 작성)\n"
                )

                response = await _call_claude_sdk(prompt, config)
                if not response:
                    return None

                # 응답 파싱
                lines = response.strip().split("\n")
                is_relevant = False
                summary = ""

                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped.startswith("관련여부:"):
                        value = line_stripped.replace("관련여부:", "").strip()
                        is_relevant = (
                            "예" in value or "yes" in value.lower()
                        )
                    elif line_stripped.startswith("요약:"):
                        summary = line_stripped.replace("요약:", "").strip()

                # 요약이 여러 줄일 수 있음
                if is_relevant and not summary:
                    summary_lines = []
                    found_summary = False
                    for line in lines:
                        if line.strip().startswith("요약:"):
                            found_summary = True
                            rest = line.strip().replace("요약:", "").strip()
                            if rest:
                                summary_lines.append(rest)
                        elif found_summary:
                            summary_lines.append(line.strip())
                    summary = " ".join(summary_lines).strip()

                if is_relevant:
                    return {
                        "page_id": page_id,
                        "page_title": page_title,
                        "summary": summary,
                        "web_url": page.get("web_url"),
                    }

                return None

        # 3. 전체 페이지 병렬 분석
        tasks = [_analyze_page(page) for page in pages]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. 관련 페이지만 필터링
        relevant_pages = []
        errors = 0
        for r in results:
            if isinstance(r, Exception):
                errors += 1
                logger.warning(f"페이지 분석 오류: {r}")
            elif r is not None:
                relevant_pages.append(r)

        return {
            "success": True,
            "query": query,
            "results": relevant_pages,
            "count": len(relevant_pages),
            "total_pages_scanned": len(pages),
            "errors": errors,
        }

    async def summarize_change(
        self,
        page_title: str,
        action: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        편집 내용을 AI로 요약 (SDK 1회 호출)

        Args:
            page_title: 페이지 제목
            action: 편집 액션 (append, replace 등)
            content: 편집된 HTML 내용

        Returns:
            {"change_summary": str, "change_keywords": [str, ...]}
        """
        if not is_sdk_available():
            return {"change_summary": "", "change_keywords": []}

        plain_text = html_to_plain_text(content)
        if not plain_text or len(plain_text.strip()) < 5:
            return {
                "change_summary": f"{action} 작업 수행",
                "change_keywords": [],
            }

        config = load_config()
        prompt = (
            f"다음은 OneNote 페이지 편집 기록입니다.\n\n"
            f"[페이지 제목] {page_title}\n"
            f"[편집 유형] {action}\n"
            f"[편집 내용]\n{plain_text[:3000]}\n\n"
            f"반드시 아래 형식으로만 응답하세요:\n"
            f"요약: (이번 편집에서 무엇을 변경했는지 1줄 요약)\n"
            f"키워드: (쉼표로 구분된 키워드 3~5개)\n"
        )

        response = await _call_claude_sdk(prompt, config)
        if not response:
            return {
                "change_summary": f"{action} 작업 수행",
                "change_keywords": [],
            }

        # 응답 파싱
        change_summary = ""
        change_keywords = []
        for line in response.strip().split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("요약:"):
                change_summary = line_stripped.replace("요약:", "").strip()
            elif line_stripped.startswith("키워드:"):
                kw_text = line_stripped.replace("키워드:", "").strip()
                change_keywords = [kw.strip() for kw in kw_text.split(",") if kw.strip()]

        return {
            "change_summary": change_summary or f"{action} 작업 수행",
            "change_keywords": change_keywords[:5],
        }
