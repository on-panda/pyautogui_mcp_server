from pyautogui_mcp_server import __description__, __version__
from pyautogui_mcp_server.__info__ import __author__, __url__


def test_metadata_values() -> None:
    assert __version__ == "0.1.1"
    assert "pyautogui" in __description__
    assert __author__ == "DIYer22"
    assert __url__ == "https://github.com/on-panda/pyautogui_mcp_server"
