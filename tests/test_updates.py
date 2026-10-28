import io
import json

from cocotimer import updates


def test_parse_and_compare_versions():
    assert updates.parse_version("v3.2") == (3, 2, 0)
    assert updates.parse_version("V3.1.1") == (3, 1, 1)
    for bad in ("", None, "latest", "v3", "3.2.1-beta", "javascript:alert(1)", "v3.2 <a href=x>"):
        assert updates.parse_version(bad) is None
    assert updates.is_newer("v3.4", "3.3.0") and updates.is_newer("3.3.1", "3.3.0")
    assert not updates.is_newer("v3.3", "3.3.0") and not updates.is_newer("V3.2.1", "3.3.0")
    assert not updates.is_newer("nonsense", "3.3.0")


def test_only_the_tag_name_is_used():
    assert updates.latest_from_response({"tag_name": "v3.4", "html_url": "https://evil.example/"}) == "3.4.0"
    assert updates.latest_from_response({"tag_name": "<b>v9</b>"}) is None
    assert updates.latest_from_response(["v3.4"]) is None


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_latest_handles_success_and_failures(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout, context):
        seen["url"], seen["timeout"] = request.full_url, timeout
        seen["verify"] = context.verify_mode
        return _Response(json.dumps({"tag_name": "v3.5"}).encode())

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    assert updates.fetch_latest() == "3.5.0"
    assert seen["url"].startswith("https://api.github.com/") and seen["verify"] == updates.ssl.CERT_REQUIRED

    def offline(*_args, **_kwargs):
        raise OSError("no network")

    monkeypatch.setattr(updates.urllib.request, "urlopen", offline)
    assert updates.fetch_latest() is None
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *a, **k: _Response(b"<html>"))
    assert updates.fetch_latest() is None
