import json

import pytest

from auto_worklog.config import ConfigError, load_config, parse_config
from auto_worklog.worklog import Rule

FULL = {
    "hooks": {
        "day_summary": [["bit", "sync"], ["logger", "-t", "x"]],
        "screen_locked": [["notify-send", "locked"]],
    },
    "hook_timeout": 30,
    "summary": {
        "rules": [
            {"toggl_project": "Alpha", "project": "10"},
            {"description": "^support", "project": "30"},
            {"tag": "internal", "project": "30"},
        ],
        "default_project": "99",
        "comments": "none",
        "ignore_descriptions": ["Working", "misc"],
    },
}


def test_a_full_config_is_understood():
    config = parse_config(FULL)

    assert config.hooks.commands["day_summary"] == [["bit", "sync"], ["logger", "-t", "x"]]
    assert config.hooks.commands["screen_locked"] == [["notify-send", "locked"]]
    assert config.hooks.timeout == 30
    assert config.mapping.rules == (
        Rule(project="10", toggl_project="Alpha"),
        Rule(project="30", description="^support"),
        Rule(project="30", tag="internal"),
    )
    assert (config.mapping.default_project, config.mapping.comments) == ("99", "none")
    assert config.mapping.ignore_descriptions == ("Working", "misc")


def test_an_empty_config_means_no_hooks_and_default_mapping():
    config = parse_config({})
    assert config.hooks.commands == {} and config.hooks.timeout == 60
    assert config.mapping.rules == () and config.mapping.default_project is None
    assert config.mapping.ignore_descriptions == ("Working",)


@pytest.mark.parametrize(
    "data, message",
    [
        ([], "object"),
        ({"hookz": {}}, "hookz"),
        ({"hooks": {"day_sumary": [["x"]]}}, "day_sumary.*day_summary"),
        ({"hooks": {"day_summary": ["bit sync"]}}, "list of strings"),
        ({"hooks": {"day_summary": [[]]}}, "empty"),
        ({"hooks": {"day_summary": [["bit", 3]]}}, "list of strings"),
        ({"hooks": {"day_summary": "bit sync"}}, "list"),
        ({"hook_timeout": 0}, "hook_timeout"),
        ({"hook_timeout": "soon"}, "hook_timeout"),
        ({"summary": {"rules": [{"project": "1"}]}}, "condition"),
        ({"summary": {"rules": [{"description": "[", "project": "1"}]}}, "pattern"),
        ({"summary": {"rules": [{"toggl_project": "A"}]}}, "project"),
        ({"summary": {"rules": [{"toggl_project": "A", "project": "1", "colour": "red"}]}}, "colour"),
        ({"summary": {"comments": "loud"}}, "comments"),
        ({"summary": {"nope": 1}}, "nope"),
    ],
)
def test_mistakes_are_reported_with_a_pointer_to_the_problem(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_load_reads_json_from_a_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(FULL))
    assert load_config(path).hooks.commands["screen_locked"] == [["notify-send", "locked"]]


def test_load_reports_a_missing_or_broken_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(broken)
