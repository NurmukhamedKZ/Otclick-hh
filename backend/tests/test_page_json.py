import json

import pytest


def test_find_state_reads_entity_encoded_inline_json():
    from app.hh.page_json import find_state

    raw = '<script>window.x = {&#34;vacancySearchResult&#34;:{&#34;totalResults&#34;:229}}</script>'
    assert find_state(raw, "vacancySearchResult") == {"totalResults": 229}


def test_find_state_reads_plain_json_without_double_unescaping():
    from app.hh.page_json import find_state

    raw = '{"vacancySearchResult":{"name":"a &amp; b"}}'
    # Already plain: the literal &amp; must survive, not become "&".
    assert find_state(raw, "vacancySearchResult") == {"name": "a &amp; b"}


def test_find_state_raises_when_key_absent():
    from app.hh.page_json import find_state

    with pytest.raises(ValueError, match="nope"):
        find_state("<html></html>", "nope")


def test_find_state_reads_array_valued_key():
    """The resume list on the applicant page is an array, not an object."""
    from app.hh.page_json import find_state

    raw = '{"applicantResumes":[{"hash":"a","title":"Dev"},{"hash":"b"}]}'
    assert find_state(raw, "applicantResumes") == [
        {"hash": "a", "title": "Dev"},
        {"hash": "b"},
    ]


def test_find_balanced_object_handles_nested_arrays_and_objects():

    from app.hh.page_json import find_balanced_object

    text = '{"a":[{"x":1},{"y":[1,2,3]}],"b":2}'
    assert json.loads(find_balanced_object(text, 0))["b"] == 2