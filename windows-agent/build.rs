fn main() {
    println!("cargo:rustc-env=NUSCAPE_DEFAULT_API_BASE=https://nuscape-backend-dexterjk86.replit.app");
    tauri_build::build();
}

