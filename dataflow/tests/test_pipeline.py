import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from dataflow.database import Database
from dataflow.pipeline import FIELDS, InputError, import_csv, safe_cell
from dataflow.api import create_app

MAPPING = {k: k for k in (*FIELDS, "description")}
HEADER = "sale_id,branch,sale_date,amount,currency,description\n"
SAMPLE = (
    HEADER
    + "A1,Lima,2026-10-01,100.10,PEN,=1+1\nA2,Lima,2026-10-02,20.20,PEN,normal\nA1,Lima,2026-10-01,100.10,PEN,=1+1\nA3,Lima,2026-02-30,1.00,PEN,error\nA2,Lima,2026-10-02,30.20,PEN,conflicto\nA4,Cusco,2026-10-04,10.00,USD,otra moneda\n"
)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.sqlite3")


def test_accounting_totals_provenance_and_idempotence(db):
    result = import_csv(db, SAMPLE.encode(), "../ventas.csv", MAPPING)
    assert (
        result["total"],
        result["accepted"],
        result["rejected"],
        result["duplicated"],
    ) == (6, 3, 2, 1)
    with db.connect() as con:
        assert (
            con.execute(
                "SELECT SUM(amount_cents) FROM sales WHERE currency='PEN'"
            ).fetchone()[0]
            == 12030
        )
        assert [
            tuple(r)
            for r in con.execute(
                "SELECT source_row,status FROM outcomes ORDER BY source_row"
            )
        ] == [
            (2, "accepted"),
            (3, "accepted"),
            (4, "duplicated"),
            (5, "rejected"),
            (6, "rejected"),
            (7, "accepted"),
        ]
    replay = import_csv(db, SAMPLE.encode(), "copia.csv", MAPPING)
    assert replay["replayed"] and replay["id"] == result["id"]
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 3
        assert con.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 1


def test_semicolon_dmy_decimal_comma_and_mapping(db):
    content = "codigo;sede;dia;total;divisa\nX1; lima ;29/10/2026;12,34;pen\n".encode()
    result = import_csv(
        db,
        content,
        "ES.csv",
        dict(zip(FIELDS, ["codigo", "sede", "dia", "total", "divisa"])),
        ";",
        "dmy",
        "comma",
    )
    assert result["accepted"] == 1
    with db.connect() as con:
        assert tuple(
            con.execute("SELECT branch,sale_date,amount_cents FROM sales").fetchone()
        ) == ("LIMA", "2026-10-29", 1234)


@pytest.mark.parametrize(
    "bad",
    [
        b"a,a\nx,x\n",
        b"\xff\xfe",
        b"sale_id\n\x00",
        b'a,b\n"unfinished',
        b"a\n" + b"x" * 2001,
    ],
)
def test_bad_files_are_atomic(db, bad):
    with pytest.raises(InputError):
        import_csv(db, bad, "bad.csv", MAPPING)
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0


@pytest.mark.parametrize(
    "amount", ["-2", "NaN", "Infinity", "1e3", "0", "1.234", "1,000.00"]
)
def test_invalid_money_is_rejected(db, amount):
    result = import_csv(
        db,
        (HEADER + f'A,Lima,2026-10-01,"{amount}",PEN,none\n').encode(),
        "a.csv",
        MAPPING,
    )
    assert result["rejected"] == 1 and result["accepted"] == 0


def test_duplicate_across_files_and_concurrent_imports(db):
    one = (HEADER + "A,Lima,2026-10-01,1,PEN,a\n").encode()
    with ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(lambda _: import_csv(db, one, "same.csv", MAPPING), range(4))
        )
    assert sum(not r["replayed"] for r in results) == 1
    other = one + b"B,Lima,2026-10-01,2,PEN,b\n"
    r = import_csv(db, other, "other.csv", MAPPING)
    assert (r["accepted"], r["duplicated"]) == (1, 1)


def test_multiline_physical_source_lines(db):
    body = (
        HEADER
        + 'A,Lima,2026-10-01,1,PEN,"two\nlines"\nB,Lima,2026-10-01,2,PEN,next\n\n'
    )
    result = import_csv(db, body.encode(), "multiline.csv", MAPPING)
    assert result["total"] == 3 and result["rejected"] == 1
    with db.connect() as con:
        assert [
            r[0]
            for r in con.execute("SELECT source_row FROM outcomes ORDER BY source_row")
        ] == [2, 4, 5]


@pytest.mark.parametrize(
    "value", ["=HYPERLINK(1)", "+1", "-2", "@SUM(A1)", "  =1", "\t=1", "\n=1"]
)
def test_formula_neutralization(value):
    assert safe_cell(value).startswith("'")


def test_api_upload_export_pagination_and_errors(tmp_path):
    with TestClient(create_app(tmp_path / "api.db")) as client:
        assert client.get("/api/health").status_code == 200
        p = client.post(
            "/api/preview", files={"file": ("x.csv", SAMPLE.encode(), "text/csv")}
        )
        assert p.json()["records"] == 6
        result = client.post(
            "/api/imports",
            files={"file": ("x.csv", SAMPLE.encode(), "text/csv")},
            data={"mapping": json.dumps(MAPPING)},
        )
        assert result.status_code == 201
        export = client.get("/api/export/sales")
        rows = list(csv.DictReader(io.StringIO(export.text.lstrip("\ufeff"))))
        assert len(rows) == 3 and rows[0]["description"] == "'=1+1"
        summary = client.get("/api/summary").json()
        assert summary["totals"]["total"] == 6
        assert len(summary["groups"]) == 2
        assert client.get("/api/summary?period=2026-99").status_code == 422
        assert (
            len(
                client.get(
                    f"/api/imports/{result.json()['id']}/outcomes?limit=2"
                ).json()
            )
            == 2
        )
        assert client.get("/api/imports/missing/outcomes").status_code == 404
        assert (
            client.post(
                "/api/imports",
                files={"file": ("x.csv", b"a\n", "text/csv")},
                data={"mapping": "[]"},
            ).status_code
            == 422
        )
        assert client.get("/").status_code == 200


def test_synthetic_demo_expected_totals(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root / "demo/expected.json").read_text())
    with TestClient(create_app(tmp_path / "demo.db")) as client:
        client.post("/api/demo").raise_for_status()
        summary = client.get("/api/summary").json()
        for field in ("accepted", "rejected", "duplicated"):
            assert summary["totals"][field] == expected[field]
        assert (
            sum(g["amount_cents"] for g in summary["groups"]) == expected["total_cents"]
        )
        client.post("/api/demo").raise_for_status()
        assert client.get("/api/summary").json() == summary
