use std::env;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

fn run(command: &mut Command, description: &str) -> Output {
    let output = command
        .output()
        .unwrap_or_else(|error| panic!("failed to execute {description}: {error}"));
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        panic!("{description} failed: {stderr}");
    }
    output
}

fn pkg_config(arguments: &[&str], description: &str) -> Output {
    run(Command::new("pkg-config").args(arguments), description)
}

fn main() {
    println!("cargo:rerun-if-changed=native/vnc_shim.c");
    println!("cargo:rerun-if-changed=native/vnc_shim.h");

    let target_os = env::var("CARGO_CFG_TARGET_OS").expect("Cargo must set CARGO_CFG_TARGET_OS");
    assert_eq!(
        target_os, "linux",
        "libvnc-adapter v0.1 currently supports Linux only"
    );

    let version_output = pkg_config(
        &["--modversion", "libvncclient"],
        "LibVNCClient version discovery",
    );
    let version = String::from_utf8(version_output.stdout)
        .expect("pkg-config version must be UTF-8")
        .trim()
        .to_owned();
    assert!(!version.is_empty(), "pkg-config returned an empty version");
    println!("cargo:rustc-env=VRC_LIBVNCCLIENT_VERSION={version}");

    let cflags_output = pkg_config(
        &["--cflags", "libvncclient"],
        "LibVNCClient compiler flag discovery",
    );
    let cflags =
        String::from_utf8(cflags_output.stdout).expect("pkg-config compiler flags must be UTF-8");

    let out_dir = PathBuf::from(env::var_os("OUT_DIR").expect("Cargo must set OUT_DIR"));
    let object = out_dir.join("vnc_shim.o");
    let archive = out_dir.join("libvrc_vnc_shim.a");

    let mut compiler = Command::new(env::var_os("CC").unwrap_or_else(|| OsString::from("cc")));
    compiler
        .args([
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-fPIC",
            "-I",
            "native",
            "-c",
            "native/vnc_shim.c",
            "-o",
        ])
        .arg(&object);
    for flag in cflags.split_whitespace() {
        compiler.arg(flag);
    }
    run(&mut compiler, "native LibVNCClient shim compilation");

    let mut archiver = Command::new(env::var_os("AR").unwrap_or_else(|| OsString::from("ar")));
    archiver.args(["crs"]).arg(&archive).arg(&object);
    run(&mut archiver, "native LibVNCClient shim archive creation");

    let link_output = pkg_config(
        &["--libs-only-L", "libvncclient"],
        "LibVNCClient link path discovery",
    );
    let link_paths =
        String::from_utf8(link_output.stdout).expect("pkg-config link paths must be UTF-8");
    for flag in link_paths.split_whitespace() {
        if let Some(path) = flag.strip_prefix("-L") {
            println!("cargo:rustc-link-search=native={path}");
        }
    }

    println!("cargo:rustc-link-search=native={}", display_path(&out_dir));
    println!("cargo:rustc-link-lib=static=vrc_vnc_shim");
    println!("cargo:rustc-link-lib=vncclient");
}

fn display_path(path: &Path) -> String {
    path.to_str()
        .expect("native build output path must be valid UTF-8")
        .to_owned()
}
