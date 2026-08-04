#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import r9_worker_patch as candidate

_ORIGINAL = candidate.replace_once


def replace_once(path: Path, old: str, new: str) -> None:
    """Allow only the known duplicated mock-framebuffer insertion target."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    duplicated_mock_framebuffer = (
        path.name == "worker.rs"
        and count == 2
        and old.startswith(
            "        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
            "            Ok(NativeFramebuffer {\n"
        )
        and old.endswith(
            "        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
            "            Ok(NativeFramebuffer {\n"
        )
    )
    if duplicated_mock_framebuffer:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    _ORIGINAL(path, old, new)


def replace_generated(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one generated {label}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


candidate.replace_once = replace_once
candidate.main()

worker = candidate.ROOT / "crates/controller-api/src/worker.rs"
replace_generated(
    worker,
    "            if event.kind == DesktopEventKind::ClipboardRevision { revision: 1 } {\n",
    "            if matches!(\n"
    "                event.kind,\n"
    "                DesktopEventKind::ClipboardRevision { revision: 1 }\n"
    "            ) {\n",
    "clipboard event assertion",
)
replace_generated(
    worker,
    "                run_worker(\n"
    "                    settings,\n"
    "                    factory,\n"
    "                    command_rx,\n"
    "                    event_tx,\n"
    "                    startup_tx,\n"
    "                    thread_snapshot,\n"
    "                    thread_framebuffer,\n"
    "                    thread_clipboard,\n"
    "                );\n",
    "                run_worker(\n"
    "                    settings,\n"
    "                    factory,\n"
    "                    WorkerChannels {\n"
    "                        commands: command_rx,\n"
    "                        events: event_tx,\n"
    "                        startup: startup_tx,\n"
    "                    },\n"
    "                    thread_snapshot,\n"
    "                    thread_framebuffer,\n"
    "                    thread_clipboard,\n"
    "                );\n",
    "worker channel call",
)
replace_generated(
    worker,
    "fn run_worker<F, S>(\n"
    "    settings: WorkerSettings,\n"
    "    mut factory: F,\n"
    "    commands: Receiver<CommandEnvelope>,\n"
    "    events: SyncSender<WorkerEvent>,\n"
    "    startup: SyncSender<()>,\n"
    "    snapshot: Arc<Mutex<WorkerSnapshot>>,\n"
    "    framebuffer: FramebufferStore,\n"
    "    clipboard: Arc<Mutex<Option<ClipboardSnapshot>>>,\n"
    ") where\n"
    "    F: FnMut() -> Result<S, NativeError>,\n"
    "    S: WorkerSession,\n"
    "{\n"
    "    let _ = startup.send(());\n",
    "struct WorkerChannels {\n"
    "    commands: Receiver<CommandEnvelope>,\n"
    "    events: SyncSender<WorkerEvent>,\n"
    "    startup: SyncSender<()>,\n"
    "}\n\n"
    "fn run_worker<F, S>(\n"
    "    settings: WorkerSettings,\n"
    "    mut factory: F,\n"
    "    channels: WorkerChannels,\n"
    "    snapshot: Arc<Mutex<WorkerSnapshot>>,\n"
    "    framebuffer: FramebufferStore,\n"
    "    clipboard: Arc<Mutex<Option<ClipboardSnapshot>>>,\n"
    ") where\n"
    "    F: FnMut() -> Result<S, NativeError>,\n"
    "    S: WorkerSession,\n"
    "{\n"
    "    let WorkerChannels {\n"
    "        commands,\n"
    "        events,\n"
    "        startup,\n"
    "    } = channels;\n"
    "    let _ = startup.send(());\n",
    "worker channel signature",
)
replace_generated(
    worker,
    "            fn send_pointer(\n"
    "                &mut self,\n"
    "                _coordinate: Coordinate,\n"
    "                _button_mask: u8,\n"
    "            ) -> Result<(), NativeError> {\n"
    "                Ok(())\n"
    "            }\n\n"
    "            fn send_key(&mut self, _key: KeyboardKey, _pressed: bool) -> Result<(), NativeError> {\n",
    "            fn clipboard(&self) -> Result<NativeClipboard, NativeError> {\n"
    "                Err(NativeError::ClipboardUnavailable)\n"
    "            }\n\n"
    "            fn send_pointer(\n"
    "                &mut self,\n"
    "                _coordinate: Coordinate,\n"
    "                _button_mask: u8,\n"
    "            ) -> Result<(), NativeError> {\n"
    "                Ok(())\n"
    "            }\n\n"
    "            fn send_key(&mut self, _key: KeyboardKey, _pressed: bool) -> Result<(), NativeError> {\n",
    "mismatched-session clipboard method",
)
