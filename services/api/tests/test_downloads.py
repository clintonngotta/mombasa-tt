"""Downloads are named after what they show (core/downloads.py)."""

from django.http import HttpResponse

from core.downloads import file_name, named


def test_a_file_is_named_after_its_parts():
    assert file_name("Coast Open 2026", "Men's Singles", "Draw", extension="pdf") == (
        "Coast Open 2026 - Men's Singles - Draw.pdf"
    )
    assert file_name("Coast Open", "", "Final results", extension="png") == "Coast Open - Final results.png"


def test_characters_that_break_a_file_name_are_dropped():
    assert file_name('U-19 "A"/B: day 1?', extension="pdf") == "U-19 A B day 1.pdf"
    assert file_name("..\\..\\etc", extension="pdf") == "etc.pdf"
    assert file_name("Line\r\nbreak", extension="pdf") == "Line break.pdf"
    assert file_name("", "  ", extension="pdf") == "Coast TT.pdf"
    assert len(file_name("x" * 400, extension="pdf")) == 154


def test_a_non_ascii_name_is_quoted_for_every_browser():
    response = named(HttpResponse(), file_name("Mombasa Open – Wanawake", extension="pdf"), attachment=True)
    header = response["Content-Disposition"]
    assert header.startswith("attachment; filename*=utf-8''") and "Wanawake.pdf" in header
    assert "\n" not in header and "\r" not in header
