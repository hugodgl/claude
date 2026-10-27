from content_engine.prompts import SYSTEM_PROMPT
from content_engine.topics import (
    add_topic,
    count_topics,
    generate_ideas,
    is_duplicate,
    list_topics,
    normalize_question,
    pick_topics,
    seed_topics,
)


def test_seed_is_idempotent_and_covers_three_products(conn, settings):
    assert seed_topics(conn, settings.topics_file) == 0  # déjà amorcé par la fixture
    for product in ("avis", "marches", "cabinets"):
        assert 10 <= count_topics(conn, product, "new") <= 15
    assert all(r["angle"] for r in list_topics(conn))


def test_normalize_and_duplicates(conn):
    assert (
        normalize_question("Comment demander un avis Google ?") == "comment demander un avis google"
    )
    assert (
        add_topic(conn, "avis", "comment demander un avis google à un client sans le gêner !")
        is None
    )
    assert (
        is_duplicate(
            "comment relancer un client par sms",
            ["comment relancer un client par sms pour un avis"],
        )
        is False
    )
    assert is_duplicate("a b c d e", ["a b c d e f"]) is True
    new_id = add_topic(conn, "avis", "Faut-il payer pour avoir des avis ?", angle="mythe")
    assert new_id and list_topics(conn, "avis", "new")[-1]["source"] == "manual"


def test_generate_ideas_skips_duplicates(conn, llm):
    before = count_topics(conn, "avis", "new")
    inserted = generate_ideas(conn, llm, "avis", 4)
    assert len(inserted) == 4
    assert len({i["question"] for i in inserted}) == 4
    assert count_topics(conn, "avis", "new") == before + 4
    call = llm.calls[0]
    assert call["system"] == SYSTEM_PROMPT and call["json_mode"] is True
    assert "Questions déjà en banque" in call["prompt"]
    # le simulateur renvoie aussi la première question existante : elle n'est pas réinsérée
    assert all(i["source"] == "llm" for i in list_topics(conn, "avis")[-4:])


def test_pick_topics_alternates_products(conn):
    picked = pick_topics(conn, 6)
    assert [r["product"] for r in picked] == ["avis", "marches", "cabinets"] * 2
    assert [r["product"] for r in pick_topics(conn, 2, product="marches")] == ["marches", "marches"]
