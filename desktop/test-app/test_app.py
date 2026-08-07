#!/usr/bin/env python3
"""Deterministic Tkinter surface the R13 E2E suite drives over VNC and reads back via JSON."""

from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATE_PATH = Path(os.environ.get("TEST_APP_STATE_FILE", "/tmp/vnc-test-app-state.json"))
MAX_EVENTS = 200


@dataclass
class _InputState:
    """The deterministic input state the E2E harness observes via `current_state()`."""

    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    event_sequence: int = 0
    pointer: dict[str, int] = field(default_factory=lambda: {"x": 0, "y": 0})
    buttons: dict[str, bool] = field(
        default_factory=lambda: {"left": False, "middle": False, "right": False}
    )
    scroll: dict[str, int] = field(default_factory=lambda: {"x": 0, "y": 0})
    keys_down: list[str] = field(default_factory=list)
    counter: int = 0
    clipboard_revision: int = 0


class TestApplication:
    """The deterministic test surface: builds the UI, binds events, and persists state."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("VNC Remote Control Deterministic Test App")
        self.root.geometry("800x600+20+20")
        self.root.minsize(800, 600)
        self.state = _InputState()
        self.text = tk.StringVar(value="")
        self.status = tk.StringVar(value="ready")
        self.pointer_text = tk.StringVar(value="pointer: 0,0")
        self.counter_text = tk.StringVar(value="counter: 0")
        self._build_ui()
        self._bind_events()
        self._write_state()

    def run(self) -> None:
        """Start the Tkinter event loop."""
        self.root.mainloop()

    def current_state(self) -> dict[str, Any]:
        """Return the same state payload most recently persisted to `STATE_PATH`."""
        return self._build_state_payload()

    def _build_ui(self) -> None:
        heading = tk.Label(
            self.root,
            text="VNC Remote Control Test Surface",
            font=("DejaVu Sans", 18, "bold"),
        )
        heading.pack(pady=16)
        tk.Label(self.root, textvariable=self.pointer_text, font=("DejaVu Sans Mono", 12)).pack()
        tk.Label(self.root, textvariable=self.counter_text, font=("DejaVu Sans Mono", 12)).pack()
        tk.Label(self.root, textvariable=self.status, font=("DejaVu Sans Mono", 11)).pack(pady=8)

        self.entry = tk.Entry(
            self.root, textvariable=self.text, width=70, font=("DejaVu Sans Mono", 12)
        )
        self.entry.pack(padx=20, pady=12)
        self.entry.focus_set()

        controls = tk.Frame(self.root)
        controls.pack(pady=8)
        self.control_widgets: dict[str, tk.Button] = {}
        for name, label, column, command in (
            ("increment", "Increment", 0, self._increment),
            ("copy", "Copy", 1, self._copy),
            ("paste", "Paste", 2, self._paste),
            ("reset", "Reset", 3, self._reset),
        ):
            button = tk.Button(controls, text=label, width=14, command=command)
            button.grid(row=0, column=column, padx=6)
            self.control_widgets[name] = button

        self.swatches = tk.Frame(self.root)
        self.swatches.pack(pady=10)
        self.swatch_widgets: dict[str, tk.Frame] = {}
        for name, color, column in (
            ("red", "#ff0000", 0),
            ("blue", "#0000ff", 1),
        ):
            swatch = tk.Frame(
                self.swatches,
                width=120,
                height=80,
                bg=color,
                highlightthickness=0,
                borderwidth=0,
            )
            swatch.grid(row=0, column=column, padx=24)
            swatch.grid_propagate(False)
            self.swatch_widgets[name] = swatch

        self.click_target = tk.Label(
            self.root,
            text="CLICK TARGET",
            width=30,
            height=6,
            bg="#336699",
            fg="white",
            font=("DejaVu Sans", 16, "bold"),
            relief=tk.RAISED,
            borderwidth=4,
        )
        self.click_target.pack(pady=12)
        self.root.update_idletasks()

    def _bind_events(self) -> None:
        self.root.bind_all("<Motion>", self._motion, add=True)
        self.root.bind_all("<ButtonPress>", self._button_press, add=True)
        self.root.bind_all("<ButtonRelease>", self._button_release, add=True)
        self.root.bind_all("<KeyPress>", self._key_press, add=True)
        self.root.bind_all("<KeyRelease>", self._key_release, add=True)
        self.root.bind_all("<MouseWheel>", self._mouse_wheel, add=True)
        self.root.bind_all("<Shift-MouseWheel>", self._shift_mouse_wheel, add=True)

    def _record(self, event_type: str, **data: Any) -> None:
        self.state.event_sequence += 1
        self.state.events.append(
            {"sequence": self.state.event_sequence, "type": event_type, **data}
        )
        self.status.set(event_type)
        self._write_state()

    def _motion(self, event: tk.Event[Any]) -> None:
        self.state.pointer = {"x": int(event.x_root), "y": int(event.y_root)}
        self.pointer_text.set(f"pointer: {event.x_root},{event.y_root}")
        self._write_state()

    @staticmethod
    def _button_name(number: int) -> str:
        return {1: "left", 2: "middle", 3: "right"}.get(number, f"button_{number}")

    def _button_press(self, event: tk.Event[Any]) -> None:
        number = int(event.num)
        if number in (4, 5, 6, 7):
            self._linux_wheel(number)
            return
        name = self._button_name(number)
        if name in self.state.buttons:
            self.state.buttons[name] = True
        self._record("button_down", button=name, x=int(event.x_root), y=int(event.y_root))

    def _button_release(self, event: tk.Event[Any]) -> None:
        number = int(event.num)
        if number in (4, 5, 6, 7):
            return
        name = self._button_name(number)
        if name in self.state.buttons:
            self.state.buttons[name] = False
        self._record("button_up", button=name, x=int(event.x_root), y=int(event.y_root))

    def _linux_wheel(self, number: int) -> None:
        delta_x = 0
        delta_y = 0
        if number == 4:
            delta_y = 1
        elif number == 5:
            delta_y = -1
        elif number == 6:
            delta_x = -1
        elif number == 7:
            delta_x = 1
        self.state.scroll["x"] += delta_x
        self.state.scroll["y"] += delta_y
        self._record("scroll", delta_x=delta_x, delta_y=delta_y)

    def _mouse_wheel(self, event: tk.Event[Any]) -> None:
        delta = 1 if int(event.delta) > 0 else -1
        self.state.scroll["y"] += delta
        self._record("scroll", delta_x=0, delta_y=delta)

    def _shift_mouse_wheel(self, event: tk.Event[Any]) -> None:
        delta = 1 if int(event.delta) > 0 else -1
        self.state.scroll["x"] += delta
        self._record("scroll", delta_x=delta, delta_y=0)

    def _key_press(self, event: tk.Event[Any]) -> None:
        key = str(event.keysym)
        if key not in self.state.keys_down:
            self.state.keys_down.append(key)
        self._record("key_down", key=key)

    def _key_release(self, event: tk.Event[Any]) -> None:
        key = str(event.keysym)
        if key in self.state.keys_down:
            self.state.keys_down.remove(key)
        self._record("key_up", key=key)

    def _increment(self) -> None:
        self.state.counter += 1
        self.counter_text.set(f"counter: {self.state.counter}")
        self.click_target.configure(bg="#2e8b57" if self.state.counter % 2 else "#336699")
        self._record("counter", value=self.state.counter)

    def _copy(self) -> None:
        value = self.text.get()
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()
        self.state.clipboard_revision += 1
        self._record("copy", clipboard_revision=self.state.clipboard_revision)

    def _paste(self) -> None:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            value = ""
        self.text.set(value)
        self.state.clipboard_revision += 1
        self._record("paste", clipboard_revision=self.state.clipboard_revision)

    def _reset(self) -> None:
        self.state = _InputState()
        self.text.set("")
        self.pointer_text.set("pointer: 0,0")
        self.counter_text.set("counter: 0")
        self.status.set("reset")
        self.click_target.configure(bg="#336699")
        self._write_state()

    def _control_centers(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "x": int(widget.winfo_rootx() + widget.winfo_width() // 2),
                "y": int(widget.winfo_rooty() + widget.winfo_height() // 2),
            }
            for name, widget in self.control_widgets.items()
        }

    def _swatch_centers(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "x": int(widget.winfo_rootx() + widget.winfo_width() // 2),
                "y": int(widget.winfo_rooty() + widget.winfo_height() // 2),
            }
            for name, widget in self.swatch_widgets.items()
        }

    def _build_state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ready": True,
            "pointer": self.state.pointer,
            "controls": self._control_centers(),
            "swatches": self._swatch_centers(),
            "buttons": self.state.buttons,
            "scroll": self.state.scroll,
            "keys_down": self.state.keys_down,
            "text": self.text.get(),
            "counter": self.state.counter,
            "clipboard_revision": self.state.clipboard_revision,
            "events": list(self.state.events),
        }

    def _write_state(self) -> None:
        payload = self._build_state_payload()
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix="vnc-test-state-", dir=STATE_PATH.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, STATE_PATH)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)


def main() -> None:
    """Build and run the deterministic test surface."""
    root = tk.Tk()
    TestApplication(root).run()


if __name__ == "__main__":
    main()
