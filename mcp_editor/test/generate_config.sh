#!/bin/bash
#
# generate_config.sh - editor_config.json 생성 스크립트
#
# 사용법:
#   ./generate_config.sh           # editor_config.json 생성
#   ./generate_config.sh --dry-run # 발견된 서버만 표시 (생성 안함)
#   ./generate_config.sh --clean   # 기존 config 삭제 후 새로 생성
#   ./generate_config.sh --help    # 도움말 표시
#

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 스크립트 위치 기준으로 경로 설정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_EDITOR_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$MCP_EDITOR_DIR")"

CONFIG_FILE="$MCP_EDITOR_DIR/editor_config.json"
GENERATOR_SCRIPT="$MCP_EDITOR_DIR/service_registry/config_generator.py"

# 함수: 도움말 표시
show_help() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  editor_config.json 생성 스크립트${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo "사용법:"
    echo "  $0 [옵션]"
    echo ""
    echo "옵션:"
    echo "  (없음)      editor_config.json 생성"
    echo "  --dry-run   발견된 서버만 표시 (파일 생성 안함)"
    echo "  --clean     기존 config 삭제 후 새로 생성"
    echo "  --show      현재 editor_config.json 내용 표시"
    echo "  --help      이 도움말 표시"
    echo ""
    echo "동작 방식:"
    echo "  1. 프로젝트 루트에서 @mcp_service 데코레이터/JSDoc 스캔"
    echo "  2. mcp_* 디렉토리 패턴 스캔"
    echo "  3. 발견된 서버로 editor_config.json 생성"
    echo ""
    echo "파일 위치:"
    echo "  프로젝트 루트: $PROJECT_ROOT"
    echo "  mcp_editor:    $MCP_EDITOR_DIR"
    echo "  출력 파일:     $CONFIG_FILE"
    echo ""
}

# 함수: 현재 config 표시
show_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        echo -e "${GREEN}현재 editor_config.json:${NC}"
        echo ""
        cat "$CONFIG_FILE" | python3 -m json.tool 2>/dev/null || cat "$CONFIG_FILE"
    else
        echo -e "${YELLOW}editor_config.json이 존재하지 않습니다.${NC}"
    fi
}

# 함수: dry-run 모드 (Python 스크립트의 스캔 부분만 실행)
dry_run() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  Dry Run: 서버 스캔 결과${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    python3 << 'PYTHON_SCRIPT'
import os
import sys
sys.path.insert(0, os.environ.get('MCP_EDITOR_DIR', '.'))

from service_registry.config_generator import (
    scan_codebase_for_servers,
    scan_mcp_directories
)

project_root = os.environ.get('PROJECT_ROOT', os.getcwd())

print("프로젝트 루트:", project_root)
print()

# 데코레이터/JSDoc 스캔
decorator_servers = scan_codebase_for_servers(project_root)
print(f"\n데코레이터/JSDoc에서 발견: {len(decorator_servers)}개")
for s in sorted(decorator_servers):
    print(f"  - {s}")

# 디렉토리 스캔
print(f"\nmcp_* 디렉토리 스캔:")
directory_servers = scan_mcp_directories(project_root)
print(f"\n디렉토리에서 발견: {len(directory_servers)}개")
for s in sorted(directory_servers):
    print(f"  - {s}")

# 합집합
all_servers = decorator_servers | directory_servers
print(f"\n{'='*40}")
print(f"총 발견된 서버: {len(all_servers)}개")
for s in sorted(all_servers):
    print(f"  - {s}")
PYTHON_SCRIPT
}

# 함수: config 생성
generate_config() {
    local clean_mode=$1

    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  editor_config.json 생성${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    # clean 모드일 경우 기존 파일 삭제
    if [[ "$clean_mode" == "true" && -f "$CONFIG_FILE" ]]; then
        echo -e "${YELLOW}기존 config 삭제 중...${NC}"
        rm -f "$CONFIG_FILE"
        rm -f "$CONFIG_FILE.backup"
        echo -e "${GREEN}삭제 완료${NC}"
        echo ""
    fi

    # Python 스크립트 실행
    cd "$MCP_EDITOR_DIR"
    python3 "$GENERATOR_SCRIPT"

    echo ""
    if [[ -f "$CONFIG_FILE" ]]; then
        echo -e "${GREEN}생성 완료!${NC}"
        echo ""
        echo "생성된 프로필:"
        python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print('\n'.join(f'  - {k} (port: {v.get(\"port\", \"N/A\")})' for k,v in c.items()))"
    else
        echo -e "${RED}생성 실패${NC}"
        exit 1
    fi
}

# 메인 로직
export PROJECT_ROOT
export MCP_EDITOR_DIR

case "${1:-}" in
    --help|-h)
        show_help
        ;;
    --dry-run|-n)
        dry_run
        ;;
    --show|-s)
        show_config
        ;;
    --clean|-c)
        generate_config "true"
        ;;
    "")
        generate_config "false"
        ;;
    *)
        echo -e "${RED}알 수 없는 옵션: $1${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac
