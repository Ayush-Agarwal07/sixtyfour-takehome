"""Extraction ladder: structured rungs → predicate tuples, no LLM involved."""
from __future__ import annotations

from pi.expand.extract import extract_github_emails, extract_github_profile, extract_jsonld, handle_of, window_text

JSONLD_HTML = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Person", "name": "Andrew Goering",
 "jobTitle": "Software Engineer", "worksFor": {"@type": "Organization", "name": "Ramp"}}
</script></head><body></body></html>"""


def test_jsonld_person_gives_title_and_employer():
    tuples = extract_jsonld(JSONLD_HTML)
    assert ("title", "Software Engineer", "Software Engineer", None) in tuples
    assert ("employer", "Ramp", "Ramp", None) in tuples


def test_github_profile_strips_leading_at_from_company():
    tuples = extract_github_profile({"company": "@Sixtyfour", "location": "SF", "bio": ""})
    assert ("employer", "Sixtyfour", "Sixtyfour", None) in tuples
    assert ("location", "SF", "SF", None) in tuples


def test_github_profile_takes_text_after_last_at_in_company():
    tuples = extract_github_profile({"company": "founding eng @sixtyfour-ai"})
    assert ("employer", "sixtyfour-ai", "sixtyfour-ai", None) in tuples


def test_commit_emails_corporate_gives_employment_and_email():
    entries = [{"email": "andrew@ramp.com", "first": "2021-01-01", "last": "2022-06-01", "count": 40}]
    tuples = extract_github_emails(entries)
    preds = {t[0] for t in tuples}
    assert preds == {"employment", "email"}
    employment = next(t for t in tuples if t[0] == "employment")
    assert employment[1] == "ramp.com" and employment[3] == "2021 – 2022"
    email = next(t for t in tuples if t[0] == "email")
    assert email[1] == "andrew@ramp.com" and email[3] is None


def test_commit_emails_freemail_gives_email_only():
    entries = [{"email": "andrew@gmail.com", "first": "2021-01-01", "last": "2021-01-02", "count": 3}]
    tuples = extract_github_emails(entries)
    assert len(tuples) == 1 and tuples[0][0] == "email" and tuples[0][1] == "andrew@gmail.com"


def test_window_text_keeps_text_around_name():
    text = ("padding " * 500) + "Andrew works at Ramp." + (" padding" * 500)
    out = window_text(text, ["Andrew"], radius=20)
    assert "Andrew works at Ramp." in out
    assert len(out) < len(text)


def test_handle_of_known_platform_shapes():
    assert handle_of("https://github.com/saarthshah") == "saarthshah"
    assert handle_of("https://x.com/saarth_") == "saarth_"
    assert handle_of("https://www.linkedin.com/in/saarthshah") == "saarthshah"
    assert handle_of("https://www.behance.net/saarthshah") == "saarthshah"
    assert handle_of("https://medium.com/@saarthshah") == "saarthshah"
    assert handle_of("https://dev.to/saarthshah") == "saarthshah"
    assert handle_of("https://www.reddit.com/user/saarthshah") == "saarthshah"
    assert handle_of("https://www.instagram.com/saarthshah") == "saarthshah"
    assert handle_of("https://www.youtube.com/@saarthshah") == "saarthshah"
    assert handle_of("https://www.kaggle.com/saarthshah") == "saarthshah"
    assert handle_of("https://huggingface.co/saarthshah") == "saarthshah"
    assert handle_of("https://dribbble.com/saarthshah") == "saarthshah"
    assert handle_of("https://devpost.com/saarthshah") == "saarthshah"


def test_handle_of_rejects_a_bare_website_root():
    # fix-round F2: a personal-website domain is not a handle shape at all.
    assert handle_of("https://www.saarthshah.com/") is None
    assert handle_of("https://saarthshah.com") is None
    # nor is a LinkedIn/reddit URL that isn't the /in//user/ profile shape
    assert handle_of("https://www.linkedin.com/company/acme") is None
    assert handle_of("https://www.reddit.com/r/programming") is None


def test_extract_github_repos_yields_dated_repo_tuples():
    from pi.expand.extract import extract_github_repos
    tuples = extract_github_repos([{"full_name": "jane/proj", "html_url": "https://github.com/jane/proj",
                                    "description": "a tool", "pushed_at": "2021-06-01T10:00:00Z"},
                                   {"full_name": "jane/nourl"}])
    assert tuples == [("repo", "https://github.com/jane/proj", "jane/proj: a tool", "2021-06-01")]
