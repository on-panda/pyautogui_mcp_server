from pyautogui_mcp_server import PythonInterpreterRuntime
from pyautogui_mcp_server.server import DEFAULT_HOST, DEFAULT_PORT, build_argument_parser
from pyautogui_mcp_server.wake import build_argument_parser as build_wake_argument_parser


def test_public_runtime_export() -> None:
    assert PythonInterpreterRuntime.__name__ == "PythonInterpreterRuntime"


def test_server_parser_defaults() -> None:
    args = build_argument_parser().parse_args([])
    assert args.host == DEFAULT_HOST
    assert args.port == DEFAULT_PORT


def test_server_parser_overrides() -> None:
    args = build_argument_parser().parse_args(["--port", "9301", "--host", "0.0.0.0"])
    assert args.host == "0.0.0.0"
    assert args.port == 9301


def test_wake_parser_defaults() -> None:
    args = build_wake_argument_parser().parse_args([])
    assert args.hold_seconds == 60
    assert args.no_activate_finder is False
