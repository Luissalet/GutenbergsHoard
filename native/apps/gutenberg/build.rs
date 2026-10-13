// Modified for Gutenberg: detached engine, own document and product identity.
//! Windows only: embed the app icon and version info (VERSIONINFO) into `gutenberg.exe`, so it
//! shows in Explorer, the taskbar, the Start menu and Alt-Tab.
//!
//! On every other target this does nothing. A missing resource compiler is a warning, so a
//! cross-compile from macOS or Linux still links, unless `GUTENBERG_REQUIRE_WINRES=1` turns it
//! into an error (for release builds).

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=../../assets/app-icon/gutenberg.ico");
    println!("cargo:rerun-if-env-changed=GUTENBERG_REQUIRE_WINRES");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    let mut res = winresource::WindowsResource::new();
    res.set_icon("../../assets/app-icon/gutenberg.ico")
        .set("ProductName", "Gutenberg")
        .set("FileDescription", "Gutenberg page layout")
        .set("CompanyName", "Gutenberg Hoard")
        .set("LegalCopyright", "Copyright (c) the DesignCraft authors. MIT OR Apache-2.0. See native/NOTICE.")
        .set("OriginalFilename", "gutenberg.exe")
        .set("InternalName", "gutenberg");
    if let Err(e) = res.compile() {
        if std::env::var_os("GUTENBERG_REQUIRE_WINRES").is_some() {
            eprintln!("embedding Windows resources failed: {e}");
            std::process::exit(1);
        }
        println!("cargo:warning=gutenberg.exe built without icon/version resources: {e}");
    }
}
