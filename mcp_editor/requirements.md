# MCP Web Editor 설치 및 실행 가이드

## 시스템 요구사항

- Python 3.10 이상
- pip (Python 패키지 매니저)

## 패키지 설치

```bash
cd /home/kimghw/Connector_auth/mcp_editor
pip install -r requirements_web.txt
```

### 필수 패키지

| 패키지 | 버전 | 용도 |
|--------|------|------|
| Flask | 3.0.0 | 웹 서버 프레임워크 |
| flask-cors | 4.0.0 | CORS 지원 |
| psutil | >=5.9.0 | 프로세스 모니터링 |
| Jinja2 | (Flask 의존성) | 템플릿 엔진 |

### 선택 패키지 (서비스별)

```bash
# Outlook/Calendar 서비스 사용 시
pip install msal aiohttp

# JavaScript 프로젝트 타입 파싱 시 (선택)
pip install esprima
```

## 환경변수 설정

### MCP_EDITOR_ROOT (선택)

웹 에디터를 다른 위치에서 실행하거나 도커로 배포할 때 프로젝트 루트 경로를 지정합니다.

```bash
# 설정하지 않으면: mcp_editor/ 상위 폴더가 자동으로 ROOT_DIR
# 설정하면: 지정한 경로가 ROOT_DIR

export MCP_EDITOR_ROOT=/home/kimghw/Connector_auth
```

### MCP_EDITOR_CONFIG (선택)

editor_config.json 경로를 오버라이드합니다.

```bash
export MCP_EDITOR_CONFIG=/custom/path/editor_config.json
```

## 실행 방법

### 기본 실행 (현재 위치)

```bash
cd /home/kimghw/Connector_auth/mcp_editor/tool_editor_core
python -c "from app import run_app; run_app()"
```

또는:

```bash
cd /home/kimghw/Connector_auth/mcp_editor
python -m tool_editor_core.app
```

### 다른 위치에서 실행

```bash
# 프로젝트 루트 지정
export MCP_EDITOR_ROOT=/home/kimghw/Connector_auth

# 어디서든 실행 가능
python -m tool_editor_core.app
```

### 포트 지정

기본 포트는 `editor_config.json`의 첫 번째 프로필 설정을 따릅니다.

## 도커 실행

### Dockerfile 예시

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 웹 에디터만 복사
COPY mcp_editor/ /app/mcp_editor/

# 서비스 코드 복사 (필요한 것만)
COPY mcp_outlook/ /app/mcp_outlook/
COPY mcp_calendar/ /app/mcp_calendar/

# 패키지 설치
RUN pip install -r /app/mcp_editor/requirements_web.txt

# 환경변수 설정
ENV MCP_EDITOR_ROOT=/app

# 실행
WORKDIR /app/mcp_editor
CMD ["python", "-m", "tool_editor_core.app"]
```

### docker-compose.yml 예시

```yaml
version: '3.8'

services:
  mcp-editor:
    build: .
    ports:
      - "8091:8091"
    environment:
      - MCP_EDITOR_ROOT=/app
    volumes:
      # 개발 시 소스 마운트
      - ./mcp_outlook:/app/mcp_outlook
      - ./mcp_calendar:/app/mcp_calendar
      - ./mcp_editor:/app/mcp_editor
```

### 볼륨 마운트 필수 경로

| 경로 | 용도 |
|------|------|
| `mcp_editor/` | 웹 에디터 코드 |
| `mcp_{server}/` | 서비스 코드 (편집 대상) |

## 폴더 구조

```
{MCP_EDITOR_ROOT}/
├── mcp_editor/                    # 웹 에디터
│   ├── tool_editor_core/          # Flask 앱
│   ├── service_registry/          # 서비스 스캐너
│   ├── jinja/                     # 서버 템플릿
│   │   ├── python/
│   │   └── javascript/
│   ├── mcp_{server}/              # 프로필별 설정
│   │   ├── registry_{server}.json
│   │   └── tool_definition_templates.py
│   └── editor_config.json
├── mcp_outlook/                   # 서비스 코드
│   ├── outlook_service.py
│   └── mcp_server/
│       └── tool_definitions.py
└── mcp_calendar/
    └── ...
```

## 트러블슈팅

### ModuleNotFoundError

```bash
# PYTHONPATH에 mcp_editor 추가
export PYTHONPATH=/home/kimghw/Connector_auth/mcp_editor:$PYTHONPATH
```

### 서비스 코드를 찾을 수 없음

```bash
# MCP_EDITOR_ROOT가 올바르게 설정되었는지 확인
echo $MCP_EDITOR_ROOT
ls $MCP_EDITOR_ROOT/mcp_outlook  # 서비스 폴더 존재 확인
```

### editor_config.json 생성 실패

```bash
# 수동 생성
cd /home/kimghw/Connector_auth/mcp_editor/test
./generate_config.sh
```
