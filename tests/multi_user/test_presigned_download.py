"""G02 — Graph 가 준 사전 서명 다운로드 URL 에는 Graph bearer 를 붙이지 않는다 (②-7.5, ②-10 G02).

FileHandler `convert_onedrive_to_text` 는 `requests` 로 `/shares/.../driveItem` → `/me/drive/items/{id}/content`
(302) → 사전 서명 URL 순서로 간다. 마지막 요청에 Authorization 이 없어야 하고, Graph 요청은 호출자 토큰
으로만, 받은 파일은 호출자 `files/` 아래에만 생긴다.
"""

from mcp_common.user_paths import paths_for
from tests.multi_user.harness import GRAPH_HOST, FakeHttpResponse, contains_bytes

PAYLOAD = b"PK-ALICE-DOWNLOADED-BYTES"


def test_presigned_download_gets_no_bearer_and_lands_in_callers_files(mu, alice, bob):
    item = {"id": "ITEM1", "name": "doc.docx", "file": {"mimeType": "application/octet-stream"}, "size": len(PAYLOAD)}
    mu.graph.on("GET", r"/shares/.*/driveItem$", item)
    mu.graph.on("GET", r"/me/drive/items/ITEM1$", item)
    mu.graph.on("GET", r"/me/drive/items/ITEM1/content$",
                FakeHttpResponse(302, None, headers={"Location": "https://download.sharepoint.example/dl?tempauth=t0k"}))
    mu.graph.on("GET", r"/dl$", FakeHttpResponse(200, None, body=PAYLOAD))

    with mu.client("file_handler") as c:
        result = c.call(alice.key, "convert_onedrive_to_text",
                        {"url": "https://contoso-my.sharepoint.com/:w:/g/personal/alice/EXyz"})
    # 변환 라이브러리 유무와 무관하게 HTTP 경로만 본다
    assert str(mu.root) not in result.text

    graph = [call for call in mu.graph.calls if call.host == GRAPH_HOST]
    presigned = [call for call in mu.graph.calls if call.host != GRAPH_HOST]
    assert graph and presigned, [c.url for c in mu.graph.calls]
    for call in graph:
        assert mu.graph.owner(call) == alice.account
        assert call.principal_key == alice.user_key
    for call in presigned:
        assert call.authorization is None, "사전 서명 URL 에 Graph bearer 가 붙었다"
    for path in contains_bytes(mu.root, PAYLOAD):
        assert str(paths_for(alice.user_key).files) in str(path), path
