"""Cheap guards for the stylesheet.

The markup in `app/components.py` is tested line by line; the CSS it depends on
was not tested at all. These four tests pin the properties that would be
expensive to notice by eye: no external resource sneaking into the page, both
colour sets present, no reference to a token that was renamed away, and the
phone breakpoints still last in the cascade - they redefine the padding tokens
and only work when they come after both token blocks.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from style import CSS  # noqa: E402


def test_the_page_loads_no_external_resource() -> None:
    assert "url(" not in CSS
    assert "http" not in CSS
    assert "@import" not in CSS


def test_both_token_blocks_exist() -> None:
    assert "prefers-color-scheme: dark" in CSS
    assert CSS.count("--cl-bg-0:") == 2


def test_every_token_used_is_defined() -> None:
    used = set(re.findall(r"var\((--cl-[a-z0-9-]+)\)", CSS))
    defined = set(re.findall(r"^\s*(--cl-[a-z0-9-]+):", CSS, re.M))
    assert used - defined == set()


def test_the_phone_breakpoints_survive() -> None:
    assert "max-width: 640px" in CSS
    assert "max-width: 420px" in CSS
    assert CSS.index("prefers-color-scheme") < CSS.index("max-width: 640px")
