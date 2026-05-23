# /ms365 시나리오 예시

SKILL.md 의 1~5단계 흐름을 실제 케이스에 매핑한 예시 5개.

## 첫 설치 — `/ms365`

```
1. 상태: 다 X (venv·.env·deps·등록 모두 없음)
2-A. unhealthy_common 감지 → "지금 셋업할까요?" 예
3-A-0a. 서버 → 6개 다
3-A-0b. 타겟 → Code + Desktop
3-A-1~3. Python 발견 → venv 생성 → pip install
3-A-4. .env 입력 → 작성
3-A-5-CC/CD. register_claude_code.py / register_claude_desktop.py 호출
4. server_stream.py 6개 백그라운드 실행 → health_check.py 확인
5. verify_setup.py 검증 표 출력
```

## 기존 환경 — 일부 누락 — `/ms365`

```
1. 상태: venv/deps/.env OK. teams 는 Code만, Desktop 누락. todo 는 둘 다 미등록
2-B. AskUserQuestion multiSelect:
     ☐ teams → Claude Desktop (STDIO)
     ☐ todo  → Claude Code (HTTP)
     ☐ todo  → Claude Desktop (STDIO)
   → 3개 다 체크 → 3-A-5만 부분 실행 (선택 기준으로 --servers 인자 구성)
2-C. 정지 서버 감지 (outlook 5001, todo 5006) → multiSelect 로 시작 선택 → 3-D-1
5. 검증 표
```

## 모두 정상 — `/ms365`

```
1. 상태: venv/deps/.env/토큰 OK, 6개 서버 모두 Code+Desktop 등록 + 포트 LISTEN
2-D. ✅ 모든 서버 정상 — 추가 작업 메뉴 (선택 안 하면 종료)
```

## 일부 서버 시작 — `/ms365 start outlook teams`

```
1. 상태 확인
3-D-1. start 모드:
   - 각 포트 점유 확인 후 nohup 으로 server_stream.py 백그라운드 기동
   - 3초 대기
   - health_check.py --servers outlook,teams
```

## 전체 중지 — `/ms365 stop all`

```
3-D-2. stop_server.py --servers all
       → 6개 포트 모두 Stop-Process
```

## 인증 점검 — `/ms365 check`

```
3-C-1. check_token.py
       → {"status":"valid","email":"..."} 또는 invalid_or_expired/no_user
3-C-2. LISTEN 중인 서버마다 streamable_http_probe.py 실행
       → compliant / partial / non-compliant
```
