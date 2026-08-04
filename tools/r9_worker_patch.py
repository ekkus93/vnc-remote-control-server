#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement target, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_input() -> None:
    path = ROOT / "crates/controller-api/src/input.rs"
    replace_once(
        path,
        "    Coordinate, DesktopError, DisplayInfo, KeyboardKey, MouseButton, validate_chord,\n"
        "    validate_scroll,\n",
        "    Coordinate, DesktopError, DisplayInfo, KeyboardKey, MouseButton, validate_chord,\n"
        "    validate_scroll, validate_text,\n",
    )
    replace_once(
        path,
        "    /// Best-effort releases every locally tracked input and clears local state.\n",
        "    /// Enters one completely preflighted v0.1 text value.\n"
        "    pub(crate) fn type_text<S: InputSink>(\n"
        "        &mut self,\n"
        "        sink: &mut S,\n"
        "        text: &str,\n"
        "    ) -> Result<usize, DesktopError> {\n"
        "        let character_count = validate_text(text)?;\n"
        "        for character in text.chars() {\n"
        "            let key = match character {\n"
        "                '\\n' | '\\r' => KeyboardKey::Enter,\n"
        "                '\\t' => KeyboardKey::Tab,\n"
        "                value => KeyboardKey::Printable(value),\n"
        "            };\n"
        "            self.set_key(sink, key, true)?;\n"
        "            if let Err(error) = self.set_key(sink, key, false) {\n"
        "                let _ = self.set_key(sink, key, false);\n"
        "                return Err(error);\n"
        "            }\n"
        "        }\n"
        "        Ok(character_count)\n"
        "    }\n\n"
        "    /// Best-effort releases every locally tracked input and clears local state.\n",
    )
    replace_once(
        path,
        "    #[test]\n"
        "    fn disconnect_release_clears_buttons_and_keys() {\n",
        "    #[test]\n"
        "    fn text_is_fully_preflighted_and_sent_in_order() {\n"
        "        let mut controller = InputController::default();\n"
        "        let mut sink = RecordingSink::default();\n"
        "        assert_eq!(\n"
        "            controller\n"
        "                .type_text(&mut sink, \"A\\n\\t!\")\n"
        "                .expect(\"supported text\"),\n"
        "            4\n"
        "        );\n"
        "        assert_eq!(\n"
        "            sink.events,\n"
        "            vec![\n"
        "                Event::Key(KeyboardKey::Printable('A'), true),\n"
        "                Event::Key(KeyboardKey::Printable('A'), false),\n"
        "                Event::Key(KeyboardKey::Enter, true),\n"
        "                Event::Key(KeyboardKey::Enter, false),\n"
        "                Event::Key(KeyboardKey::Tab, true),\n"
        "                Event::Key(KeyboardKey::Tab, false),\n"
        "                Event::Key(KeyboardKey::Printable('!'), true),\n"
        "                Event::Key(KeyboardKey::Printable('!'), false),\n"
        "            ]\n"
        "        );\n\n"
        "        sink.events.clear();\n"
        "        assert!(controller.type_text(&mut sink, \"ok☃\").is_err());\n"
        "        assert!(sink.events.is_empty());\n"
        "    }\n\n"
        "    #[test]\n"
        "    fn text_release_failure_is_retried_and_reported() {\n"
        "        let mut controller = InputController::default();\n"
        "        let mut sink = RecordingSink::fail_on(2);\n"
        "        assert!(controller.type_text(&mut sink, \"A\").is_err());\n"
        "        assert_eq!(\n"
        "            sink.events,\n"
        "            vec![\n"
        "                Event::Key(KeyboardKey::Printable('A'), true),\n"
        "                Event::Key(KeyboardKey::Printable('A'), false),\n"
        "            ]\n"
        "        );\n"
        "    }\n\n"
        "    #[test]\n"
        "    fn disconnect_release_clears_buttons_and_keys() {\n",
    )


def patch_core() -> None:
    path = ROOT / "crates/remote-desktop-core/src/lib.rs"
    replace_once(
        path,
        "#[derive(Debug, Clone, PartialEq, Eq)]\n"
        "pub enum WorkerCommand {\n",
        "#[derive(Clone, PartialEq, Eq)]\n"
        "pub enum WorkerCommand {\n",
    )
    replace_once(
        path,
        "/// Public event kinds. Payload text and pixels are intentionally absent.\n",
        "impl fmt::Debug for WorkerCommand {\n"
        "    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {\n"
        "        match self {\n"
        "            Self::MovePointer { coordinate } => formatter\n"
        "                .debug_struct(\"MovePointer\")\n"
        "                .field(\"coordinate\", coordinate)\n"
        "                .finish(),\n"
        "            Self::SetButton { coordinate, button, pressed } => formatter\n"
        "                .debug_struct(\"SetButton\")\n"
        "                .field(\"coordinate\", coordinate)\n"
        "                .field(\"button\", button)\n"
        "                .field(\"pressed\", pressed)\n"
        "                .finish(),\n"
        "            Self::Click { coordinate, button } => formatter\n"
        "                .debug_struct(\"Click\")\n"
        "                .field(\"coordinate\", coordinate)\n"
        "                .field(\"button\", button)\n"
        "                .finish(),\n"
        "            Self::DoubleClick { coordinate, button, interval_ms } => formatter\n"
        "                .debug_struct(\"DoubleClick\")\n"
        "                .field(\"coordinate\", coordinate)\n"
        "                .field(\"button\", button)\n"
        "                .field(\"interval_ms\", interval_ms)\n"
        "                .finish(),\n"
        "            Self::Scroll { coordinate, delta_x, delta_y } => formatter\n"
        "                .debug_struct(\"Scroll\")\n"
        "                .field(\"coordinate\", coordinate)\n"
        "                .field(\"delta_x\", delta_x)\n"
        "                .field(\"delta_y\", delta_y)\n"
        "                .finish(),\n"
        "            Self::SetKey { key, pressed } => formatter\n"
        "                .debug_struct(\"SetKey\")\n"
        "                .field(\"key\", key)\n"
        "                .field(\"pressed\", pressed)\n"
        "                .finish(),\n"
        "            Self::Chord { keys } => formatter\n"
        "                .debug_struct(\"Chord\")\n"
        "                .field(\"keys\", keys)\n"
        "                .finish(),\n"
        "            Self::TypeText { text } => formatter\n"
        "                .debug_struct(\"TypeText\")\n"
        "                .field(\"text_bytes\", &text.len())\n"
        "                .finish(),\n"
        "            Self::SetClipboard { text } => formatter\n"
        "                .debug_struct(\"SetClipboard\")\n"
        "                .field(\"text_bytes\", &text.len())\n"
        "                .finish(),\n"
        "            Self::RequestFullRefresh => formatter.write_str(\"RequestFullRefresh\"),\n"
        "            Self::Reconnect => formatter.write_str(\"Reconnect\"),\n"
        "            Self::Shutdown => formatter.write_str(\"Shutdown\"),\n"
        "        }\n"
        "    }\n"
        "}\n\n"
        "/// Public event kinds. Payload text and pixels are intentionally absent.\n",
    )
    replace_once(
        path,
        "    #[test]\n"
        "    fn connection_transition_contract_is_explicit() {\n",
        "    #[test]\n"
        "    fn worker_command_debug_redacts_text_and_clipboard_payloads() {\n"
        "        let typed = format!(\n"
        "            \"{:?}\",\n"
        "            WorkerCommand::TypeText {\n"
        "                text: \"typed secret\".to_owned(),\n"
        "            }\n"
        "        );\n"
        "        assert!(!typed.contains(\"typed secret\"));\n"
        "        assert!(typed.contains(\"text_bytes\"));\n\n"
        "        let clipboard = format!(\n"
        "            \"{:?}\",\n"
        "            WorkerCommand::SetClipboard {\n"
        "                text: \"clipboard secret\".to_owned(),\n"
        "            }\n"
        "        );\n"
        "        assert!(!clipboard.contains(\"clipboard secret\"));\n"
        "        assert!(clipboard.contains(\"text_bytes\"));\n"
        "    }\n\n"
        "    #[test]\n"
        "    fn connection_transition_contract_is_explicit() {\n",
    )


def patch_worker() -> None:
    path = ROOT / "crates/controller-api/src/worker.rs"
    replace_once(
        path,
        "    NativeClient, NativeClientConfig, NativeDisplayInfo, NativeError, NativeFramebuffer,\n"
        "    PollOutcome,\n",
        "    NativeClient, NativeClientConfig, NativeClipboard, NativeDisplayInfo, NativeError,\n"
        "    NativeFramebuffer, PollOutcome,\n",
    )
    replace_once(
        path,
        "    ConnectionState, Coordinate, DesktopError, DesktopEventKind, DisplayInfo, KeyboardKey,\n"
        "    MAX_FRAMEBUFFER_BYTES, WorkerCommand,\n",
        "    ClipboardSnapshot, ConnectionState, Coordinate, DesktopError, DesktopEventKind,\n"
        "    DisplayInfo, KeyboardKey, MAX_FRAMEBUFFER_BYTES, WorkerCommand, validate_clipboard,\n",
    )
    replace_once(
        path,
        "    framebuffer: FramebufferStore,\n"
        "    next_command_id: Arc<AtomicU64>,\n",
        "    framebuffer: FramebufferStore,\n"
        "    clipboard: Arc<Mutex<Option<ClipboardSnapshot>>>,\n"
        "    next_command_id: Arc<AtomicU64>,\n",
    )
    replace_once(
        path,
        "    /// Creates a bounded screenshot service over the worker-owned framebuffer.\n",
        "    /// Returns the last valid inbound clipboard snapshot.\n"
        "    pub fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {\n"
        "        lock_unpoisoned(&self.clipboard)\n"
        "            .clone()\n"
        "            .ok_or(DesktopError::ClipboardUnavailable)\n"
        "    }\n\n"
        "    /// Creates a bounded screenshot service over the worker-owned framebuffer.\n",
    )
    replace_once(
        path,
        "        let framebuffer = FramebufferStore::new(settings.maximum_framebuffer_bytes)?;\n"
        "        let thread_framebuffer = framebuffer.clone();\n",
        "        let framebuffer = FramebufferStore::new(settings.maximum_framebuffer_bytes)?;\n"
        "        let thread_framebuffer = framebuffer.clone();\n"
        "        let clipboard = Arc::new(Mutex::new(None));\n"
        "        let thread_clipboard = Arc::clone(&clipboard);\n",
    )
    replace_once(
        path,
        "                    thread_framebuffer,\n"
        "                );\n",
        "                    thread_framebuffer,\n"
        "                    thread_clipboard,\n"
        "                );\n",
    )
    replace_once(
        path,
        "                    framebuffer,\n"
        "                    next_command_id: Arc::new(AtomicU64::new(1)),\n",
        "                    framebuffer,\n"
        "                    clipboard,\n"
        "                    next_command_id: Arc::new(AtomicU64::new(1)),\n",
    )
    replace_once(
        path,
        "    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError>;\n"
        "    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError>;\n",
        "    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError>;\n"
        "    fn clipboard(&self) -> Result<NativeClipboard, NativeError>;\n"
        "    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError>;\n",
    )
    replace_once(
        path,
        "    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
        "        NativeClient::framebuffer(self)\n"
        "    }\n\n"
        "    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {\n",
        "    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
        "        NativeClient::framebuffer(self)\n"
        "    }\n\n"
        "    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {\n"
        "        NativeClient::clipboard(self)\n"
        "    }\n\n"
        "    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {\n",
    )
    replace_once(
        path,
        "    framebuffer: FramebufferStore,\n"
        "    event_sequence: u64,\n"
        "    session: Option<S>,\n"
        "    last_native_revision: Option<u64>,\n",
        "    framebuffer: FramebufferStore,\n"
        "    clipboard: &'a Arc<Mutex<Option<ClipboardSnapshot>>>,\n"
        "    event_sequence: u64,\n"
        "    session: Option<S>,\n"
        "    last_native_revision: Option<u64>,\n"
        "    last_native_clipboard_revision: Option<u64>,\n"
        "    clipboard_revision: u64,\n"
        "    clipboard_decode_failed: bool,\n",
    )
    replace_once(
        path,
        "        if self.connected_since.is_some_and(|since| {\n",
        "        self.refresh_clipboard()?;\n\n"
        "        if self.connected_since.is_some_and(|since| {\n",
    )
    replace_once(
        path,
        "    fn release_input(&mut self) {\n",
        "    fn refresh_clipboard(&mut self) -> Result<(), DesktopError> {\n"
        "        let clipboard = self\n"
        "            .session\n"
        "            .as_ref()\n"
        "            .ok_or(DesktopError::WorkerUnavailable)?\n"
        "            .clipboard();\n"
        "        match clipboard {\n"
        "            Ok(native) if self.last_native_clipboard_revision == Some(native.revision) => {\n"
        "                Ok(())\n"
        "            }\n"
        "            Ok(native) => {\n"
        "                self.last_native_clipboard_revision = Some(native.revision);\n"
        "                self.clipboard_decode_failed = false;\n"
        "                if validate_clipboard(&native.text).is_err() {\n"
        "                    self.record_failure(WorkerFailureKind::Protocol);\n"
        "                    self.publish(DesktopEventKind::ProtocolError);\n"
        "                    return Ok(());\n"
        "                }\n"
        "                let revision = self\n"
        "                    .clipboard_revision\n"
        "                    .checked_add(1)\n"
        "                    .ok_or(DesktopError::Protocol)?;\n"
        "                self.clipboard_revision = revision;\n"
        "                *lock_unpoisoned(self.clipboard) = Some(ClipboardSnapshot {\n"
        "                    text: Arc::from(native.text),\n"
        "                    revision,\n"
        "                    updated_at: SystemTime::now(),\n"
        "                });\n"
        "                self.publish(DesktopEventKind::ClipboardRevision { revision });\n"
        "                Ok(())\n"
        "            }\n"
        "            Err(NativeError::ClipboardUnavailable) => Ok(()),\n"
        "            Err(NativeError::ClipboardNotUtf8) => {\n"
        "                if !self.clipboard_decode_failed {\n"
        "                    self.clipboard_decode_failed = true;\n"
        "                    self.record_failure(WorkerFailureKind::Protocol);\n"
        "                    self.publish(DesktopEventKind::ProtocolError);\n"
        "                }\n"
        "                Ok(())\n"
        "            }\n"
        "            Err(error) => Err(error.into()),\n"
        "        }\n"
        "    }\n\n"
        "    fn release_input(&mut self) {\n",
    )
    replace_once(
        path,
        "        self.last_native_revision = None;\n"
        "        let store_changed = self.framebuffer.invalidate();\n",
        "        self.last_native_revision = None;\n"
        "        self.last_native_clipboard_revision = None;\n"
        "        self.clipboard_decode_failed = false;\n"
        "        let store_changed = self.framebuffer.invalidate();\n",
    )
    replace_once(
        path,
        "            WorkerCommand::SetClipboard { text } => self\n"
        "                .session\n"
        "                .as_mut()\n"
        "                .ok_or(DesktopError::WorkerUnavailable)?\n"
        "                .send_clipboard(&text)\n"
        "                .map_err(DesktopError::from),\n",
        "            WorkerCommand::SetClipboard { text } => {\n"
        "                validate_clipboard(&text)?;\n"
        "                self.session\n"
        "                    .as_mut()\n"
        "                    .ok_or(DesktopError::WorkerUnavailable)?\n"
        "                    .send_clipboard(&text)\n"
        "                    .map_err(DesktopError::from)\n"
        "            }\n",
    )
    replace_once(
        path,
        "            WorkerCommand::TypeText { .. } => Err(DesktopError::Configuration(\n"
        "                \"text input is not enabled until the text milestone\".to_owned(),\n"
        "            )),\n",
        "            WorkerCommand::TypeText { text } => {\n"
        "                let session = self\n"
        "                    .session\n"
        "                    .as_mut()\n"
        "                    .ok_or(DesktopError::WorkerUnavailable)?;\n"
        "                self.input.type_text(session, &text).map(|_| ())\n"
        "            }\n",
    )
    replace_once(
        path,
        "    framebuffer: FramebufferStore,\n"
        ") where\n",
        "    framebuffer: FramebufferStore,\n"
        "    clipboard: Arc<Mutex<Option<ClipboardSnapshot>>>,\n"
        ") where\n",
    )
    replace_once(
        path,
        "        framebuffer,\n"
        "        event_sequence: 0,\n"
        "        session: None,\n"
        "        last_native_revision: None,\n",
        "        framebuffer,\n"
        "        clipboard: &clipboard,\n"
        "        event_sequence: 0,\n"
        "        session: None,\n"
        "        last_native_revision: None,\n"
        "        last_native_clipboard_revision: None,\n"
        "        clipboard_revision: 0,\n"
        "        clipboard_decode_failed: false,\n",
    )
    replace_once(
        path,
        "        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
        "            Ok(NativeFramebuffer {\n",
        "        fn clipboard(&self) -> Result<NativeClipboard, NativeError> {\n"
        "            Err(NativeError::ClipboardUnavailable)\n"
        "        }\n\n"
        "        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
        "            Ok(NativeFramebuffer {\n",
    )
    replace_once(
        path,
        "    #[derive(Debug, Clone, Copy, PartialEq, Eq)]\n"
        "    enum InputEvent {\n"
        "        Pointer(Coordinate, u8),\n"
        "        Key(KeyboardKey, bool),\n"
        "    }\n",
        "    #[derive(Debug, Clone, PartialEq, Eq)]\n"
        "    enum InputEvent {\n"
        "        Pointer(Coordinate, u8),\n"
        "        Key(KeyboardKey, bool),\n"
        "        Clipboard(String),\n"
        "    }\n",
    )
    replace_once(
        path,
        "        fail_on_input_call: Option<usize>,\n"
        "    }\n",
        "        fail_on_input_call: Option<usize>,\n"
        "        clipboard: Option<NativeClipboard>,\n"
        "    }\n",
    )
    replace_once(
        path,
        "                fail_on_input_call,\n"
        "            }\n"
        "        }\n",
        "                fail_on_input_call,\n"
        "                clipboard: None,\n"
        "            }\n"
        "        }\n\n"
        "        fn with_clipboard(\n"
        "            events: Arc<Mutex<Vec<InputEvent>>>,\n"
        "            text: &str,\n"
        "            revision: u64,\n"
        "        ) -> Self {\n"
        "            Self {\n"
        "                events,\n"
        "                input_calls: 0,\n"
        "                fail_on_input_call: None,\n"
        "                clipboard: Some(NativeClipboard {\n"
        "                    text: text.to_owned(),\n"
        "                    revision,\n"
        "                }),\n"
        "            }\n"
        "        }\n",
    )
    replace_once(
        path,
        "        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
        "            Ok(NativeFramebuffer {\n"
        "                width: 2,\n"
        "                height: 2,\n"
        "                revision: 1,\n"
        "                bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],\n"
        "            })\n"
        "        }\n\n"
        "        fn send_pointer(\n"
        "            &mut self,\n"
        "            coordinate: Coordinate,\n",
        "        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
        "            Ok(NativeFramebuffer {\n"
        "                width: 2,\n"
        "                height: 2,\n"
        "                revision: 1,\n"
        "                bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],\n"
        "            })\n"
        "        }\n\n"
        "        fn clipboard(&self) -> Result<NativeClipboard, NativeError> {\n"
        "            self.clipboard\n"
        "                .clone()\n"
        "                .ok_or(NativeError::ClipboardUnavailable)\n"
        "        }\n\n"
        "        fn send_pointer(\n"
        "            &mut self,\n"
        "            coordinate: Coordinate,\n",
    )
    replace_once(
        path,
        "        fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {\n"
        "            Ok(())\n"
        "        }\n"
        "    }\n\n"
        "    fn settings() -> WorkerSettings {\n",
        "        fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {\n"
        "            self.record(InputEvent::Clipboard(text.to_owned()))\n"
        "        }\n"
        "    }\n\n"
        "    fn settings() -> WorkerSettings {\n",
    )
    replace_once(
        path,
        "    #[test]\n"
        "    fn worker_rejects_invalid_coordinate_before_native_mutation() {\n",
        "    #[test]\n"
        "    fn worker_routes_preflighted_text_and_clipboard_without_payload_loss() {\n"
        "        let events = Arc::new(Mutex::new(Vec::new()));\n"
        "        let factory_events = Arc::clone(&events);\n"
        "        let worker = DesktopWorker::spawn_with_factory(settings(), move || {\n"
        "            Ok(RecordingSession::new(Arc::clone(&factory_events), None))\n"
        "        })\n"
        "        .expect(\"worker spawns\");\n"
        "        let client = worker.client();\n"
        "        wait_for_state(&client, ConnectionState::Connected);\n\n"
        "        client\n"
        "            .submit(WorkerCommand::TypeText {\n"
        "                text: \"A\\n\".to_owned(),\n"
        "            })\n"
        "            .expect(\"accepted\")\n"
        "            .wait(Duration::from_secs(1))\n"
        "            .expect(\"text executed\");\n"
        "        client\n"
        "            .submit(WorkerCommand::SetClipboard {\n"
        "                text: \"clipboard value\".to_owned(),\n"
        "            })\n"
        "            .expect(\"accepted\")\n"
        "            .wait(Duration::from_secs(1))\n"
        "            .expect(\"clipboard sent\");\n\n"
        "        assert_eq!(\n"
        "            *lock_unpoisoned(&events),\n"
        "            vec![\n"
        "                InputEvent::Key(KeyboardKey::Printable('A'), true),\n"
        "                InputEvent::Key(KeyboardKey::Printable('A'), false),\n"
        "                InputEvent::Key(KeyboardKey::Enter, true),\n"
        "                InputEvent::Key(KeyboardKey::Enter, false),\n"
        "                InputEvent::Clipboard(\"clipboard value\".to_owned()),\n"
        "            ]\n"
        "        );\n\n"
        "        lock_unpoisoned(&events).clear();\n"
        "        client\n"
        "            .submit(WorkerCommand::TypeText {\n"
        "                text: \"ok☃\".to_owned(),\n"
        "            })\n"
        "            .expect(\"accepted\")\n"
        "            .wait(Duration::from_secs(1))\n"
        "            .expect_err(\"unsupported text rejected\");\n"
        "        client\n"
        "            .submit(WorkerCommand::SetClipboard {\n"
        "                text: \"a\\0b\".to_owned(),\n"
        "            })\n"
        "            .expect(\"accepted\")\n"
        "            .wait(Duration::from_secs(1))\n"
        "            .expect_err(\"NUL clipboard rejected\");\n"
        "        assert!(lock_unpoisoned(&events).is_empty());\n\n"
        "        worker\n"
        "            .shutdown(Duration::from_secs(1))\n"
        "            .expect(\"worker joins\");\n"
        "    }\n\n"
        "    #[test]\n"
        "    fn worker_publishes_last_valid_inbound_clipboard_snapshot() {\n"
        "        let events = Arc::new(Mutex::new(Vec::new()));\n"
        "        let factory_events = Arc::clone(&events);\n"
        "        let worker = DesktopWorker::spawn_with_factory(settings(), move || {\n"
        "            Ok(RecordingSession::with_clipboard(\n"
        "                Arc::clone(&factory_events),\n"
        "                \"from desktop\",\n"
        "                7,\n"
        "            ))\n"
        "        })\n"
        "        .expect(\"worker spawns\");\n"
        "        let client = worker.client();\n"
        "        wait_for_state(&client, ConnectionState::Connected);\n\n"
        "        let deadline = Instant::now() + Duration::from_secs(1);\n"
        "        let clipboard = loop {\n"
        "            match client.clipboard_snapshot() {\n"
        "                Ok(snapshot) => break snapshot,\n"
        "                Err(DesktopError::ClipboardUnavailable) if Instant::now() < deadline => {\n"
        "                    thread::sleep(Duration::from_millis(1));\n"
        "                }\n"
        "                other => panic!(\"clipboard snapshot unavailable: {other:?}\"),\n"
        "            }\n"
        "        };\n"
        "        assert_eq!(clipboard.text.as_ref(), \"from desktop\");\n"
        "        assert_eq!(clipboard.revision, 1);\n\n"
        "        let mut saw_revision = false;\n"
        "        while let Ok(event) = worker.events().recv_timeout(Duration::from_millis(20)) {\n"
        "            if event.kind == DesktopEventKind::ClipboardRevision { revision: 1 } {\n"
        "                saw_revision = true;\n"
        "                break;\n"
        "            }\n"
        "        }\n"
        "        assert!(saw_revision);\n"
        "        worker\n"
        "            .shutdown(Duration::from_secs(1))\n"
        "            .expect(\"worker joins\");\n"
        "    }\n\n"
        "    #[test]\n"
        "    fn worker_rejects_invalid_coordinate_before_native_mutation() {\n",
    )


def main() -> None:
    patch_input()
    patch_core()
    patch_worker()


if __name__ == "__main__":
    main()
