use serde_json::Value;
use std::io::{self, Write};
use std::sync::{Arc, Mutex};
use tracing::Dispatch;
use tracing_subscriber::fmt::MakeWriter;

#[derive(Clone, Default)]
struct SharedWriter {
    bytes: Arc<Mutex<Vec<u8>>>,
}

impl Write for SharedWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        self.bytes
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl<'writer> MakeWriter<'writer> for SharedWriter {
    type Writer = Self;

    fn make_writer(&'writer self) -> Self::Writer {
        self.clone()
    }
}

pub(crate) fn capture_logs<T>(operation: impl FnOnce() -> T) -> (T, String) {
    let writer = SharedWriter::default();
    let bytes = Arc::clone(&writer.bytes);
    let subscriber = tracing_subscriber::fmt()
        .with_ansi(false)
        .without_time()
        .with_target(false)
        .with_writer(writer)
        .finish();
    let dispatch = Dispatch::new(subscriber);
    let result = tracing::dispatcher::with_default(&dispatch, operation);
    (result, rendered(bytes))
}

pub(crate) fn capture_json_logs<T>(operation: impl FnOnce() -> T) -> (T, Vec<Value>) {
    let writer = SharedWriter::default();
    let bytes = Arc::clone(&writer.bytes);
    let subscriber = tracing_subscriber::fmt()
        .json()
        .with_ansi(false)
        .without_time()
        .with_target(false)
        .with_writer(writer)
        .finish();
    let dispatch = Dispatch::new(subscriber);
    let result = tracing::dispatcher::with_default(&dispatch, operation);
    let records = rendered(bytes)
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("captured tracing record is JSON"))
        .collect();
    (result, records)
}

pub(crate) fn json_logs_contain(records: &[Value], sentinel: &str) -> bool {
    records
        .iter()
        .any(|record| record.to_string().contains(sentinel))
}

fn rendered(bytes: Arc<Mutex<Vec<u8>>>) -> String {
    String::from_utf8(
        bytes
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone(),
    )
    .expect("captured tracing output is UTF-8")
}

pub(crate) fn current_dispatch() -> Dispatch {
    tracing::dispatcher::get_default(Clone::clone)
}
