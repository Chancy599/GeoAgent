from __future__ import annotations

from geoagent.orchestration.runner import _clean_finish_args, _issue_list


def test_finish_args_strip_leaked_provider_markup() -> None:
    args = {
        "summary": 'Figure produced.</summary>\n<parameter name="unresolved">["line too thin", "arc extent"]</parameter>\n</invoke>',
        "status": "",
    }
    cleaned = _clean_finish_args(args)
    assert cleaned["summary"] == "Figure produced."
    assert _issue_list(cleaned["unresolved"]) == ["line too thin", "arc extent"]


def test_finish_args_keep_clean_values_untouched() -> None:
    args = {"summary": "compiled v1, score 0.95", "status": "success", "unresolved": ["a"]}
    cleaned = _clean_finish_args(args)
    assert cleaned == args


def test_issue_list_accepts_prose_dict_and_json() -> None:
    assert _issue_list("single issue") == ["single issue"]
    assert _issue_list('["a", "b"]') == ["a", "b"]
    assert _issue_list({"issue": "x"})[0].startswith('{"issue"')
    assert _issue_list(None) == []
