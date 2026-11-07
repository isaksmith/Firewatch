import pytest

from app.keywords import classify


@pytest.mark.parametrize("text,cat", [
    ("There is a FIRE on the ridge", "fire"),
    ("grass is burning near the creek", "fire"),
    ("I see smoke west of town", "smoke"),
    ("downed power line on 5th", "hazard"),
    ("burn pile at my place", "burn"),
    ("nice day", "other"),
    ("", "other"),
    ("firefly", "other"),
])
def test_categories(text, cat):
    assert classify(text).category == cat


@pytest.mark.parametrize("text", ["no fire here", "No smoke now", "we put out the fire", "it was not a fire"])
def test_negation_is_other(text):
    assert classify(text).category == "other"


@pytest.mark.parametrize("text", ["I heard there is a fire", "someone said smoke", "They say fire"])
def test_hearsay(text):
    r = classify(text)
    assert r.hearsay and r.category in ("fire", "smoke")


def test_first_hand_is_not_hearsay():
    assert not classify("fire on the hill").hearsay
