# /setup_ms365 운영 함정 · 보안 주의

## 보안 주의

- **`.env` 내용을 채팅에 출력 금지** — Client Secret 평문 노출. 라인 수만 확인.
- **`.env`, `.env.bak.*` 는 `.gitignore` 등재 확인** — 실수 커밋 방지.
- **입력받은 자격증명을 memory 시스템에 저장 금지** — 영구화는 `.env` 한 곳만.
- **`auth.db` 는 평문 SQLite** — 디스크 권한으로만 보호되므로 공유 머신에 두지 말 것.

## 운영 함정

### 등록 vs 실행

- **HTTP (Claude Code)**: 등록만 함, spawn 안 함 — Claude Code 는 외부 서버에 붙기만 하므로 `/setup_ms365 start` (또는 `/port_manager`) 로 별도 기동 필요.
- **STDIO (Claude Desktop)**: 등록하면 Desktop 이 자동 spawn. 별도 기동 불필요. **Desktop 재시작은 필수**.

### 포트 점유

- 이미 떠있는 서버는 `start` 가 재시작하지 않음 (skip).
- 강제 재시작을 원하면 `/setup_ms365 restart <server>` 또는 `stop` 후 `start`.

### 로그 위치

- `/tmp/mcp_{name}.log` (Git Bash MSYS 경로, 실제로는 Windows `%TEMP%`).
- 실패한 서버는 `tail -20 /tmp/mcp_{name}.log` 로 확인.

### 멱등성 / 재실행 안전

- `.venv` 는 지우고 다시 만들지 않는다 — `uv sync --frozen` 을 다시 돌리면 잠금과 어긋난 것만 맞춘다 (이미 맞으면 하는 일이 없다).
- 등록은 read-modify-write — 같은 서버 여러 번 호출해도 idempotent.

### `--frozen` 을 빼면 잠금이 다시 풀린다

- `uv sync` 를 `--frozen` 없이 돌리면 uv 가 `uv.lock` 을 **다시 풀어 갱신한다.** 검증된 조합이 조용히 바뀌고 잠금 파일이 수정된 채 남는다. 셋업·검증에서는 항상 붙인다.
- `uv sync --frozen` 이 잠금 불일치로 실패하면 `--frozen` 을 떼서 넘기지 말고 `uv lock` 으로 갱신한 뒤 그 변경을 커밋한다 — 의존성은 **의도했을 때만** 움직여야 한다.
- 잠금 없이 최신본을 받으면 어떻게 되는지는 이미 겪었다: `mcp` 2.x 가 깔려 `Server.list_tools` 가 사라지면서 6개 서버가 전부 기동에 실패했다(2026-09-16). `pyproject.toml` 이 `mcp>=1.29,<2` 로 막아 둔 이유다.
- `requirements.txt` 는 `uv export` 산출물이라 손으로 고쳐도 다음 export 에 덮인다. 의존성 변경은 `pyproject.toml`(`uv add`)에서만 한다.
- `venv/`(전환 전 이름)가 남아 있으면 `verify_setup.py` 가 경고한다. 인정은 하되 새로 만들 때는 항상 `.venv` 다.

### Claude Desktop 재시작 필수

- Config 변경(`register_claude_desktop.py`) 후 Desktop 을 끄고 다시 켜야 새 MCP 가 보임.

### Claude Code 세션 재시작 필수

- `register_claude_code.py` 실행 후엔 **새 Claude Code 세션** 에서만 등록된 MCP 가 보임.

### Windows 포트 5000 (콜백) 와 Hyper-V 충돌

Windows 10/11 의 winnat/Hyper-V 동적 예약 범위에 5000 이 포함되는 경우가 있어 콜백 서버 바인딩이 실패할 수 있다.

회피:
1. `netsh int ipv4 show excludedportrange protocol=tcp` 로 예약 범위 확인.
2. Azure Portal 에서 앱 Redirect URI 를 다른 포트(예: 53682)로 변경.
3. `.env` 의 `AZURE_REDIRECT_URI` 도 동일하게 변경.

### MCP_SERVER_PORT 환경변수 우선

각 `server_stream.py` 는 `MCP_SERVER_PORT` 가 있으면 기본 포트(5001~5008) 대신 그 값을 사용. CI / 멀티 인스턴스 / 충돌 회피용.

### Cloudflare tunnel

이전 운영에서 cloudflare tunnel 이 `outlook → 8001` 로 매핑돼 있었다면, 포트 5001 으로 변경된 후엔 cloudflare 측 ingress 도 갱신해야 외부 접속이 동작한다. `cloudflare/reset-tunnel.sh` 참조.
