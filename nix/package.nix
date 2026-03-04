{
  pkgs,
  python3Packages,
}: let
  inherit (import ./deps.nix) version runtimePythonDeps systemDeps;

  ldLibraryPath = pkgs.lib.makeLibraryPath [
    pkgs.dbus
    pkgs.glib
  ];
in
  python3Packages.buildPythonApplication {
    pname = "auto-worklog";
    inherit version;

    src = pkgs.lib.sources.cleanSource ../.;

    format = "pyproject";

    nativeBuildInputs = with python3Packages; [
      setuptools
      wheel
    ];

    propagatedBuildInputs = (runtimePythonDeps python3Packages) ++ (systemDeps pkgs);

    buildInputs = [
      pkgs.dbus
      pkgs.glib
    ];

    postFixup = ''
      wrapProgram $out/bin/auto-worklog \
        --prefix GI_TYPELIB_PATH : "$GI_TYPELIB_PATH" \
        --prefix LD_LIBRARY_PATH : "${ldLibraryPath}"
    '';

    doCheck = true;

    # toggl-cli is provided via propagatedBuildInputs but the PyPI name
    # differs from the Nix attribute name
    dontCheckRuntimeDeps = true;

    meta = with pkgs.lib; {
      description = "Automatic work time tracking with screen lock detection";
      license = licenses.mit;
      maintainers = [];
      platforms = platforms.linux;
    };
  }
