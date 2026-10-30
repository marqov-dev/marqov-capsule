"""Release checks must fail honestly and scan the whole tracked repository."""

import importlib.util
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

SPEC = importlib.util.spec_from_file_location(
    "check_urls", Path(__file__).parents[1] / "tools/check_urls.py"
)
links = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(links)


def url(host="example.org", path=""):
    return "https" + "://" + host + path


def test_collect_keeps_spaced_names_and_ignores_cwd(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    target = tmp_path / "guide with spaces.md"
    target.write_text(url() + "!\n")
    subprocess.run(["git", "add", target.name], cwd=tmp_path, check=True)
    nested = tmp_path / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert links.collect(tmp_path) == {url(): {target.name}}


def test_missing_git_repository_does_not_pass_vacuously(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        links.tracked_files(tmp_path)


@pytest.mark.parametrize("host", ["[::1", "a" * 64 + ".org", "bad_host.org", "example.org:99999"])
def test_bad_url_is_a_failure_not_a_crash(host, monkeypatch, capsys):
    monkeypatch.setattr(links, "collect", lambda: {url(host): {"guide.md"}})
    assert links.main(["--offline"]) == 1
    assert "invalid URL" in capsys.readouterr().out


@pytest.mark.parametrize(
    "host", ["marqov" + ".com", "platform.marqov" + ".dev", "unknown.marqov.ai"]
)
def test_unapproved_marqov_host_fails_even_if_it_resolves(host, monkeypatch):
    monkeypatch.setattr(links, "collect", lambda: {url(host): {"guide.md"}})
    monkeypatch.setattr(links, "probe", lambda _: pytest.fail("must fail before network access"))
    assert links.main([]) == 1


def test_unicode_urls_and_ipv6_are_normalized():
    assert links.normalize(url("café.org", "/résumé")) == url(
        "xn--caf-dma.org", "/r%C3%A9sum%C3%A9"
    )
    assert links.normalize(url("[::1]", "/")) == url("[::1]", "/")


def test_resolver_outage_is_inconclusive(monkeypatch, capsys):
    monkeypatch.setattr(links, "collect", lambda: {url(): {"guide.md"}})

    def unavailable(*args, **kwargs):
        raise URLError("temporary resolver failure")

    monkeypatch.setattr(links, "urlopen", unavailable)
    assert links.main([]) == 0
    assert "WARN:" in capsys.readouterr().out


@pytest.mark.parametrize("status", [403, 405])
def test_head_retries_get_and_closes_response(status, monkeypatch):
    calls = []

    class Response:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

    response = Response()

    def open_url(request, **kwargs):
        calls.append(request.method)
        if request.method == "HEAD":
            raise HTTPError(url(), status, "HEAD restricted", {}, None)
        return response

    monkeypatch.setattr(links, "urlopen", open_url)
    assert links.probe(url()) is None
    assert calls == ["HEAD", "GET"]
    assert response.closed


def test_schema_identifier_is_not_fetched(monkeypatch):
    monkeypatch.setattr(links, "collect", lambda: {next(iter(links.IDENTIFIERS)): {"schema.json"}})
    monkeypatch.setattr(links, "probe", lambda _: pytest.fail("identifier is not a retrieval URL"))
    assert links.main([]) == 0
