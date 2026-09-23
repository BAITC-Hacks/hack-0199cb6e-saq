"""Read-only recommendations viewer checks using temporary synthetic CSV files."""

from __future__ import annotations

import csv
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ekt_api.viewer import create_app

HEADERS = ["sku", "supplier", "qty_recommended", "reason", "urgency"]
SYNTHETIC_ROW = ["030200192_", "SE", "12.500", "Синтетический спрос", "normal"]


def write_csv(
    path: Path,
    rows: list[list[str]],
    *,
    headers: list[str] | None = None,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> None:
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(HEADERS if headers is None else headers)
        writer.writerows(rows)


def test_exact_strings_and_only_public_fields(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.csv"
    rows = [
        [
            "030200192_",
            "Systeme Electric",
            "9007199254740993.000100",
            '<script>alert("synthetic")</script>\nВторая строка; =1+1',
            "critical",
            "synthetic-private-field",
        ],
        ["щт23054819", "ИЭК", "0.000000000000001", "=1+1", "normal", "extra"],
        ["ст-9952399", "IEK", "00012.50", "+SUM(A1:A2)", "later", "extra"],
        ["BR-R10-12-K01", "SE", "0", "@synthetic", "normal", "extra"],
    ]
    write_csv(path, rows, headers=[*HEADERS, "internal_note"])
    before = path.read_bytes()

    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.get("/recommendations")

    assert response.status_code == 200
    expected = [
        dict(zip(HEADERS, [row[0], supplier, *row[2:5]], strict=True))
        for row, supplier in zip(rows, ["SE", "IEK", "IEK", "SE"], strict=True)
    ]
    assert response.json() == expected
    assert all(set(row) == set(HEADERS) for row in response.json())
    assert all(
        isinstance(value, str) for row in response.json() for value in row.values()
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_bom_and_supported_delimiters(
    tmp_path: Path, delimiter: str, encoding: str
) -> None:
    path = tmp_path / "synthetic.csv"
    row = [*SYNTHETIC_ROW]
    row[3] = "Спрос, кратность; остаток\tи поставка\nСинтетическая строка"
    write_csv(path, [row], delimiter=delimiter, encoding=encoding)

    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.get("/recommendations")

    assert response.status_code == 200
    assert response.json() == [dict(zip(HEADERS, row, strict=True))]


@pytest.mark.parametrize(
    "headers",
    [
        HEADERS,
        ["sku_id", "supplier_id", "recommended_qty", "reason_short", "urgency"],
        ["sku", "supplier_id", "qty_recommended", "reason_short.ru", "urgency"],
        ["sku_id", "supplier", "recommended_qty", "reason_ru", "urgency"],
    ],
)
def test_supported_header_aliases(tmp_path: Path, headers: list[str]) -> None:
    path = tmp_path / "synthetic.csv"
    write_csv(path, [SYNTHETIC_ROW], headers=headers)

    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.get("/recommendations")

    assert response.status_code == 200
    assert response.json() == [dict(zip(HEADERS, SYNTHETIC_ROW, strict=True))]


def test_header_only_is_an_empty_result(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.csv"
    write_csv(path, [])

    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.get("/recommendations")

    assert response.status_code == 200
    assert response.json() == []


def test_each_request_reads_current_file(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.csv"
    write_csv(path, [SYNTHETIC_ROW])
    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        original = client.get("/recommendations")
        assert original.status_code == 200
        assert original.json()[0]["qty_recommended"] == "12.500"

        updated = [*SYNTHETIC_ROW]
        updated[2] = "42.000001"
        write_csv(path, [updated])
        before_request = path.read_bytes()
        response = client.get("/recommendations")

    assert response.status_code == 200
    assert response.json()[0]["qty_recommended"] == "42.000001"
    assert path.read_bytes() == before_request


def test_environment_can_select_synthetic_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "synthetic.csv"
    write_csv(path, [SYNTHETIC_ROW])
    monkeypatch.setenv("EKT_RECOMMENDATIONS_CSV", str(path))

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        response = client.get("/recommendations")

    assert response.status_code == 200
    assert response.json() == [dict(zip(HEADERS, SYNTHETIC_ROW, strict=True))]


@pytest.mark.parametrize("unreadable", [False, True], ids=["missing", "directory"])
def test_unavailable_file_returns_503(tmp_path: Path, unreadable: bool) -> None:
    path = tmp_path if unreadable else tmp_path / "missing-synthetic.csv"
    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.get("/recommendations")

    assert response.status_code == 503
    assert str(path) not in response.text
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "contents",
    [
        b"",
        b"\xff\xfeinvalid utf-8",
        b"sku,supplier,qty_recommended,reason\nSYN,SE,1,synthetic\n",
        b"sku,supplier,qty_recommended,reason,urgency\nSYN,SE,1,synthetic\n",
        b"sku,supplier,qty_recommended,reason,urgency\nSYN,SE,1,synthetic,normal,extra\n",
        b'sku,supplier,qty_recommended,reason,urgency\nSYN,SE,1,"unclosed,normal\n',
        b"sku,sku,supplier,qty_recommended,reason,urgency\nSYN,OTHER,SE,1,synthetic,normal\n",
        b"sku,sku_id,supplier,qty_recommended,reason,urgency\nSYN,OTHER,SE,1,synthetic,normal\n",
    ],
    ids=[
        "empty",
        "invalid-encoding",
        "missing-header",
        "short-row",
        "long-row",
        "unclosed-quote",
        "duplicate-header",
        "conflicting-aliases",
    ],
)
def test_malformed_csv_returns_422_without_modifying_file(
    tmp_path: Path, contents: bytes
) -> None:
    path = tmp_path / "synthetic-invalid.csv"
    path.write_bytes(contents)

    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.get("/recommendations")

    assert response.status_code == 422
    assert str(path) not in response.text
    assert "Traceback" not in response.text
    assert path.read_bytes() == contents


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_mutations_are_not_supported(tmp_path: Path, method: str) -> None:
    path = tmp_path / "synthetic.csv"
    write_csv(path, [SYNTHETIC_ROW])
    before = path.read_bytes()

    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.request(
            method,
            "/recommendations",
            json={"sku": "030200192_", "qty_recommended": "99"},
        )

    assert response.status_code == 405
    assert path.read_bytes() == before


def test_json_headers_and_disabled_documentation(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.csv"
    write_csv(path, [SYNTHETIC_ROW])

    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.get("/recommendations")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "no-store" in response.headers["cache-control"]
        for url in ["/docs", "/redoc", "/openapi.json"]:
            assert client.get(url).status_code == 404


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and attributes.get("src"):
            self.sources.append(str(attributes["src"]))
        if tag == "link" and attributes.get("rel") == "stylesheet":
            assert attributes.get("href")
            self.sources.append(str(attributes["href"]))


def test_static_page_and_local_assets(tmp_path: Path) -> None:
    if not (ROOT / "web" / "viewer" / "index.html").is_file():
        pytest.skip("Static viewer assets are not installed in this checkout")
    path = tmp_path / "synthetic.csv"
    write_csv(path, [])

    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        parser = AssetParser()
        parser.feed(response.text)
        assert parser.sources
        for source in parser.sources:
            parsed = urlsplit(source)
            assert not parsed.scheme and not parsed.netloc
            assert client.get(urljoin("/", source)).status_code == 200
