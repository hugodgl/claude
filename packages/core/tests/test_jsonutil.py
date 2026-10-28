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


# ----------------------------------------------------------------------------------------------
# Revue croisée : cas limites
# ----------------------------------------------------------------------------------------------
def test_scalars_are_not_json_answers():
    for text in ("42", "null", '"abc"', "true", "rien {pas json} ici"):
        with pytest.raises(ValueError):
            extract_json(text)
    with pytest.raises(ValueError):
        extract_json("")


def test_nan_and_infinity_become_none():
    assert extract_json('{"score": NaN, "x": -Infinity, "ok": true}') == {"score": None, "x": None, "ok": True}


def test_braces_inside_strings_and_prose_before():
    text = 'Texte {pas json} puis {"a": "x{y}z", "b": [1, {"c": "}"}]} fin'
    assert extract_json(text) == {"a": "x{y}z", "b": [1, {"c": "}"}]}


def test_fence_without_language_or_with_other_language_wins_over_prose():
    assert extract_json("Note [1] :\n```\n{\"a\": 1}\n```") == {"a": 1}
    assert extract_json("```JSON\n{\"a\": 2}\n```") == {"a": 2}
    assert extract_json("```javascript\n[1, 2]\n```") == [1, 2]


def test_unterminated_think_block_is_dropped():
    assert strip_think("<think>je réfléchis {\"a\": 1}") == ""
    with pytest.raises(ValueError):
        extract_json("<think>je réfléchis {\"a\": 1}")
    assert extract_json("<think>a</think>{\"b\": 2}<think>c") == {"b": 2}


def test_nested_trailing_commas_and_truncated_object():
    assert extract_json('{"a": {"b": [1, 2,],},}') == {"a": {"b": [1, 2]}}
    with pytest.raises(ValueError):
        extract_json('{"a": 1, "b": "tronqu')


def test_long_response_with_many_stray_braces():
    text = ("{ " * 3000) + '{"a": "' + ("y" * 100_000) + '"}'
    assert len(extract_json(text)["a"]) == 100_000
    with pytest.raises(ValueError):
        extract_json("bla { x " * 5000)
