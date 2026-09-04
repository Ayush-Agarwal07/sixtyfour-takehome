"""Run-directory naming: <person-slug>-<n>, counting per label."""
from __future__ import annotations

from pi.run import allocate_run_dir, run_label


def test_label_from_email_and_url():
    assert run_label("andrew.goering@ramp.com") == "andrew-goering"
    assert run_label("https://www.linkedin.com/in/andrewgoering") == "andrewgoering"


def test_label_takes_the_name_not_the_qualifiers():
    assert run_label("Henry wang, sixtyfour ai") == "henry-wang"
    assert run_label("sarah chen, product designer, ex-figma") == "sarah-chen"


def test_label_strips_request_phrasing():
    assert run_label("do deep research on the CTO of Ariglad") == "cto-of-ariglad"


def test_label_never_empty_or_unsafe():
    assert run_label("") == "target"
    assert run_label("   ") == "target"
    assert run_label("Ünal Çağdaş, Zürich") == "unal-cagdas"        # diacritics folded
    assert run_label("../../etc/passwd") == "etc-passwd"            # no separators survive


def test_numbering_increments_per_label(tmp_path):
    first = allocate_run_dir("Henry wang, sixtyfour ai", str(tmp_path))
    second = allocate_run_dir("Henry wang, sixtyfour ai", str(tmp_path))
    other = allocate_run_dir("andrew.goering@ramp.com", str(tmp_path))
    assert first.name == "henry-wang-1"
    assert second.name == "henry-wang-2"
    assert other.name == "andrew-goering-1"
    assert first.is_dir() and second.is_dir()


def test_allocate_skips_a_directory_someone_else_took(tmp_path):
    (tmp_path / "henry-wang-1").mkdir()
    (tmp_path / "henry-wang-7").mkdir()
    assert allocate_run_dir("Henry wang, sixtyfour ai", str(tmp_path)).name == "henry-wang-8"
