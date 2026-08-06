use crate::input::InputSink;
use libvnc_adapter::{
    NativeClient, NativeClipboard, NativeDisplayInfo, NativeError, NativeFramebuffer, PollOutcome,
};
use remote_desktop_core::{Coordinate, KeyboardKey};
use std::time::Duration;

pub(super) trait WorkerSession {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError>;
    fn request_full_refresh(&mut self) -> Result<(), NativeError>;
    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError>;
    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError>;
    fn clipboard(&self) -> Result<NativeClipboard, NativeError>;
    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError>;
    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError>;
    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError>;
}

impl WorkerSession for NativeClient {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        NativeClient::poll(self, timeout)
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        NativeClient::request_full_refresh(self)
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        NativeClient::display_info(self)
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        NativeClient::framebuffer(self)
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        NativeClient::clipboard(self)
    }

    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {
        NativeClient::send_pointer(self, coordinate, button_mask)
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        NativeClient::send_key(self, key, pressed)
    }

    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
        NativeClient::send_clipboard(self, text)
    }
}

impl<T: WorkerSession> InputSink for T {
    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {
        WorkerSession::send_pointer(self, coordinate, button_mask)
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        WorkerSession::send_key(self, key, pressed)
    }
}
