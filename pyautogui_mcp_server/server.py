from __future__ import annotations

import argparse
from typing import Sequence

MCP_SERVER_NAME = "pyautogui-mcp"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9300
CORS_EXPOSE_HEADERS = ["mcp-session-id", "mcp-protocol-version"]


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyautogui-mcp-server",
        description="Run the pyautogui MCP server over Streamable HTTP."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host interface to bind. Default: {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on. Default: {DEFAULT_PORT}.",
    )
    return parser


def create_app(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    from mcp.server.fastmcp import FastMCP
    from starlette.middleware.cors import CORSMiddleware

    from .runtime import PythonInterpreterRuntime

    mcp = FastMCP(
        MCP_SERVER_NAME,
        host=host,
        port=port,
        json_response=True,
        stateless_http=True,
    )
    runtime = PythonInterpreterRuntime()

    @mcp.tool()
    def run_python_with_pyautogui(code: str):
        """Execute Python with pyautogui hooks in a fresh interpreter state.

        Args:
            code: Python code to run. Each call starts from a fresh Python state.
                `pyautogui` is already instrumented: mouse operations capture an
                annotated pre-action screenshot, and screenshots or final PIL
                images are inlined directly in the tool response.
        """

        return runtime.execute(code)

    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=CORS_EXPOSE_HEADERS,
    )
    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(host=args.host, port=args.port)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0
