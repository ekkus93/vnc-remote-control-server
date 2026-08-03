#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
from collections import deque
from pathlib import Path
from typing import Any

STATE_PATH = Path(os.environ.get("TEST_APP_STATE_FILE", "/tmp/vnc-test-app-state.json"))
MAX_EVENTS = 200


class TestApplication:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("VNC Remote Control Deterministic Test App")
        self.root.geometry("800x600+20+20")
        self.root.minsize(800, 600)
        self.events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self.event_sequence = 0
        self.pointer = {"x": 0, "y": 0}
        self.buttons = {"left": False, "middle": False, "right": False}
        self.scroll = {"x": 0, "y": 0}
        self.keys_down: list[str] = []
        self.counter = 0
        self.clipboard_revision = 0
        self.text = tk.StringVar(value="")
        self.status = tk.StringVar(value="ready")
        self.pointer_text = tk.StringVar(value="pointer: 0,0")
        self.counter_text = tk.StringVar(value="counter: 0")
        self._build_ui()
        self._bind_events()
        self._write_state()

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

        self.entry = tk.Entry(self.root, textvariable=self.text, width=70, font=("DejaVu Sans Mono", 12))
        self.entry.pack(padx=20, pady=12)
        self.entry.focus_set()

        controls = tk.Frame(self.root)
        controls.pack(pady=8)
        tk.Button(controls, text="Increment", width=14, command=self._increment).grid(row=0, column=0, padx=6)
        tk.Button(controls, text="Copy", width=14, command=self._copy).grid(row=0, column=1, padx=6)
        tk.Button(controls, text="Paste", width=14, command=self._paste).grid(row=0, column=2, padx=6)
        tk.Button(controls, text="Reset", width=14, command=self._reset).grid(row=0, column=3, padx=6)

        self.click_target = tk.Label(
            self.root,
            text="CLICK TARGET",
            width=30,
            height=8,
            bg="#336699",
            fg="white",
            font=("DejaVu Sans", 16, "bold"),
            relief=tk.RAISED,
            borderwidth=4,
        )
        self.click_target.pack(pady=24)

    def _bind_events(self) -> None:
        self.root.bind_all("<Motion>", self._motion, add=True)
        self.root.bind_all("<ButtonPress>", self._button_press, add=True)
        self.root.bind_all("<ButtonRelease>", self._button_release, add=True)
        self.root.bind_all("<KeyPress>", self._key_press, add=True)
        self.root.bind_all("<KeyRelease>", self._key_release, add=True)
        self.root.bind_all("<MouseWheel>", self._mouse_wheel, add=True)
        self.root.bind_all("<Shift-MouseWheel>", self._shift_mouse_wheel, add=True)

    def _record(self, event_type: str, **data: Any) -> None:
        self.event_sequence += 1
        self.events.append({"sequence": self.event_sequence, "type": event_type, **data})
        self.status.set(event_type)
        self._write_state()

    def _motion(self, event: tk.Event[Any]) -> None:
        self.pointer = {"x": int(event.x_root), "y": int(event.y_root)}
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
        if name in self.buttons:
            self.buttons[name] = True
        self._record("button_down", button=name, x=int(event.x_root), y=int(event.y_root))

    def _button_release(self, event: tk.Event[Any]) -> None:
        number = int(event.num)
        if number in (4, 5, 6, 7):
            return
        name = self._button_name(number)
        if name in self.buttons:
            self.buttons[name] = False
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
        self.scroll["x"] += delta_x
        self.scroll["y"] += delta_y
        self._record("scroll", delta_x=delta_x, delta_y=delta_y)

    def _mouse_wheel(self, event: tk.Event[Any]) -> None:
        delta = 1 if int(event.delta) > 0 else -1
        self.scroll["y"] += delta
        self._record("scroll", delta_x=0, delta_y=delta)

    def _shift_mouse_wheel(self, event: tk.Event[Any]) -> None:
        delta = 1 if int(event.delta) > 0 else -1
        self.scroll["x"] += delta
        self._record("scroll", delta_x=delta, delta_y=0)

    def _key_press(self, event: tk.Event[Any]) -> None:
        key = str(event.keysym)
        if key not in self.keys_down:
            self.keys_down.append(key)
        self._record("key_down", key=key)

    def _key_release(self, event: tk.Event[Any]) -> None:
        key = str(event.keysym)
        if key in self.keys_down:
            self.keys_down.remove(key)
        self._record("key_up", key=key)

    def _increment(self) -> None:
        self.counter += 1
        self.counter_text.set(f"counter: {self.counter}")
        self.click_target.configure(bg="#2e8b57" if self.counter % 2 else "#336699")
        self._record("counter", value=self.counter)

    def _copy(self) -> None:
        value = self.text.get()
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()
        self.clipboard_revision += 1
        self._record("copy", clipboard_revision=self.clipboard_revision)

    def _paste(self) -> None:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            value = ""
        self.text.set(value)
        self.clipboard_revision += 1
        self._record("paste", clipboard_revision=self.clipboard_revision)

    def _reset(self) -> None:
        self.events.clear()
        self.event_sequence = 0
        self.pointer = {"x": 0, "y": 0}
        self.buttons = {"left": False, "middle": False, "right": False}
        self.scroll = {"x": 0, "y": 0}
        self.keys_down = []
        self.counter = 0
        self.clipboard_revision = 0
        self.text.set("")
        self.pointer_text.set("pointer: 0,0")
        self.counter_text.set("counter: 0")
        self.status.set("reset")
        self.click_target.configure(bg="#336699")
        self._write_state()

    def _write_state(self) -> None:
        payload = {
            "schema_version": 1,
            "ready": True,
            "pointer": self.pointer,
            "buttons": self.buttons,
            "scroll": self.scroll,
            "keys_down": self.keys_down,
            "text": self.text.get(),
            "counter": self.counter,
            "clipboard_revision": self.clipboard_revision,
            "events": list(self.events),
        }
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(prefix="vnc-test-state-", dir=STATE_PATH.parent)
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
    root = tk.Tk()
    TestApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()
