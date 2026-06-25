from tools.translators.prose_cleanup import cleanup_prose


def test_strips_uuid_keeps_label():
    raw = (
        "The creature makes a @UUID[Compendium.dnd5e.rules.JournalEntry.cube]{Save} against poison."
    )
    assert cleanup_prose(raw) == "The creature makes a Save against poison."


def test_strips_uuid_without_label_keeps_terminal_segment():
    raw = "See @UUID[Compendium.dnd5e.rules.JournalEntry.poisoned] for details."
    assert cleanup_prose(raw) == "See poisoned for details."


def test_save_macro_to_prose():
    assert (
        cleanup_prose("Make a [[/save dex 15]] or fall prone.")
        == "Make a DC 15 Dexterity save or fall prone."
    )


def test_save_macro_caps_ability_name():
    assert cleanup_prose("[[/save con 17]]") == "DC 17 Constitution save"


def test_strips_html_tags():
    assert cleanup_prose("<p>The <em>creature</em> attacks.</p>") == "The creature attacks."


def test_collapses_whitespace():
    assert cleanup_prose("Line 1.\n\n\n\nLine 2.") == "Line 1.\n\nLine 2."


def test_idempotent_on_clean_text():
    clean = "Already clean prose."
    assert cleanup_prose(clean) == clean
