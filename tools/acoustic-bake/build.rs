// Links against the Steam Audio SDK's libphonon.so (not vendored; fetched by
// bench/m0/spike6/fetch-sdk.sh). Override the location with STEAM_AUDIO_SDK.
fn main() {
    let sdk = std::env::var("STEAM_AUDIO_SDK")
        .unwrap_or_else(|_| "/home/akram/code/or3/data/raw/steam-audio/sdk/steamaudio".into());
    let lib = format!("{sdk}/lib/linux-x64");
    println!("cargo:rerun-if-env-changed=STEAM_AUDIO_SDK");
    println!("cargo:rustc-link-search=native={lib}");
    println!("cargo:rustc-link-lib=dylib=phonon");
    println!("cargo:rustc-link-arg=-Wl,-rpath,{lib}");
}
