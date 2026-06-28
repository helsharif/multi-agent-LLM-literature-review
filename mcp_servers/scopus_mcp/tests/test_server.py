import pytest
import json
from unittest.mock import patch, MagicMock
from server import load_api_key, search_papers, get_abstract, verify_doi, get_full_text

# ── helpers ──────────────────────────────────────────────────────────────────

MOCK_SEARCH_RESPONSE = {
    "search-results": {
        "entry": [
            {
                "dc:title": "Permafrost carbon dynamics",
                "dc:creator": "Smith, J.",
                "prism:doi": "10.1234/test.001",
                "prism:coverDate": "2023-01-01",
                "dc:description": "Study of permafrost carbon release."
            }
        ],
        "opensearch:totalResults": "1"
    }
}

MOCK_ABSTRACT_RESPONSE = {
    "abstracts-retrieval-response": {
        "coredata": {
            "dc:title": "Permafrost carbon dynamics",
            "dc:creator": "Smith, J.",
            "prism:doi": "10.1234/test.001",
            "prism:coverDate": "2023-01-01",
            "dc:description": "Full abstract text here."
        }
    }
}

# ── tests ─────────────────────────────────────────────────────────────────────

def test_load_api_key_reads_from_keys_file(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("SCOPUS_API_KEY=mykey123\n")
    key = load_api_key(str(keys_file))
    assert key == "mykey123"

def test_load_api_key_raises_if_missing(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("OTHER_KEY=something\n")
    with pytest.raises(ValueError, match="SCOPUS_API_KEY"):
        load_api_key(str(keys_file))

@patch("server.requests.get")
def test_search_papers_returns_list(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_SEARCH_RESPONSE
    )
    results = search_papers("permafrost carbon", limit=1, api_key="testkey")
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["doi"] == "10.1234/test.001"
    assert results[0]["title"] == "Permafrost carbon dynamics"
    assert results[0]["first_author"] == "Smith, J."
    assert results[0]["year"] == "2023"

@patch("server.requests.get")
def test_search_papers_raises_on_http_error(mock_get):
    mock_get.return_value = MagicMock(status_code=401)
    with pytest.raises(RuntimeError, match="Scopus search failed"):
        search_papers("anything", limit=5, api_key="badkey")

@patch("server.requests.get")
def test_get_abstract_returns_text(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_ABSTRACT_RESPONSE
    )
    result = get_abstract("10.1234/test.001", api_key="testkey")
    assert result["abstract"] == "Full abstract text here."
    assert result["doi"] == "10.1234/test.001"

@patch("server.requests.get")
def test_get_abstract_raises_on_not_found(mock_get):
    mock_get.return_value = MagicMock(status_code=404)
    with pytest.raises(RuntimeError, match="Abstract not found"):
        get_abstract("10.9999/bad.doi", api_key="testkey")

@patch("server.requests.get")
def test_verify_doi_returns_true_when_found(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "search-results": {
                "opensearch:totalResults": "1",
                "entry": [{"dc:title": "Something", "prism:doi": "10.1234/test.001"}]
            }
        }
    )
    assert verify_doi("10.1234/test.001", api_key="testkey") is True

@patch("server.requests.get")
def test_verify_doi_returns_false_when_not_found(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"search-results": {"opensearch:totalResults": "0", "entry": []}}
    )
    assert verify_doi("10.9999/fake.doi", api_key="testkey") is False

@patch("server.requests.get")
def test_verify_doi_raises_on_server_error(mock_get):
    mock_get.return_value = MagicMock(status_code=500)
    with pytest.raises(RuntimeError, match="Scopus server error"):
        verify_doi("10.1234/test.001", api_key="testkey")

@patch("server.requests.get")
def test_get_full_text_returns_text(mock_get):
    mock_get.return_value = MagicMock(status_code=200, text="Full article body text.")
    result = get_full_text("10.1234/test.001", api_key="testkey")
    assert result["doi"] == "10.1234/test.001"
    assert result["full_text"] == "Full article body text."
    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args
    assert call_kwargs.kwargs["headers"]["X-ELS-APIKey"] == "testkey"
    assert call_kwargs.kwargs["headers"]["Accept"] == "text/plain"

@patch("server.requests.get")
def test_get_full_text_raises_on_not_found(mock_get):
    mock_get.return_value = MagicMock(status_code=404)
    with pytest.raises(RuntimeError, match="Full text not found"):
        get_full_text("10.9999/bad.doi", api_key="testkey")

@patch("server.requests.get")
def test_get_full_text_raises_on_access_denied(mock_get):
    mock_get.return_value = MagicMock(status_code=403)
    with pytest.raises(RuntimeError, match="not be covered by your institutional subscription"):
        get_full_text("10.1234/paywalled.001", api_key="testkey")

@patch("server.requests.get")
def test_get_full_text_raises_on_server_error(mock_get):
    mock_get.return_value = MagicMock(status_code=500)
    with pytest.raises(RuntimeError, match="ScienceDirect server error"):
        get_full_text("10.1234/test.001", api_key="testkey")
