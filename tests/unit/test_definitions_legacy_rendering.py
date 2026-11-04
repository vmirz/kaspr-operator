"""Apps whose components are delivered one ConfigMap each render as before bundles existed.

The goldens were rendered by the release before definitions bundles (see
legacy_rendering.py). A difference in a StatefulSet would roll such apps on an operator
upgrade. Component ConfigMaps differ in one way only: their hash annotation is now the
component's own hash; the release before computed it before the annotation existed.
"""

import copy
import json

import pytest

from legacy_rendering import GOLDEN_DIR, _operator_settings, build_app, load_cases, render

CASES = load_cases()
HASH_ANNOTATION = "kaspr.io/resource-hash"


def without_hash_annotation(config_maps):
    config_maps = copy.deepcopy(config_maps)
    for config_map in config_maps:
        config_map["metadata"]["annotations"].pop(HASH_ANNOTATION)
    return config_maps


@pytest.mark.parametrize(
    "case,app_doc,components", CASES, ids=[case for case, _, _ in CASES]
)
def test_components_mode_renders_as_before(case, app_doc, components):
    golden = json.loads((GOLDEN_DIR / f"{case}.json").read_text())

    rendered = render(app_doc, components)

    assert rendered["statefulSet"] == golden["statefulSet"]
    assert without_hash_annotation(rendered["configMaps"]) == without_hash_annotation(
        golden["configMaps"]
    )


@pytest.mark.parametrize(
    "case,app_doc,components", CASES, ids=[case for case, _, _ in CASES]
)
def test_a_component_config_map_carries_its_components_hash(case, app_doc, components):
    with _operator_settings():
        app = build_app(app_doc, components)
        mismatched = [
            component.config_map_name
            for component in [*app.agents, *app.webviews, *app.tables, *app.tasks]
            if component.config_map.metadata.annotations[HASH_ANNOTATION] != component.hash
        ]

    assert mismatched == []


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
