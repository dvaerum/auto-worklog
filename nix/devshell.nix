{ pkgs, python3 }:

let
  inherit (import ./deps.nix) runtimePythonDeps systemDeps;

  giTypelibPath = pkgs.lib.makeSearchPath "lib/girepository-1.0" [
    pkgs.gtk3
    pkgs.gobject-introspection
  ];

  ldLibraryPath = pkgs.lib.makeLibraryPath [
    pkgs.dbus
    pkgs.glib
  ];
in

pkgs.mkShell {
  name = "auto-worklog-dev";

  buildInputs =
    [ python3 ]
    ++ (systemDeps pkgs)
    ++ (runtimePythonDeps python3.pkgs)
    ++ (with python3.pkgs; [
      pytest
      black
      mypy
      python-lsp-server
      pylint
    ]);

  shellHook = ''
    echo "🔨 Auto Worklog development environment"
    echo "Python version: $(python --version)"
    echo ""
    echo "Available commands:"
    echo "  python -m auto_worklog    - Run the application"
    echo "  pytest                    - Run tests"
    echo "  black .                   - Format code"
    echo "  mypy auto_worklog         - Type check"
    echo ""

    export GI_TYPELIB_PATH="${giTypelibPath}"
    export LD_LIBRARY_PATH="${ldLibraryPath}"
  '';
}
