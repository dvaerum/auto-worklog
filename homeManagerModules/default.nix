{
  config,
  lib,
  pkgs,
  ...
}:

with lib;

let
  cfg = config.services.auto-worklog;

  # Auto-answer flags configuration
  autoAnswerFlags = {
    forgotToStopYesterday = "forgot_to_stop_yesterday";
    firstUnlockToday = "first_unlock_today";
    unlock = "unlock";
    lunchBreak = "lunch_break";
  };

  # Convert enabled auto-answer options to command line arguments
  enabledAutoAnswers =
    optionals cfg.autoAnswer.forgotToStopYesterday [ autoAnswerFlags.forgotToStopYesterday ]
    ++ optionals cfg.autoAnswer.firstUnlockToday [ autoAnswerFlags.firstUnlockToday ]
    ++ optionals cfg.autoAnswer.unlock [ autoAnswerFlags.unlock ]
    ++ optionals cfg.autoAnswer.lunchBreak [ autoAnswerFlags.lunchBreak ];

  autoAnswerArgs = optionalString (
    enabledAutoAnswers != [ ]
  ) "--auto-answer ${concatStringsSep " " enabledAutoAnswers}";

  logArgs =
    "--log-level ${cfg.logLevel}"
    + optionalString (
      cfg.logFile != null
    ) " --log-file ${cfg.logFile} --log-file-level ${cfg.logFileLevel}";

  execCommand = "${cfg.package}/bin/auto-worklog ${autoAnswerArgs} ${logArgs}";

in
{
  options.services.auto-worklog = {
    enable = mkEnableOption "Auto Worklog service for automatic work time tracking";

    package = mkOption {
      type = types.package;
      default = pkgs.callPackage ../nix/package.nix { };
      defaultText = literalExpression "pkgs.auto-worklog";
      description = "The auto-worklog package to use.";
    };

    tokenFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      example = literalExpression "config.sops.secrets.toggl-token.path";
      description = ''
        Path to a file containing the Toggl API token.
        The file should contain only the token (trailing whitespace is stripped).
        The file is read at runtime so the token never enters the Nix store.

        Sets AUTO_WORKLOG_TOGGL_TOKEN_FILE for the service, which the
        application reads via --token-file.

        Works with sops-nix:
          sops.secrets.toggl-token = { };
          services.auto-worklog.tokenFile = config.sops.secrets.toggl-token.path;

        Works with agenix:
          age.secrets.toggl-token.file = ./secrets/toggl-token.age;
          services.auto-worklog.tokenFile = config.age.secrets.toggl-token.path;
      '';
    };

    autoAnswer = {
      forgotToStopYesterday = mkOption {
        type = types.bool;
        default = true;
        description = "Automatically handle 'forgot to stop yesterday' prompts.";
      };

      firstUnlockToday = mkOption {
        type = types.bool;
        default = true;
        description = "Automatically handle first unlock of the day.";
      };

      unlock = mkOption {
        type = types.bool;
        default = true;
        description = "Automatically handle unlock events.";
      };

      lunchBreak = mkOption {
        type = types.bool;
        default = true;
        description = "Automatically detect and handle lunch breaks.";
      };
    };

    environmentFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      example = literalExpression "config.sops.secrets.auto-worklog-env.path";
      description = ''
        Path to an environment file loaded by systemd (EnvironmentFile=).
        The file should contain KEY=VALUE pairs, one per line.
        This is read at runtime so secrets never enter the Nix store.

        Example file contents:
          AUTO_WORKLOG_TOGGL_TOKEN=your-token-here

        Note: tokenFile and environmentFile with AUTO_WORKLOG_TOGGL_TOKEN
        cannot both provide a token — the application enforces that --token
        and --token-file are mutually exclusive.
      '';
    };

    logLevel = mkOption {
      type = types.enum [
        "DEBUG"
        "INFO"
        "WARNING"
        "ERROR"
        "CRITICAL"
        "OFF"
      ];
      default = "INFO";
      description = ''
        Console (stderr/journal) log level.
        Set to "OFF" to disable console logging entirely.
      '';
    };

    logFile = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "/tmp/auto-worklog.log";
      description = ''
        Path to a log file.  Always includes timestamps regardless of
        whether the service runs under systemd.  Parent directories are
        created automatically.  null disables file logging.
      '';
    };

    logFileLevel = mkOption {
      type = types.enum [
        "DEBUG"
        "INFO"
        "WARNING"
        "ERROR"
        "CRITICAL"
      ];
      default = "DEBUG";
      description = "Log level for the file handler (independent of console level).";
    };

    restartDelay = mkOption {
      type = types.int;
      default = 15;
      description = "Delay in seconds before restarting the service after failure.";
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = !(cfg.tokenFile != null && cfg.environmentFile != null);
        message = ''
          services.auto-worklog: tokenFile and environmentFile cannot both be set.
          Use one or the other to provide the Toggl token.
        '';
      }
    ];

    home.packages = [ cfg.package ];

    systemd.user.services.auto-worklog = {
      Unit = {
        Description = "Auto Worklog - Automatic work time tracking";
        After = [ "graphical-session.target" ];
        PartOf = [ "graphical-session.target" ];
      };

      Service = {
        Type = "simple";
        ExecStart = execCommand;
        Restart = "always";
        RestartSec = cfg.restartDelay;
      }
      // optionalAttrs (cfg.tokenFile != null) {
        Environment = [ "AUTO_WORKLOG_TOGGL_TOKEN_FILE=${cfg.tokenFile}" ];
      }
      // optionalAttrs (cfg.environmentFile != null) {
        EnvironmentFile = cfg.environmentFile;
      };

      Install = {
        WantedBy = [ "graphical-session.target" ];
      };
    };
  };
}
