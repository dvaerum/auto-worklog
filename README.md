# Auto Worklog

Automatic work time tracking via screen lock/unlock detection on Linux, with optional Toggl integration and desktop notifications.

## How it works

The service listens for D-Bus screen lock/unlock signals and triggers Toggl time entries accordingly. Every lock/unlock event is persisted to `~/.cache/auto-worklog/` so state survives restarts.

### Triggers

| Event | What happens |
|---|---|
| **First unlock of the day** | Detects no Toggl entry is running. Asks (or auto-starts) a new "Working" entry backdated to the unlock time minus 5 min. |
| **Forgot to stop yesterday** | A Toggl entry from a previous day is still running. Asks (or auto-stops) it at the last screen-lock time from that day. Then proceeds with the first-unlock flow above. |
| **Unlock after lock** | Screen unlocked but no Toggl entry is running (you stopped it manually, or it was stopped by another trigger). Asks (or auto-starts) a new entry from the unlock time. Only fires after the first unlock of the day. |
| **Lunch break** | After unlocking between 11:40 and 13:45, checks for a lock/unlock gap of 10-35 min. If found, asks (or auto-splits) the current entry: stops at break start, starts a new one at break end. |

Every trigger shows a desktop notification. Without auto-answer the notification has a button and waits for your response. With auto-answer it acts immediately and shows an informational notification instead.

### Auto-answer modes

Each mode controls whether its trigger acts automatically or asks first:

| Mode | Trigger it controls |
|---|---|
| `forgot_to_stop_yesterday` | Stop yesterday's still-running entry |
| `first_unlock_today` | Start a new entry on first unlock |
| `unlock` | Start a new entry on subsequent unlocks |
| `lunch_break` | Split the current entry around the detected break |

## Usage

```bash
auto-worklog [OPTIONS]
```

| Option | Env var | Default | Description |
|---|---|---|---|
| `--token` | `AUTO_WORKLOG_TOGGL_TOKEN` | | Toggl API token |
| `--token-file` | `AUTO_WORKLOG_TOGGL_TOKEN_FILE` | | Path to file containing the token |
| `--auto-answer` | `AUTO_WORKLOG_AUTO_ANSWER` | | Auto-answer modes (comma-separated) |
| `--log-level` | `AUTO_WORKLOG_LOG_LEVEL` | `INFO` | Console (stderr) level; `OFF` to disable |
| `--log-file` | `AUTO_WORKLOG_LOG_FILE` | | Path to log file (always with timestamps) |
| `--log-file-level` | `AUTO_WORKLOG_LOG_FILE_LEVEL` | `DEBUG` | File log level |

`--token` and `--token-file` are mutually exclusive. CLI args take precedence over env vars.

## Home Manager

```nix
services.auto-worklog = {
  enable = true;
  tokenFile = config.sops.secrets.toggl-token.path;  # or environmentFile for KEY=VALUE
  autoAnswer = { forgotToStopYesterday = true; firstUnlockToday = true; unlock = true; lunchBreak = true; };
  logLevel = "INFO";          # OFF to disable console
  logFile = "/tmp/auto-worklog.log";
  logFileLevel = "DEBUG";
};
```

## License

MIT
