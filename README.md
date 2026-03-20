# MCP server for simplest GUI agent 🕹️🤖

`pyautogui_mcp_server` packages a Streamable HTTP MCP server for running Python code with `pyautogui` instrumentation.

It is designed for GUI automation workflows where plain `pyautogui` execution is not enough. The package adds MCP-friendly output handling, richer screenshots, and a small macOS display wake helper.

## ✨ What this package adds

Compared with running raw `pyautogui` calls directly, this library adds extra effort in the following areas:

- Fresh Python execution state for every tool call.
- Captured `stdout`, `stderr`, and final expression results in one MCP response stream.
- Inline screenshot delivery as MCP image content instead of requiring manual file handling.
- Annotated mouse-operation previews that show the target point or path before the action runs.
- Screenshot normalization so captured images line up better with logical screen coordinates.
- A separate macOS wake command for waking the display before automation starts.

**A tool response example:**  
```
<pyautogui-mcp.dragTo x=860 y=430 duration=0.2 button='left' 
    time_offset="T+1.1s" pyautogui.size=(1440, 900)>
```
<img width="512" alt="cut-the-rope-by-gui-agent" src="https://yl-data.github.io/2506.onPanda/pyautogui_mcp_server_assets/image/2603.cut-the-rope.webp" />

```
</pyautogui-mcp.dragTo>
<stdout>
Cut the right rope by dragging left to right through it.
</stdout>
```

## 📦 Installation

```bash
pip install pyautogui_mcp_server
```

For local development:

```bash
pip install -e .[dev]
```

## 🚀 Run the MCP server

Use the module entrypoint:

```bash
python -m pyautogui_mcp_server --host 127.0.0.1 --port 9300
```

Or use the installed console script:

```bash
pyautogui-mcp-server --port 9300
```

Show CLI help:

```bash
python -m pyautogui_mcp_server --help
```

The server exposes a `run_python_with_pyautogui` MCP tool that executes Python in a fresh interpreter state with instrumented `pyautogui` behavior.

## 🖥️ Wake a macOS display

The wake helper is macOS-only.

```bash
python -m pyautogui_mcp_server.wake --hold-seconds 60
```

Or:

```bash
pyautogui-mcp-wake --help
```

This helper sends a short user-activity pulse, optionally activates Finder, and briefly holds the display awake with `caffeinate`.


## 📄 License

MIT
