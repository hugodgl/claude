import pytest

from core.jsonutil import extract_json, strip_think


def test_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_and_text_around():
    text = 'Voici :\n```json\n{"score": 7, "ok": true}\n```\nmerci'
    assert extract_json(text) == {"score": 7, "ok": True}


def test_think_block_and_trailing_comma():
    text = '<think>bla</think>\nRésultat {"a": [1, 2,], "b": "x",}'
    assert extract_json(text) == {"a": [1, 2], "b": "x"}


def test_array():
    assert extract_json("réponse: [1, 2, 3]") == [1, 2, 3]


def test_strip_think():
    assert strip_think("<think>x</think> ok") == "ok"


def test_no_json():
    with pytest.raises(ValueError):
        extract_json("rien du tout")
