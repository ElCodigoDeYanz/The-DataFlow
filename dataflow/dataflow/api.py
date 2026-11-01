"""HTTP adapter. Pipeline rules remain outside request handlers."""

import json
import os
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from .database import Database
from .pipeline import FIELDS, MAX_BYTES, InputError, import_csv, parse_csv, to_csv

ROOT = Path(__file__).resolve().parents[1]


def create_app(path=None):
    db = Database(
        Path(path or os.environ.get("DATAFLOW_DB", ROOT / "runtime/dataflow.sqlite3"))
    )
    app = FastAPI(
        title="Yanz DataFlow",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        description="Local CSV consolidation. No external integrations.",
    )
    app.state.db = db

    @app.middleware("http")
    async def limits(request, call_next):
        length = request.headers.get("content-length", "0")
        if length.isdigit() and int(length) > MAX_BYTES + 65536:
            return Response("Pedido demasiado grande.", status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "external_integrations": False}

    @app.post("/api/preview")
    def preview(file: UploadFile = File(...), delimiter: str = Form(",")):
        try:
            content = file.file.read(MAX_BYTES + 1)
            headers, rows = parse_csv(content, delimiter)
            return {
                "headers": headers,
                "sample": [dict(zip(headers, r)) for _, r in rows[:5]],
                "records": len(rows),
                "suggested_mapping": {k: k for k in FIELDS if k in headers},
            }
        except InputError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            file.file.close()

    @app.post("/api/imports", status_code=201)
    def upload(
        file: UploadFile = File(...),
        mapping: str = Form(...),
        delimiter: str = Form(","),
        date_format: str = Form("iso"),
        number_format: str = Form("point"),
    ):
        try:
            if len(mapping) > 10000:
                raise InputError("Asociación demasiado larga.")
            column_map = json.loads(mapping)
            if not isinstance(column_map, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in column_map.items()
            ):
                raise InputError("Asociación de columnas inválida.")
            return import_csv(
                db,
                file.file.read(MAX_BYTES + 1),
                file.filename or "archivo.csv",
                column_map,
                delimiter,
                date_format,
                number_format,
            )
        except (InputError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            file.file.close()

    @app.get("/api/imports")
    def imports():
        with db.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM imports ORDER BY created_at DESC LIMIT 30"
                )
            ]

    @app.get("/api/imports/{batch}/outcomes")
    def outcomes(
        batch: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)
    ):
        with db.connect() as con:
            if not con.execute("SELECT 1 FROM imports WHERE id=?", (batch,)).fetchone():
                raise HTTPException(404, "Importación no encontrada.")
            return [
                dict(r)
                for r in con.execute(
                    "SELECT source_row,status,reason,raw_json FROM outcomes WHERE import_id=? ORDER BY source_row LIMIT ? OFFSET ?",
                    (batch, limit, offset),
                )
            ]

    @app.get("/api/summary")
    def summary(period: str = Query("", pattern=r"^$|^\d{4}-(0[1-9]|1[0-2])$")):
        with db.connect() as con:
            totals = dict(
                con.execute(
                    "SELECT COALESCE(SUM(total),0) total,COALESCE(SUM(accepted),0) accepted,COALESCE(SUM(rejected),0) rejected,COALESCE(SUM(duplicated),0) duplicated,COUNT(*) imports FROM imports"
                ).fetchone()
            )
            groups = [
                dict(r)
                for r in con.execute(
                    "SELECT branch,substr(sale_date,1,7) period,currency,COUNT(*) records,SUM(amount_cents) amount_cents FROM sales WHERE (?='' OR substr(sale_date,1,7)=?) GROUP BY branch,period,currency ORDER BY period DESC,branch,currency LIMIT 1000",
                    (period, period),
                )
            ]
            return {"totals": totals, "groups": groups, "period": period}

    @app.get("/api/sales")
    def sales(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        with db.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT s.*,i.filename FROM sales s JOIN imports i ON i.id=s.import_id ORDER BY s.id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]

    @app.get("/api/export/{kind}")
    def export(kind: str):
        with db.connect() as con:
            if kind == "sales":
                headers = [
                    "sale_id",
                    "branch",
                    "sale_date",
                    "amount",
                    "currency",
                    "description",
                    "source_file",
                    "source_row",
                    "import_id",
                ]
                rows = (
                    (
                        r["sale_id"],
                        r["branch"],
                        r["sale_date"],
                        f"{r['amount_cents'] // 100}.{r['amount_cents'] % 100:02d}",
                        r["currency"],
                        r["description"],
                        r["filename"],
                        r["source_row"],
                        r["import_id"],
                    )
                    for r in con.execute(
                        "SELECT s.*,i.filename FROM sales s JOIN imports i ON s.import_id=i.id ORDER BY s.id"
                    )
                )
            elif kind == "issues":
                headers = [
                    "source_file",
                    "source_row",
                    "status",
                    "reason",
                    "raw_data",
                    "import_id",
                ]
                rows = (
                    tuple(r)
                    for r in con.execute(
                        "SELECT i.filename,o.source_row,o.status,o.reason,o.raw_json,o.import_id FROM outcomes o JOIN imports i ON i.id=o.import_id WHERE o.status!='accepted' ORDER BY i.created_at,o.source_row"
                    )
                )
            elif kind == "summary":
                headers = ["branch", "period", "currency", "records", "amount_cents"]
                rows = (
                    tuple(r)
                    for r in con.execute(
                        "SELECT branch,substr(sale_date,1,7),currency,COUNT(*),SUM(amount_cents) FROM sales GROUP BY branch,substr(sale_date,1,7),currency ORDER BY 1,2,3"
                    )
                )
            else:
                raise HTTPException(404, "Exportación no encontrada.")
            content = to_csv(headers, rows)
        return Response(
            content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="dataflow-{kind}.csv"'
            },
        )

    @app.post("/api/demo", status_code=201)
    def demo():
        # Demo data is synthetic. No delete/reset endpoints and no outbound requests.
        mapping = {k: k for k in (*FIELDS, "description")}
        return [
            import_csv(db, p.read_bytes(), p.name, mapping)
            for p in sorted((ROOT / "demo").glob("*.csv"))
        ]

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static/index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
