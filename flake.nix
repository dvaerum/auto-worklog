{
  description = "Auto Worklog - Automatic work time tracking with screen lock detection";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python313;

        auto-worklog = import ./nix/package.nix {
          inherit pkgs;
          python3Packages = python.pkgs;
        };

      in
      {
        packages = {
          default = auto-worklog;
          auto-worklog = auto-worklog;
        };

        devShells.default = import ./nix/devshell.nix {
          inherit pkgs;
          python3 = python;
        };

        apps.default = {
          type = "app";
          program = "${auto-worklog}/bin/auto-worklog";
        };

        formatter = pkgs.nixpkgs-fmt;
      }
    )
    // {
      homeManagerModules.default = import ./homeManagerModules/default.nix;
      homeManagerModules.auto-worklog = import ./homeManagerModules/default.nix;
    };
}
