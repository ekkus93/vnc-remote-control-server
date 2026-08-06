#!/usr/bin/env python3
"""Run the committed framebuffer measurement with its exact contract."""

import subprocess

COMMAND = [
    "cargo", "test", "--locked",
    "--package", "controller-api",
    "--test", "framebuffer_measurement",
    "measure_representative_frame_pipeline",
    "--", "--ignored", "--exact", "--nocapture", "--test-threads=1",
]

subprocess.run(COMMAND, check=True)
