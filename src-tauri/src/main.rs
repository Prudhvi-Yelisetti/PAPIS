// Prevents a second console window from opening on Windows (no-op on Linux)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    papis_lib::run();
}