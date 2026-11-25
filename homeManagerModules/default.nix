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

  # Hooks and the project mapping travel as one JSON file; the service only gets --config
  # when something is actually configured.
  hookEvents = filterAttrs (_: commands: commands != [ ]) cfg.hooks;

  configFile = pkgs.writeText "auto-worklog-config.json" (
    builtins.toJSON {
      hooks = hookEvents;
      hook_timeout = cfg.hookTimeout;
      summary = {
        rules = map (
          rule:
          filterAttrs (_: value: value != null) {
            inherit (rule) project description tag;
            toggl_project = rule.togglProject;
          }
        ) cfg.summary.rules;
        comments = cfg.summary.comments;
        ignore_descriptions = cfg.summary.ignoreDescriptions;
      }
      // optionalAttrs (cfg.summary.defaultProject != null) {
        default_project = cfg.summary.defaultProject;
      };
    }
  );

  hookArgs = optionalString (hookEvents != { }) " --config ${configFile}";

  execCommand = "${cfg.package}/bin/auto-worklog ${autoAnswerArgs} ${logArgs}${hookArgs}";

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

    hooks = mkOption {
      type = types.submodule {
        options = genAttrs [ "screen_locked" "screen_unlocked" "day_summary" ] (
          event:
          mkOption {
            type = types.listOf (types.listOf types.str);
            default = [ ];
            description = "Commands to run on the ${event} event, each an argument list (no shell).";
          }
        );
      };
      default = { };
      example = literalExpression ''
        {
          # register each day's time in BIT; the cookie comes from the service environment
          day_summary = [ [ "''${pkgs.bit-client}/bin/bit" "sync" ] ];
        }
      '';
      description = ''
        Commands run when something happens, so other tools can react without auto-worklog
        knowing them. Each command is an argument list started without a shell; the event is
        piped to it as JSON on stdin (and named in AUTO_WORKLOG_EVENT). Commands run one after
        another in the background, a failing or hanging one is logged and skipped, and their
        output goes to the journal. They inherit the service environment, so secrets such as a
        cookie file can come from `environmentFile`.

        Events:
          screen_locked, screen_unlocked - {"state", "at"}
          day_summary - {"days": [{"date", "complete", "entries": [{"project", "minutes",
            "comment"}], "unmapped": [...]}]}: the day's Toggl entries mapped to projects and
            merged into one total per project (see `summary`). Sent after every screen lock
            (for today and the last working day) and on the first unlock of the day, so a
            consumer must be idempotent; `bit sync` is.
      '';
    };

    hookTimeout = mkOption {
      type = types.ints.positive;
      default = 60;
      description = "Seconds a hook command may run before it is killed.";
    };

    summary = {
      rules = mkOption {
        type = types.listOf (
          types.submodule {
            options = {
              project = mkOption {
                type = types.str;
                description = "The project label sent to hooks for entries this rule matches.";
              };
              togglProject = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Match entries on this Toggl project (ignoring case).";
              };
              description = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Match entries whose description matches this regular expression.";
              };
              tag = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Match entries carrying this Toggl tag (ignoring case).";
              };
            };
          }
        );
        default = [ ];
        example = literalExpression ''
          [
            { togglProject = "Alpha"; project = "10"; }
            { description = "^support"; project = "30"; }
          ]
        '';
        description = ''
          How Toggl entries map to project labels for the day_summary event. The first rule
          whose conditions all hold wins. Entries of the same label are merged into one total
          for the day: a whole day on one project is one entry, task switching gives one entry
          per project.
        '';
      };

      defaultProject = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = ''
          The label for entries no rule matches. Without it such entries are listed under
          `unmapped` in the event and not counted.
        '';
      };

      comments = mkOption {
        type = types.enum [
          "descriptions"
          "none"
        ];
        default = "descriptions";
        description = "Whether a merged entry's comment lists the distinct descriptions.";
      };

      ignoreDescriptions = mkOption {
        type = types.listOf types.str;
        default = [ "Working" ];
        description = "Descriptions left out of comments; Working is what auto-worklog itself creates.";
      };
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
        # Back off instead of restarting every restartDelay seconds forever: one
        # failure mode ran 2,334 restarts in 14 h (needs systemd >= 254).
        RestartSteps = 5;
        RestartMaxDelaySec = 300;
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
