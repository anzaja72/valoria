from service.cpnu import ResultadoCPNU

from .conftest import RADICADO, WEB


def rpc(c, method, params=None, id_=1, headers=WEB):
    body = {"jsonrpc": "2.0", "method": method, "id": id_}
    if params is not None:
        body["params"] = params
    return c.post("/mcp", json=body, headers=headers)


def test_mcp_requiere_auth(make_client):
    c, _ = make_client()
    assert rpc(c, "initialize", headers={}).status_code == 401


def test_mcp_initialize_y_notificacion(make_client):
    c, _ = make_client()
    r = rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "t", "version": "1"}}).json()
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert "tools" in r["result"]["capabilities"]
    r2 = c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=WEB)
    assert r2.status_code == 202
    desconocida = rpc(c, "initialize", {"protocolVersion": "1999-01-01"}).json()
    assert desconocida["result"]["protocolVersion"] == "2025-11-25"


def test_mcp_tools_list(make_client):
    c, _ = make_client()
    tools = rpc(c, "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["consultar_estados", "consultar_proceso"]
    assert tools[0]["inputSchema"]["required"] == ["radicado"]
    assert tools[0]["annotations"]["readOnlyHint"] is True


def test_mcp_tools_call_proceso(make_client):
    c, fake = make_client()
    r = rpc(c, "tools/call", {"name": "consultar_proceso", "arguments": {"radicado": RADICADO}}).json()
    res = r["result"]
    assert res["isError"] is False
    assert res["structuredContent"]["status"] == "ok"
    assert "### Para el abogado" in res["content"][0]["text"]
    # la segunda llamada usa la misma cache que la API REST
    c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO})
    assert fake.llamadas == 1


def test_mcp_tools_call_error_portal(make_client):
    c, _ = make_client(ResultadoCPNU("error", error_code="portal_unavailable"))
    res = rpc(c, "tools/call", {"name": "consultar_proceso", "arguments": {"radicado": RADICADO}}).json()["result"]
    assert res["isError"] is True and "no está respondiendo" in res["content"][0]["text"]


def test_mcp_errores_jsonrpc(make_client):
    c, _ = make_client()
    assert rpc(c, "tools/call", {"name": "x", "arguments": {}}).json()["error"]["code"] == -32602
    assert rpc(c, "tools/call", {"name": "consultar_proceso", "arguments": {}}).json()["error"]["code"] == -32602
    assert rpc(c, "metodo/raro").json()["error"]["code"] == -32601
    assert c.post("/mcp", content=b"{no json", headers={**WEB, "Content-Type": "application/json"}).status_code == 400
    assert rpc(c, "ping").json()["result"] == {}
    assert c.get("/mcp", headers=WEB).status_code == 405


def test_mcp_lote(make_client):
    c, _ = make_client()
    r = c.post("/mcp", headers=WEB, json=[
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]).json()
    assert [x["id"] for x in r] == [1, 2]


def test_mcp_acepta_x_api_key(make_client):
    c, _ = make_client()
    assert rpc(c, "tools/list", headers={"X-API-Key": "web_test"}).status_code == 200
    assert rpc(c, "tools/list", headers={"X-API-Key": "otra"}).status_code == 401
