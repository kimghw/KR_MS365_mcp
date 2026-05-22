# MCP Editor

## 아키텍처 개요

### 초기화 단계 (Initialization Phase)
초기화 중에 생성되는 파일:
- **editor_config.json** - 웹 에디터의 설정 파일 (도구 정의 및 서버 설정 포함)
- **tool_definition_templates.py** - MCP 서버 코드 생성을 위한 템플릿 참조 파일 (참조용으로만 사용)

### 편집 단계 (Editing Phase)
편집 단계에서 생성/수정 가능한 파일:
- **tool_definition.py** - 실제 도구 구현을 정의 (파라미터 및 로직 포함)
- 특정 구현에 필요한 기타 MCP 서버 파일들

### 저장 단계 (Saving Phase)
저장 단계에서 생성되는 파일:
- **server.py** - 최종 MCP 서버 실행 파일 (도구 정의와 서버 로직이 통합된 완전한 서버 코드)