import pytest
from unittest.mock import patch, MagicMock
import sys, os
from server import load_credentials, ZoteroClient

# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def creds(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text(
        "SCOPUS_API_KEY=s\nZOTERO_API_KEY=zkey123\nZOTERO_USER_ID=987654\n"
    )
    return load_credentials(str(keys_file))

# ── credential loading ─────────────────────────────────────────────────────────

def test_load_credentials_reads_both_keys(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("ZOTERO_API_KEY=abc\nZOTERO_USER_ID=123\n")
    creds = load_credentials(str(keys_file))
    assert creds["api_key"] == "abc"
    assert creds["user_id"] == "123"

def test_load_credentials_raises_if_api_key_missing(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("ZOTERO_USER_ID=123\n")
    with pytest.raises(ValueError, match="ZOTERO_API_KEY"):
        load_credentials(str(keys_file))

def test_load_credentials_raises_if_user_id_missing(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("ZOTERO_API_KEY=abc\n")
    with pytest.raises(ValueError, match="ZOTERO_USER_ID"):
        load_credentials(str(keys_file))

# ── ZoteroClient ───────────────────────────────────────────────────────────────

def test_create_collection_returns_key(creds):
    mock_zot = MagicMock()
    mock_zot.create_collection.return_value = [{"key": "ABCD1234", "data": {"name": "My Topic — 2026-06-27"}}]
    client = ZoteroClient(creds, zot=mock_zot)
    key = client.create_collection("My Topic — 2026-06-27")
    assert key == "ABCD1234"
    mock_zot.create_collection.assert_called_once_with([{"name": "My Topic — 2026-06-27", "parentCollection": False}])

def test_get_collection_key_by_name_returns_key_when_found(creds):
    mock_zot = MagicMock()
    mock_zot.collections.return_value = [
        {"key": "ABCD1234", "data": {"name": "My Topic — 2026-06-27"}},
        {"key": "ZZZZ9999", "data": {"name": "Other Topic"}},
    ]
    client = ZoteroClient(creds, zot=mock_zot)
    key = client.get_collection_key_by_name("My Topic — 2026-06-27")
    assert key == "ABCD1234"

def test_get_collection_key_by_name_returns_none_when_not_found(creds):
    mock_zot = MagicMock()
    mock_zot.collections.return_value = []
    client = ZoteroClient(creds, zot=mock_zot)
    key = client.get_collection_key_by_name("Nonexistent")
    assert key is None

def test_get_collection_items_returns_list(creds):
    mock_zot = MagicMock()
    mock_zot.collection_items.return_value = [
        {"key": "ITEM0001", "data": {"title": "Paper A", "DOI": "10.1/a", "creators": [{"lastName": "Smith"}], "date": "2022"}}
    ]
    client = ZoteroClient(creds, zot=mock_zot)
    items = client.get_collection_items("ABCD1234")
    assert len(items) == 1
    assert items[0]["doi"] == "10.1/a"
    assert items[0]["title"] == "Paper A"
    assert items[0]["first_author"] == "Smith"
    assert items[0]["year"] == "2022"
    assert items[0]["zotero_key"] == "ITEM0001"

def test_search_library_by_doi_returns_item_when_found(creds):
    mock_zot = MagicMock()
    mock_zot.items.return_value = [
        {"key": "ITEM0001", "data": {"DOI": "10.1/test", "title": "Test Paper"}}
    ]
    client = ZoteroClient(creds, zot=mock_zot)
    result = client.search_library_by_doi("10.1/test")
    assert result is not None
    assert result["key"] == "ITEM0001"

def test_search_library_by_doi_returns_none_when_not_found(creds):
    mock_zot = MagicMock()
    mock_zot.items.return_value = [
        {"key": "ITEM0001", "data": {"DOI": "10.1/other"}}
    ]
    client = ZoteroClient(creds, zot=mock_zot)
    result = client.search_library_by_doi("10.1/test")
    assert result is None

def test_add_item_to_collection(creds):
    mock_zot = MagicMock()
    mock_zot.item_template.return_value = {
        "itemType": "journalArticle", "title": "", "DOI": "",
        "creators": [], "date": "", "abstractNote": "", "collections": []
    }
    mock_zot.create_items.return_value = [{"key": "ITEM0001"}]
    client = ZoteroClient(creds, zot=mock_zot)
    paper = {"title": "Test Paper", "doi": "10.1/test", "first_author": "Jones, A.", "year": "2024", "abstract": "Abstract text."}
    item_key = client.add_item(paper, collection_key="ABCD1234")
    assert item_key == "ITEM0001"
    created = mock_zot.create_items.call_args[0][0][0]
    assert created["title"] == "Test Paper"
    assert created["DOI"] == "10.1/test"
    assert "ABCD1234" in created["collections"]

def test_export_bibliography_calls_zotero(creds):
    mock_zot = MagicMock()
    mock_zot.collection_items.return_value = "<bib>Smith 2024</bib>"
    client = ZoteroClient(creds, zot=mock_zot)
    result = client.export_bibliography("ABCD1234", style="agu")
    mock_zot.collection_items.assert_called_once_with("ABCD1234", format="bib", style="agu")
    assert result == "<bib>Smith 2024</bib>"

def test_export_bibliography_falls_back_to_json_for_non_string(creds):
    mock_zot = MagicMock()
    mock_zot.collection_items.return_value = [{"key": "ITEM0001", "data": {"title": "Test"}}]
    client = ZoteroClient(creds, zot=mock_zot)
    result = client.export_bibliography("ABCD1234", style="agu")
    assert isinstance(result, str)
    assert "ITEM0001" in result
