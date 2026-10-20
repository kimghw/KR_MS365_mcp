"""드라이브 경로의 `#` `%` 공백·검색어의 따옴표가 요청 URL 에서 잘리지 않는지 검증."""

from unittest.mock import AsyncMock

from mcp_onedrive.graph_onedrive_client import GraphOneDriveClient, _enc


def test_enc_escapes_fragment_percent_and_space():
    assert _enc("/Docs/report#v2 100%.txt") == "Docs/report%23v2%20100%25.txt"


async def test_delete_targets_the_encoded_path():
    c = GraphOneDriveClient(token_provider=object())
    c._make_request = AsyncMock(return_value={"success": True})
    await c.delete_file("u@x", "Docs/report#v2.txt")
    assert c._make_request.call_args.args[1] == "/me/drive/root:/Docs/report%23v2.txt"


async def test_search_escapes_single_quote():
    c = GraphOneDriveClient(token_provider=object())
    c._make_request = AsyncMock(return_value={"success": True, "data": {"value": []}})
    await c.list_files("u@x", search="it's")
    assert c._make_request.call_args.args[1] == "/me/drive/root/search(q='it%27%27s')?$top=50"
