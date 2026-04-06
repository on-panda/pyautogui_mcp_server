from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from pyautogui_mcp_server.server import MCPAcceptCompatibilityMiddleware


async def echo_accept_header(request: Request) -> JSONResponse:
    return JSONResponse({"accept": request.headers.get("accept")})


def build_test_client() -> TestClient:
    app = Starlette(routes=[Route("/mcp", echo_accept_header, methods=["POST"]), Route("/other", echo_accept_header, methods=["POST"])])
    app.add_middleware(MCPAcceptCompatibilityMiddleware, mcp_path="/mcp")
    return TestClient(app)


def test_mcp_accept_middleware_normalizes_wildcard_accept() -> None:
    with build_test_client() as client:
        response = client.post("/mcp", headers={"accept": "*/*"})

    assert response.status_code == 200
    assert response.json()["accept"] == "*/*, application/json"


def test_mcp_accept_middleware_preserves_explicit_json_accept() -> None:
    with build_test_client() as client:
        response = client.post("/mcp", headers={"accept": "application/json"})

    assert response.status_code == 200
    assert response.json()["accept"] == "application/json"


def test_mcp_accept_middleware_does_not_touch_other_paths() -> None:
    with build_test_client() as client:
        response = client.post("/other", headers={"accept": "*/*"})

    assert response.status_code == 200
    assert response.json()["accept"] == "*/*"
