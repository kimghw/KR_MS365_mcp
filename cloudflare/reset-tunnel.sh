#!/bin/bash

# Cloudflare Tunnel 전체 초기화 및 재설정 스크립트
# 사용법: sudo ./reset-tunnel.sh

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "Cloudflare Tunnel 전체 초기화"
echo "========================================"

# 1. 기존 터널 프로세스 종료
echo -e "\n${YELLOW}1. 기존 cloudflared 프로세스 종료${NC}"
pkill -f cloudflared 2>/dev/null && echo -e "${GREEN}✓ 프로세스 종료됨${NC}" || echo "실행 중인 프로세스 없음"
sleep 2

# 2. 기존 터널 삭제
echo -e "\n${YELLOW}2. 기존 터널 삭제${NC}"
TUNNELS=$(cloudflared tunnel list 2>/dev/null | tail -n +2 | awk '{print $2}')
for tunnel in $TUNNELS; do
    echo "터널 삭제 중: $tunnel"
    cloudflared tunnel cleanup $tunnel 2>/dev/null || true
    cloudflared tunnel delete $tunnel --force 2>/dev/null || echo "  - $tunnel 삭제 실패 (수동 삭제 필요)"
done
echo -e "${GREEN}✓ 터널 정리 완료${NC}"

# 3. 새 터널 생성
echo -e "\n${YELLOW}3. 새 터널 생성${NC}"
TUNNEL_NAME="mcp-outlook"
cloudflared tunnel create $TUNNEL_NAME
TUNNEL_ID=$(cloudflared tunnel list | grep $TUNNEL_NAME | awk '{print $1}')
echo -e "${GREEN}✓ 터널 생성 완료: $TUNNEL_NAME (ID: $TUNNEL_ID)${NC}"

# 4. 설정 파일 생성
echo -e "\n${YELLOW}4. 설정 파일 생성${NC}"
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml << EOF
tunnel: $TUNNEL_ID
credentials-file: $HOME/.cloudflared/$TUNNEL_ID.json

ingress:
  # MCP Outlook 서버 (포트 8001)
  - hostname: outlook.kimghw.org
    service: http://localhost:8001
    originRequest:
      noTLSVerify: false
      connectTimeout: 30s

  # API 서버 (포트 8000)
  - hostname: api.kimghw.org
    service: http://localhost:8000

  # 404 페이지
  - service: http_status:404
EOF
echo -e "${GREEN}✓ 설정 파일 생성: ~/.cloudflared/config.yml${NC}"

# 5. DNS 레코드 추가
echo -e "\n${YELLOW}5. DNS 레코드 추가${NC}"
cloudflared tunnel route dns $TUNNEL_NAME outlook.kimghw.org 2>/dev/null || echo "DNS 레코드가 이미 존재하거나 추가됨"
cloudflared tunnel route dns $TUNNEL_NAME api.kimghw.org 2>/dev/null || echo "DNS 레코드가 이미 존재하거나 추가됨"
echo -e "${GREEN}✓ DNS 설정 완료${NC}"

# 6. 터널 시작
echo -e "\n${YELLOW}6. 터널 시작${NC}"
echo -e "${GREEN}터널을 시작하려면 다음 명령어를 실행하세요:${NC}"
echo ""
echo "  cloudflared tunnel run $TUNNEL_NAME"
echo ""
echo -e "${YELLOW}또는 백그라운드 실행:${NC}"
echo "  nohup cloudflared tunnel run $TUNNEL_NAME > /var/log/cloudflared.log 2>&1 &"
echo ""
echo -e "${YELLOW}systemd 서비스로 설치:${NC}"
echo "  sudo cloudflared service install"
echo "  sudo systemctl start cloudflared"
echo ""
echo "========================================"
echo -e "${GREEN}설정 완료!${NC}"
echo "========================================"
echo ""
echo "URL: https://outlook.kimghw.org → localhost:8001"
echo "URL: https://api.kimghw.org → localhost:8000"
