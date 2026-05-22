# Claude Code SDK 비동기 사용법

## 설치

```bash
pip install claude-code-sdk
```

- Python 3.10+
- `ANTHROPIC_API_KEY` 환경변수 필요

## 기본 사용법

```python
import asyncio
from claude_code_sdk import query, ClaudeCodeOptions

async def main():
    options = ClaudeCodeOptions(
        allowed_tools=["Read", "Grep", "Glob"],
        cwd="/작업/디렉토리",
    )

    async for message in query(prompt="파일 분석해줘", options=options):
        if hasattr(message, 'content'):
            for block in message.content:
                if hasattr(block, 'text'):
                    print(block.text)

asyncio.run(main())
```

## ClaudeCodeOptions 주요 옵션

| 옵션 | 타입 | 설명 |
|------|------|------|
| `allowed_tools` | `list[str]` | 허용할 도구 (`Read`, `Write`, `Bash`, `Glob`, `Grep` 등) |
| `disallowed_tools` | `list[str]` | 차단할 도구 |
| `permission_mode` | `str` | `"default"`, `"acceptEdits"`, `"bypassPermissions"` |
| `cwd` | `str` | 작업 디렉토리 |
| `max_turns` | `int` | 최대 턴 수 |
| `model` | `str` | 모델 지정 (예: `"claude-sonnet-4-5-20250929"`) |
| `system_prompt` | `str` | 커스텀 시스템 프롬프트 |

## 메시지 타입 처리

```python
from claude_code_sdk import AssistantMessage, TextBlock, ToolUseBlock, ResultMessage

async for message in query(prompt="...", options=options):
    # Agent 응답
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(f"응답: {block.text}")
            elif isinstance(block, ToolUseBlock):
                print(f"도구 사용: {block.name}")

    # 최종 결과 (비용, 소요시간)
    elif isinstance(message, ResultMessage):
        print(f"비용: ${message.total_cost_usd}")
        print(f"소요시간: {message.duration_ms}ms")
```

## 사용 가능한 도구 목록

| 도구 | 설명 |
|------|------|
| `Read` | 파일 읽기 |
| `Write` | 파일 생성 |
| `Edit` | 파일 수정 |
| `Bash` | 명령 실행 |
| `Glob` | 파일 패턴 검색 |
| `Grep` | 파일 내용 검색 |
| `WebSearch` | 웹 검색 |
| `WebFetch` | 웹 페이지 가져오기 |
| `Task` | 서브에이전트 호출 |
| `NotebookEdit` | Jupyter 노트북 편집 |

## 프로젝트 적용 예시 (agent/format_review.py)

```python
from claude_code_sdk import query, ClaudeCodeOptions

async def review_format(hwpx_paths, review_prompt):
    options = ClaudeCodeOptions(
        allowed_tools=["Read", "Grep", "Glob"],
        cwd=str(Path(hwpx_paths[0]).parent),
    )

    responses = []
    async for message in query(prompt=review_prompt, options=options):
        if hasattr(message, 'content'):
            for block in message.content:
                if hasattr(block, 'text'):
                    responses.append(block.text)

    return '\n'.join(responses)
```
