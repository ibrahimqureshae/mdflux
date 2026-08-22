{ pkgs, lib, ... }:

let
  isLinux = pkgs.stdenv.isLinux;
  isDarwin = pkgs.stdenv.isDarwin;
in
{
  # The lockfile pins every package below. No credentials are declared here: keep
  # provider keys in the caller's environment or a local, untracked secret store.
  packages = with pkgs;
    [
      nodejs_20
      rustc
      cargo
      python312
      uv
      shellcheck
      pkg-config
      openssl
      git
      gnumake
      gcc
      curl
      jq
    ]
    ++ lib.optionals isLinux [
      gtk3
      webkitgtk_4_1
      glib-networking
      libsoup_3
      patchelf
    ]
    ++ lib.optionals isDarwin [
      darwin.apple_sdk.frameworks.Security
      darwin.apple_sdk.frameworks.SystemConfiguration
    ];

  env = {
    RUST_BACKTRACE = "1";
    # Do not set HOME, NIX_PATH, API keys, or release-output paths here.
    # Build outputs remain in the checkout's normal ignored directories.
  };

  scripts = {
    dev.exec = "scripts/dev/dev.sh";
    check.exec = "scripts/dev/check.sh";
    "test-sidecar".exec = "scripts/dev/test-sidecar.sh";
    "build-linux-lite".exec = "scripts/dev/build-linux.sh lite";
    "build-linux-full".exec = "scripts/dev/build-linux.sh full";
  };

  enterShell = ''
    echo "MDFlux devenv: dev, check, test-sidecar, build-linux-lite, build-linux-full"
    if [ "${if isLinux then "1" else "0"}" != "1" ]; then
      echo "Linux archive commands are unavailable on this host; ordinary frontend and Rust workflows remain available."
    fi
  '';

  enterTest = ''
    scripts/dev/validate-config.sh
    scripts/dev/check.sh
  '';
}
