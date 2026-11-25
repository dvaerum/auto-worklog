# Hooks: telling other tools what happened

Auto-worklog can run commands when things happen, so other tools can react without
auto-worklog (or the tool) having any code for the other. A hook is an argument list (no
shell); the event is piped to it as JSON on stdin and its output goes to the journal.

```nix
services.auto-worklog = {
  hooks.day_summary = [ [ "${pkgs.bit-client}/bin/bit" "sync" ] ];   # register the day in BIT
  summary.rules = [
    { togglProject = "Alpha"; project = "10"; }
    { description = "^support"; project = "30"; }
    { tag = "internal"; project = "30"; }
  ];
  summary.defaultProject = null;     # entries no rule matches are listed, not sent
  environmentFile = "/run/secrets/auto-worklog.env";   # holds BIT_COOKIE_FILE=... for `bit`
};
```

Without Nix, pass `--config file.json` (or `AUTO_WORKLOG_CONFIG`):

```json
{"hooks": {"day_summary": [["bit", "sync"]]},
 "hook_timeout": 60,
 "summary": {"rules": [{"toggl_project": "Alpha", "project": "10"}],
             "default_project": null, "comments": "descriptions",
             "ignore_descriptions": ["Working"]}}
```

A typo in an event name or a key fails at startup with a message listing what is valid.

## Events

Every event is one JSON document on stdin, with `AUTO_WORKLOG_EVENT` and `AUTO_WORKLOG_HOST`
in the environment:

```json
{"version": 1, "event": "day_summary", "time": "2026-11-25T16:02:11+01:00", "host": "laptop", ...}
```

| event | extra fields | sent |
|---|---|---|
| `screen_locked` | `state`, `at` | on every lock |
| `screen_unlocked` | `state`, `at` | on every unlock |
| `day_summary` | `days` (below) | after every lock, for today **and** the last working day; and on the first unlock of the day for the last working day |

### `day_summary`

```json
{"days": [{"date": "2026-11-25", "complete": false,
           "entries": [{"project": "10", "minutes": 270, "comment": "planning; review"},
                       {"project": "30", "minutes": 75, "comment": "support ticket 12"}],
           "unmapped": [{"description": "lunch chat", "project": "Social", "minutes": 20}]}]}
```

This is the neutral format `bit sync` reads (`days[].entries[]` with `project`, `minutes`,
`comment`); extra fields such as `complete` and `unmapped` are ignored by it, so the two
programs fit together with no glue.

**Mapping and merging.** Each Toggl entry is mapped to a project *label* by the first rule
whose conditions all hold (`togglProject` and `tag` ignore case, `description` is a regular
expression searched in the text); entries no rule matches use `defaultProject`, or are listed
under `unmapped` and left out of `entries`. Entries with the same label are merged into one total
for the day, rounded to the minute once per total. One project all day gives one entry; task
switching across projects gives one entry per project. Entries are clipped to the day at
midnight, and an entry still running counts up to now. The comment lists the distinct
descriptions (`comments = "none"` leaves it empty; `Working`, which auto-worklog creates
itself, is left out).

**Why it is sent so often.** The day's end cannot be known, so a summary follows every lock and
the consumer is expected to be idempotent (`bit sync` is: the same document twice changes
nothing). The last working day is re-sent on each lock as well, so a correction made after the
first unlock (fixing a forgotten timer) reaches the consumer. The last working day is the day
of the last lock before today, so weekends and holidays are handled.

**Forgotten timers.** If a timer that started before today is still running, no summary is sent
at all (it would be counted until midnight and sent as a wrong total); a warning says which
entry. The next lock after it has been stopped sends the right totals.

## Behaviour of hooks

* Hooks never block auto-worklog: events are queued and run one after another on a worker
  thread. A failing, missing or hanging command (killed after `hook_timeout`) is logged as a
  warning and skipped; the rest still run.
* Queued `day_summary` requests for the same day collapse into one, and the Toggl lookup only
  happens if a `day_summary` hook is configured.
* In offline mode (no Toggl token) there is no `day_summary`.
* Stdout of a hook is logged at info level, so `bit sync`'s report is in the journal.

## Trying it

`auto-worklog --token-file … --config config.json --print-day-summary yesterday` prints the
`day_summary` document for a day (`today`, `yesterday` or `YYYY-MM-DD`) and exits, so the
mapping can be checked and the consumer previewed:

```console
$ auto-worklog --token-file ~/toggl --config config.json --print-day-summary yesterday | bit sync --dry-run
```
