"""Apps whose components are delivered one ConfigMap each render as before bundles existed.

The goldens were rendered by the release before definitions bundles (see
legacy_rendering.py). A difference here would roll such apps on an operator upgrade.
"""

import json

import pytest

from legacy_rendering import GOLDEN_DIR, _operator_settings, build_app, load_cases, render

CASES = load_cases()


@pytest.mark.parametrize(
    "case,app_doc,components", CASES, ids=[case for case, _, _ in CASES]
)
def test_components_mode_renders_as_before(case, app_doc, components):
    golden = json.loads((GOLDEN_DIR / f"{case}.json").read_text())

    assert render(app_doc, components) == golden


def test_every_case_has_a_golden():
    assert {path.stem for path in GOLDEN_DIR.glob("*.json")} == {case for case, _, _ in CASES}


def test_joins_change_nothing_in_components_mode():
    """The combined app has a KasprJoin; in components mode it is not delivered."""
    case, app_doc, components = next(c for c in CASES if c[0] == "every-component")
    with _operator_settings():
        app = build_app(app_doc, components)
        env = {e.name for e in app.stateful_set.spec.template.spec.containers[0].env}

    assert app.joins, "the combined app should hold the example join"
    assert "JOINS_HASH" not in env
