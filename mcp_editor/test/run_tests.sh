#!/bin/bash
#
# Registry & Type Extractor 테스트 러너
#
# 사용법:
#   ./run_tests.sh          # 메뉴 표시
#   ./run_tests.sh 1        # Python 타입 추출 테스트
#   ./run_tests.sh all      # 전체 테스트
#

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# 스크립트 디렉토리
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 헤더 출력
print_header() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}     ${BOLD}Registry & Type Extractor 테스트${NC}                         ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# 메뉴 출력
print_menu() {
    echo -e "${YELLOW}테스트 모듈을 선택하세요:${NC}"
    echo ""
    echo -e "  ${BOLD}1)${NC} Python 타입 추출 테스트      ${BLUE}(extract_types.py)${NC}"
    echo -e "     └─ Pydantic BaseModel 클래스 추출 테스트"
    echo ""
    echo -e "  ${BOLD}2)${NC} JavaScript 타입 추출 테스트  ${BLUE}(extract_types_js.py)${NC}"
    echo -e "     └─ Sequelize 모델 추출 테스트"
    echo ""
    echo -e "  ${BOLD}3)${NC} MCP 서비스 스캐너 테스트     ${BLUE}(mcp_service_scanner.py)${NC}"
    echo -e "     └─ @mcp_service 데코레이터 스캔 테스트"
    echo ""
    echo -e "  ${BOLD}4)${NC} 서비스 레지스트리 테스트     ${BLUE}(service_registry.py)${NC}"
    echo -e "     └─ JSON 레지스트리 로딩 및 검증 테스트"
    echo ""
    echo -e "  ${BOLD}5)${NC} ${GREEN}전체 테스트 실행${NC}"
    echo -e "     └─ 모든 테스트 모듈 순차 실행"
    echo ""
    echo -e "  ${BOLD}q)${NC} 종료"
    echo ""
}

# 구분선 출력
print_separator() {
    echo -e "${CYAN}──────────────────────────────────────────────────────────────────${NC}"
}

# 테스트 실행 함수
run_test() {
    local test_file=$1
    local test_name=$2

    print_separator
    echo -e "${YELLOW}>>> ${test_name} 실행 중...${NC}"
    print_separator
    echo ""

    python3 "$test_file"
    local exit_code=$?

    echo ""
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✓ ${test_name} 완료${NC}"
    else
        echo -e "${RED}✗ ${test_name} 실패 (exit code: $exit_code)${NC}"
    fi

    return $exit_code
}

# 전체 테스트 실행
run_all_tests() {
    print_separator
    echo -e "${YELLOW}>>> 전체 테스트 실행${NC}"
    print_separator
    echo ""

    python3 run_all_tests.py
    return $?
}

# 결과 대기
wait_for_key() {
    echo ""
    echo -e "${BLUE}계속하려면 아무 키나 누르세요...${NC}"
    read -n 1 -s
}

# 메인 함수
main() {
    local choice=$1

    # 인자가 있으면 바로 실행
    if [ -n "$choice" ]; then
        case $choice in
            1)
                run_test "test_extract_types.py" "Python 타입 추출 테스트"
                ;;
            2)
                run_test "test_extract_types_js.py" "JavaScript 타입 추출 테스트"
                ;;
            3)
                run_test "test_mcp_service_scanner.py" "MCP 서비스 스캐너 테스트"
                ;;
            4)
                run_test "test_service_registry.py" "서비스 레지스트리 테스트"
                ;;
            5|all|a)
                run_all_tests
                ;;
            *)
                echo -e "${RED}잘못된 선택입니다: $choice${NC}"
                exit 1
                ;;
        esac
        exit $?
    fi

    # 대화형 메뉴
    while true; do
        clear
        print_header
        print_menu

        echo -n -e "${BOLD}선택 [1-5, q]: ${NC}"
        read -r choice

        case $choice in
            1)
                run_test "test_extract_types.py" "Python 타입 추출 테스트"
                wait_for_key
                ;;
            2)
                run_test "test_extract_types_js.py" "JavaScript 타입 추출 테스트"
                wait_for_key
                ;;
            3)
                run_test "test_mcp_service_scanner.py" "MCP 서비스 스캐너 테스트"
                wait_for_key
                ;;
            4)
                run_test "test_service_registry.py" "서비스 레지스트리 테스트"
                wait_for_key
                ;;
            5|a|A)
                run_all_tests
                wait_for_key
                ;;
            q|Q)
                echo ""
                echo -e "${GREEN}테스트를 종료합니다.${NC}"
                exit 0
                ;;
            *)
                echo -e "${RED}잘못된 선택입니다. 다시 시도하세요.${NC}"
                sleep 1
                ;;
        esac
    done
}

# 스크립트 실행
main "$1"
