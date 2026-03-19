from __future__ import annotations

import ast
import contextlib
import contextvars
import functools
import io
import math
import threading
import time
import traceback
from dataclasses import dataclass
from inspect import Signature, signature
from typing import Any, Callable

import pyautogui
from mcp.server.fastmcp import Image as MCPImage
from mcp.types import TextContent
from PIL import Image as PILImage
from PIL import ImageDraw


_LAST_VALUE_NAME = "__pyautogui_mcp_last_value__"
_ACTIVE_RECORDER: contextvars.ContextVar["ExecutionRecorder | None"] = contextvars.ContextVar(
    "pyautogui_mcp_active_recorder",
    default=None,
)
_WRAPPER_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "pyautogui_mcp_wrapper_depth",
    default=0,
)


@dataclass
class StreamEvent:
    stream: str
    text: str


@dataclass
class RawTextEvent:
    text: str


@dataclass
class ImageEvent:
    operation: str
    kwargs: dict[str, Any]
    time_offset: float
    pil_size: tuple[int, int]
    pyautogui_size: tuple[int, int] | None
    image_bytes: bytes


class RecorderStream(io.TextIOBase):
    def __init__(self, recorder: "ExecutionRecorder", stream: str):
        self._recorder = recorder
        self._stream = stream

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._recorder.add_stream_text(self._stream, s)
        return len(s)

    def flush(self) -> None:
        return None

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return "utf-8"


class ExecutionRecorder:
    def __init__(self, start_time: float):
        self.start_time = start_time
        self.events: list[StreamEvent | RawTextEvent | ImageEvent] = []

    def add_stream_text(self, stream: str, text: str) -> None:
        if not text:
            return
        if self.events and isinstance(self.events[-1], StreamEvent) and self.events[-1].stream == stream:
            self.events[-1].text += text
            return
        self.events.append(StreamEvent(stream=stream, text=text))

    def add_result(self, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, PILImage.Image):
            kwargs = {
                "source": "expression",
                "mode": value.mode,
            }
            event = self._build_image_event("result", kwargs, value)
            previous_image = self._find_last_image_event()
            if previous_image is not None and previous_image.image_bytes == event.image_bytes:
                tag = _format_image_open_tag(
                    operation="result",
                    kwargs={**kwargs, "omitted": "same-as-previous-image"},
                    time_offset=event.time_offset,
                    pil_size=event.pil_size,
                    pyautogui_size=event.pyautogui_size,
                )
                self.events.append(
                    RawTextEvent(
                        text=f"{tag}same as previous image, omitted.</pyautogui-mcp.result>"
                    )
                )
                return
            self.events.append(event)
            return
        self.add_stream_text("result", repr(value))

    def add_image(self, operation: str, kwargs: dict[str, Any], image: PILImage.Image) -> None:
        self.events.append(self._build_image_event(operation, kwargs, image))

    def _build_image_event(self, operation: str, kwargs: dict[str, Any], image: PILImage.Image) -> ImageEvent:
        pyautogui_size = _logical_screen_size()
        payload, size = _encode_webp(image)
        return ImageEvent(
            operation=operation,
            kwargs=kwargs,
            time_offset=round(time.time() - self.start_time, 1),
            pil_size=size,
            pyautogui_size=pyautogui_size,
            image_bytes=payload,
        )

    def _find_last_image_event(self) -> ImageEvent | None:
        for event in reversed(self.events):
            if isinstance(event, ImageEvent):
                return event
        return None

    def to_content(self) -> list[Any]:
        content: list[Any] = []
        for event in self.events:
            if isinstance(event, StreamEvent):
                content.append(
                    TextContent(
                        type="text",
                        text=_wrap_text_stream(event.stream, event.text),
                    )
                )
                continue

            if isinstance(event, RawTextEvent):
                content.append(TextContent(type="text", text=event.text))
                continue

            content.append(
                TextContent(
                    type="text",
                    text=_format_image_open_tag(
                        operation=event.operation,
                        kwargs=event.kwargs,
                        time_offset=event.time_offset,
                        pil_size=event.pil_size,
                        pyautogui_size=event.pyautogui_size,
                    ),
                )
            )
            content.append(MCPImage(data=event.image_bytes, format="webp"))
            content.append(
                TextContent(
                    type="text",
                    text=f"</pyautogui-mcp.{event.operation}>",
                )
            )

        if not content:
            content.append(TextContent(type="text", text="Execution finished with no output."))
        return _merge_adjacent_text_content(content)


class PyAutoGUIInterceptor:
    _SCREENSHOT_NAMES = ("screenshot",)
    _MOUSE_NAMES = (
        "moveTo",
        "moveRel",
        "move",
        "dragTo",
        "dragRel",
        "drag",
        "click",
        "doubleClick",
        "tripleClick",
        "mouseDown",
        "mouseUp",
        "scroll",
        "hscroll",
        "vscroll",
    )

    def __init__(self) -> None:
        self._installed = False
        self._originals: dict[str, Callable[..., Any]] = {}
        self._signatures: dict[str, Signature] = {}

    def install(self) -> None:
        if self._installed:
            return

        for name in self._SCREENSHOT_NAMES + self._MOUSE_NAMES:
            original = getattr(pyautogui, name)
            self._originals[name] = original
            self._signatures[name] = signature(original)

        for name in self._SCREENSHOT_NAMES:
            setattr(pyautogui, name, self._make_screenshot_wrapper(name))

        for name in self._MOUSE_NAMES:
            setattr(pyautogui, name, self._make_mouse_wrapper(name))

        self._installed = True

    def _make_screenshot_wrapper(self, name: str) -> Callable[..., Any]:
        original = self._originals[name]

        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            depth = _WRAPPER_DEPTH.get()
            token = _WRAPPER_DEPTH.set(depth + 1)
            try:
                image = original(*args, **kwargs)
            finally:
                _WRAPPER_DEPTH.reset(token)

            bound = self._bind(name, args, kwargs)
            if isinstance(image, PILImage.Image):
                image = _normalize_screenshot_image(image, region=bound.get("region"))
                image_filename = bound.get("imageFilename")
                if image_filename:
                    image.save(image_filename)

            recorder = _ACTIVE_RECORDER.get()
            if recorder is None or depth > 0 or not isinstance(image, PILImage.Image):
                return image

            recorder.add_image(
                operation=name,
                kwargs=_filter_none(
                    {
                        "imageFilename": bound.get("imageFilename"),
                        "region": bound.get("region"),
                    }
                ),
                image=image,
            )
            return image

        return wrapper

    def _make_mouse_wrapper(self, name: str) -> Callable[..., Any]:
        original = self._originals[name]

        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            recorder = _ACTIVE_RECORDER.get()
            depth = _WRAPPER_DEPTH.get()
            if recorder is not None and depth == 0:
                try:
                    preview = self._build_mouse_preview(name, args, kwargs)
                except Exception as exc:
                    recorder.add_stream_text(
                        "stderr",
                        f"[pyautogui-mcp] failed to capture {name} preview: {exc}\n",
                    )
                else:
                    if preview is not None:
                        preview_image, preview_kwargs = preview
                        recorder.add_image(name, preview_kwargs, preview_image)

            token = _WRAPPER_DEPTH.set(depth + 1)
            try:
                return original(*args, **kwargs)
            finally:
                _WRAPPER_DEPTH.reset(token)

        return wrapper

    def _bind(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        bound = self._signatures[name].bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)

    def _build_mouse_preview(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[PILImage.Image, dict[str, Any]] | None:
        screenshot = self._take_screenshot()
        metadata = self._resolve_mouse_metadata(name, args, kwargs)
        if metadata is None:
            return None
        coordinate_space = _point_to_tuple(pyautogui.size())
        annotated = _annotate_mouse_operation(
            screenshot,
            operation=name,
            start=metadata["start"],
            end=metadata.get("end"),
            scroll_clicks=metadata.get("scroll_clicks"),
            coordinate_space=coordinate_space,
        )
        return annotated, metadata["kwargs"]

    def _take_screenshot(self) -> PILImage.Image:
        image = self._originals["screenshot"]()
        if not isinstance(image, PILImage.Image):
            raise TypeError(f"pyautogui.screenshot() returned {type(image).__name__}, expected PIL.Image.Image")
        return _normalize_screenshot_image(image)

    def _resolve_mouse_metadata(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        if name in {"moveTo", "dragTo", "click", "doubleClick", "tripleClick", "mouseDown", "mouseUp"}:
            return self._resolve_absolute_xy(name, args, kwargs)
        if name in {"moveRel", "move", "dragRel", "drag"}:
            return self._resolve_relative_xy(name, args, kwargs)
        if name in {"scroll", "hscroll", "vscroll"}:
            return self._resolve_scroll(name, args, kwargs)
        return None

    def _resolve_absolute_xy(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        bound = self._bind(name, args, kwargs)
        start = _point_to_tuple(pyautogui.position())
        end = _point_to_tuple(pyautogui._normalizeXYArgs(bound.get("x"), bound.get("y")))

        payload: dict[str, Any] = {"start": start, "end": end}
        if name in {"moveTo", "dragTo"}:
            payload["kwargs"] = _filter_none(
                {
                    "x": None if end is None else end[0],
                    "y": None if end is None else end[1],
                    "duration": _non_default(bound.get("duration"), 0.0),
                    "button": _non_default(bound.get("button"), "primary"),
                }
            )
            return payload

        if name in {"click", "doubleClick", "tripleClick", "mouseDown", "mouseUp"}:
            clicks = {"click": bound.get("clicks"), "doubleClick": 2, "tripleClick": 3}.get(name)
            payload["kwargs"] = _filter_none(
                {
                    "x": None if end is None else end[0],
                    "y": None if end is None else end[1],
                    "button": bound.get("button"),
                    "clicks": _non_default(clicks, 1),
                    "interval": _non_default(bound.get("interval"), 0.0),
                    "duration": _non_default(bound.get("duration"), 0.0),
                }
            )
            return payload

        raise ValueError(f"Unsupported absolute mouse operation: {name}")

    def _resolve_relative_xy(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        bound = self._bind(name, args, kwargs)
        start = _point_to_tuple(pyautogui.position())

        x_key = "xOffset"
        y_key = "yOffset"
        x_offset = bound.get(x_key)
        y_offset = bound.get(y_key)
        if isinstance(x_offset, (tuple, list)):
            x_offset, y_offset = x_offset[0], x_offset[1]

        x_offset = 0 if x_offset is None else int(x_offset)
        y_offset = 0 if y_offset is None else int(y_offset)
        end = (start[0] + x_offset, start[1] + y_offset)
        return {
            "start": start,
            "end": end,
            "kwargs": _filter_none(
                {
                    "xOffset": _non_default(x_offset, 0),
                    "yOffset": _non_default(y_offset, 0),
                    "duration": _non_default(bound.get("duration"), 0.0),
                    "button": _non_default(bound.get("button"), "primary"),
                }
            ),
        }

    def _resolve_scroll(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        bound = self._bind(name, args, kwargs)
        start = _point_to_tuple(pyautogui.position())
        x = bound.get("x")
        y = bound.get("y")
        if isinstance(x, (tuple, list)):
            x, y = x[0], x[1]
        end = _point_to_tuple(pyautogui.position(x, y))
        clicks = bound["clicks"]
        return {
            "start": start,
            "end": end,
            "scroll_clicks": clicks,
            "kwargs": _filter_none(
                {
                    "clicks": clicks,
                    "x": None if end is None else end[0],
                    "y": None if end is None else end[1],
                }
            ),
        }


class PythonInterpreterRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._interceptor = PyAutoGUIInterceptor()
        self._interceptor.install()

    def execute(self, code: str) -> list[Any]:
        with self._lock:
            recorder = ExecutionRecorder(start_time=time.time())
            stdout = RecorderStream(recorder, "stdout")
            stderr = RecorderStream(recorder, "stderr")
            token = _ACTIVE_RECORDER.set(recorder)
            try:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self._execute_code(code, recorder)
            except Exception:
                recorder.add_stream_text("stderr", traceback.format_exc())
            finally:
                _ACTIVE_RECORDER.reset(token)
            return recorder.to_content()

    def _execute_code(self, code: str, recorder: ExecutionRecorder) -> None:
        module = ast.parse(code, mode="exec")
        captures_last_value = bool(module.body) and isinstance(module.body[-1], ast.Expr)
        if captures_last_value:
            module.body[-1] = ast.Assign(
                targets=[ast.Name(id=_LAST_VALUE_NAME, ctx=ast.Store())],
                value=module.body[-1].value,
            )
            ast.fix_missing_locations(module)

        compiled = compile(module, "<pyautogui-mcp>", "exec")
        globals_dict = self._fresh_globals()
        exec(compiled, globals_dict, globals_dict)

        last_value = globals_dict.pop(_LAST_VALUE_NAME, None)
        if captures_last_value and last_value is not None:
            recorder.add_result(last_value)

    def _fresh_globals(self) -> dict[str, Any]:
        return {
            "__builtins__": __builtins__,
            "__name__": "__main__",
            "__package__": None,
            "__doc__": None,
            "pyautogui": pyautogui,
        }


def _encode_webp(image: PILImage.Image) -> tuple[bytes, tuple[int, int]]:
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    else:
        image = image.copy()

    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=35, method=6)
    return buffer.getvalue(), image.size


def _logical_screen_size() -> tuple[int, int] | None:
    try:
        size = pyautogui.size()
    except Exception:
        return None
    return _point_to_tuple(size)


def _normalize_screenshot_image(
    image: PILImage.Image,
    region: tuple[int, int, int, int] | list[int] | None = None,
) -> PILImage.Image:
    scale = _detect_capture_scale(image.size, region=region)
    if scale is None:
        return image
    scale_x, scale_y = scale
    if _is_close(scale_x, 1.0) and _is_close(scale_y, 1.0):
        return image

    target_size = (
        max(1, int(round(image.size[0] / scale_x))),
        max(1, int(round(image.size[1] / scale_y))),
    )
    if target_size == image.size:
        return image
    return image.resize(target_size, resample=PILImage.Resampling.LANCZOS)


def _detect_capture_scale(
    captured_size: tuple[int, int],
    region: tuple[int, int, int, int] | list[int] | None = None,
) -> tuple[float, float] | None:
    reference_size = _logical_capture_reference(region=region)
    if reference_size is None or reference_size[0] <= 0 or reference_size[1] <= 0:
        return None

    if captured_size[0] <= 0 or captured_size[1] <= 0:
        return None

    scale_x = captured_size[0] / reference_size[0]
    scale_y = captured_size[1] / reference_size[1]

    if scale_x < 0.98 or scale_y < 0.98:
        return None
    if scale_x > 8.0 or scale_y > 8.0:
        return None

    return (scale_x, scale_y)


def _logical_capture_reference(
    region: tuple[int, int, int, int] | list[int] | None = None,
) -> tuple[int, int] | None:
    if region is not None and len(region) == 4:
        return (
            max(1, int(round(region[2]))),
            max(1, int(round(region[3]))),
        )
    return _logical_screen_size()


def _is_close(left: float, right: float, *, tolerance: float = 0.03) -> bool:
    return abs(left - right) <= tolerance


def _format_image_open_tag(
    operation: str,
    kwargs: dict[str, Any],
    time_offset: float,
    pil_size: tuple[int, int],
    pyautogui_size: tuple[int, int] | None,
) -> str:
    parts = [f"{key}={repr(value)}" for key, value in kwargs.items()]
    parts.append(f'time_offset="T+{time_offset:.1f}s"')
    if pyautogui_size is not None and operation in {
        "screenshot",
        "moveTo",
        "moveRel",
        "move",
        "dragTo",
        "dragRel",
        "drag",
        "click",
        "doubleClick",
        "tripleClick",
        "mouseDown",
        "mouseUp",
        "scroll",
        "hscroll",
        "vscroll",
    }:
        parts.append(f"pyautogui.size={pyautogui_size}")
    else:
        parts.append(f"PIL_size={pil_size}")
    return f"<pyautogui-mcp.{operation} {' '.join(parts)}>"


def _wrap_text_stream(stream: str, text: str) -> str:
    return f"<{stream}>{text}</{stream}>"


def _merge_adjacent_text_content(content: list[Any]) -> list[Any]:
    merged: list[Any] = []
    for item in content:
        if (
            merged
            and isinstance(item, TextContent)
            and isinstance(merged[-1], TextContent)
        ):
            merged[-1] = TextContent(
                type="text",
                text=merged[-1].text + item.text,
            )
            continue
        merged.append(item)
    return merged


def _point_to_tuple(point: Any) -> tuple[int, int] | None:
    if point is None:
        return None
    return (int(point[0]), int(point[1]))


def _filter_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _non_default(value: Any, default: Any) -> Any:
    if value == default:
        return None
    return value


def _annotate_mouse_operation(
    image: PILImage.Image,
    operation: str,
    start: tuple[int, int] | None,
    end: tuple[int, int] | None,
    scroll_clicks: int | float | None = None,
    coordinate_space: tuple[int, int] | None = None,
) -> PILImage.Image:
    annotated = image.convert("RGBA")
    draw = ImageDraw.Draw(annotated)

    base_line_width = max(1, round(min(annotated.size) / 1400))
    line_width = base_line_width * 9
    halo_width = line_width + max(2, line_width // 2)
    marker_size = max(9, round(min(annotated.size) / 88))
    marker_line_width = max(1, base_line_width + 1)
    marker_halo_width = max(2, base_line_width + 3)
    start_point = _scale_and_clamp_point(start, annotated.size, coordinate_space)
    end_point = _scale_and_clamp_point(end, annotated.size, coordinate_space)
    end_color = (255, 74, 74, 255)
    path_color = (255, 92, 92, 230)
    halo_color = (255, 255, 255, 215)
    marker_fill = (255, 92, 92, 72)
    marker_inner_gap = max(6, round(marker_size * 0.72))

    if start_point and end_point and start_point != end_point:
        path_end = _shorten_segment(start_point, end_point, marker_inner_gap)
        _draw_dashed_path(
            draw,
            start_point,
            path_end,
            line_width=line_width,
            halo_width=halo_width,
            color=path_color,
            halo_color=halo_color,
        )
        _draw_cursor_anchor(
            draw,
            end_point,
            size=marker_size,
            color=end_color,
            halo_color=halo_color,
            fill_color=marker_fill,
            line_width=marker_line_width,
            halo_width=marker_halo_width,
        )
    else:
        point = end_point or start_point
        if point is not None:
            _draw_cursor_anchor(
                draw,
                point,
                size=marker_size,
                color=end_color,
                halo_color=halo_color,
                fill_color=marker_fill,
                line_width=marker_line_width,
                halo_width=marker_halo_width,
            )

    if operation in {"scroll", "hscroll", "vscroll"} and (end_point or start_point) is not None:
        point = end_point or start_point
        assert point is not None
        _draw_scroll_hint(
            draw,
            point,
            operation,
            scroll_clicks or 0,
            line_width=line_width,
            halo_width=halo_width,
            color=path_color,
            halo_color=halo_color,
            marker_size=marker_size,
            marker_line_width=marker_line_width,
            marker_halo_width=marker_halo_width,
        )

    return annotated.convert("RGB")


def _draw_cursor_anchor(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    size: int,
    color: tuple[int, int, int, int],
    halo_color: tuple[int, int, int, int],
    halo_width: int,
    fill_color: tuple[int, int, int, int],
    line_width: int,
) -> None:
    center_x, center_y = point
    outer_radius = max(size + 8, round(size * 1.7))
    tip_radius = max(4, round(size * 0.58))
    arc_half_span = 18

    for angle_deg in (45, 135, 225, 315):
        ray = _build_cursor_ray(
            center=(center_x, center_y),
            angle_deg=angle_deg,
            tip_radius=tip_radius,
            outer_radius=outer_radius,
            arc_half_span_deg=arc_half_span,
            arc_steps=7,
        )
        draw.polygon(ray, fill=fill_color)
        draw.line(ray + [ray[0]], fill=halo_color, width=halo_width, joint="curve")
        draw.line(ray + [ray[0]], fill=color, width=line_width, joint="curve")


def _build_cursor_ray(
    center: tuple[int, int],
    angle_deg: float,
    tip_radius: float,
    outer_radius: float,
    arc_half_span_deg: float,
    arc_steps: int,
) -> list[tuple[int, int]]:
    tip = _polar_point(center, tip_radius, angle_deg)
    start_angle = angle_deg - arc_half_span_deg
    end_angle = angle_deg + arc_half_span_deg
    arc = [
        _polar_point(center, outer_radius, angle)
        for angle in _linspace(start_angle, end_angle, arc_steps)
    ]
    return [tip, *arc]


def _draw_dashed_path(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    line_width: int,
    halo_width: int,
    color: tuple[int, int, int, int],
    halo_color: tuple[int, int, int, int],
) -> None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1.0)
    dash_len = max(8, round(min(abs(dx), abs(dy), length) / 8)) if dx and dy else max(8, round(length / 12))
    gap_len = max(5, round(dash_len * 0.6))
    ux = dx / length
    uy = dy / length
    travelled = 0.0

    while travelled < length:
        seg_start = travelled
        seg_end = min(length, travelled + dash_len)
        x1 = int(round(start[0] + ux * seg_start))
        y1 = int(round(start[1] + uy * seg_start))
        x2 = int(round(start[0] + ux * seg_end))
        y2 = int(round(start[1] + uy * seg_end))
        draw.line((x1, y1, x2, y2), fill=halo_color, width=halo_width)
        draw.line((x1, y1, x2, y2), fill=color, width=line_width)
        travelled += dash_len + gap_len


def _draw_scroll_hint(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    operation: str,
    clicks: int | float,
    line_width: int,
    halo_width: int,
    color: tuple[int, int, int, int],
    halo_color: tuple[int, int, int, int],
    marker_size: int,
    marker_line_width: int,
    marker_halo_width: int,
) -> None:
    x, y = point
    length = marker_size * 2
    if operation == "hscroll":
        direction = 1 if clicks >= 0 else -1
        end = (x + direction * length, y)
    else:
        direction = -1 if clicks >= 0 else 1
        end = (x, y + direction * length)
    start = _shorten_segment(end, point, max(6, round(marker_size * 0.72)))
    _draw_dashed_path(
        draw,
        start,
        end,
        line_width=line_width,
        halo_width=halo_width,
        color=color,
        halo_color=halo_color,
    )
    _draw_cursor_anchor(
        draw,
        end,
        size=max(7, marker_size - 2),
        color=color,
        halo_color=halo_color,
        fill_color=(255, 92, 92, 64),
        line_width=marker_line_width,
        halo_width=marker_halo_width,
    )


def _linspace(start: float, end: float, steps: int) -> list[float]:
    if steps <= 1:
        return [start]
    step = (end - start) / (steps - 1)
    return [start + step * idx for idx in range(steps)]


def _polar_point(center: tuple[int, int], radius: float, angle_deg: float) -> tuple[int, int]:
    angle_rad = math.radians(angle_deg)
    return (
        int(round(center[0] + math.cos(angle_rad) * radius)),
        int(round(center[1] + math.sin(angle_rad) * radius)),
    )


def _shorten_segment(
    start: tuple[int, int],
    end: tuple[int, int],
    inset_from_end: float,
) -> tuple[int, int]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return end
    if inset_from_end <= 0:
        return end
    usable = max(0.0, length - inset_from_end)
    ratio = usable / length
    return (
        int(round(start[0] + dx * ratio)),
        int(round(start[1] + dy * ratio)),
    )

def _scale_and_clamp_point(
    point: tuple[int, int] | None,
    image_size: tuple[int, int],
    coordinate_space: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if point is None:
        return None
    x, y = point
    if coordinate_space is not None and coordinate_space[0] > 0 and coordinate_space[1] > 0:
        scale_x = image_size[0] / coordinate_space[0]
        scale_y = image_size[1] / coordinate_space[1]
        x = int(round(x * scale_x))
        y = int(round(y * scale_y))
    width, height = image_size
    return (
        max(0, min(width - 1, int(x))),
        max(0, min(height - 1, int(y))),
    )
