{
  version = (builtins.fromTOML (builtins.readFile ../pyproject.toml)).project.version;

  runtimePythonDeps = ps: with ps; [
    dbus-python
    toggl-cli
    pendulum
    sortedcontainers
    pygobject3
    requests
  ];

  systemDeps = pkgs: with pkgs; [
    gobject-introspection
    gtk3
    dbus
    glib
  ];
}
