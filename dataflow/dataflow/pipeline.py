"""Explicit CSV normalization and atomic, auditable imports. No network access."""

import csv
import hashlib
import io
import json
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import PurePath
from .database import Database

FIELDS = ("sale_id", "branch", "sale_date", "amount", "currency")
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000
MAX_FIELD = 2_000
csv.field_size_limit(MAX_FIELD)


class InputError(ValueError):
    pass


def parse_csv(content: bytes, delimiter: str):
    if len(content) > MAX_BYTES:
        raise InputError("El CSV supera 5 MiB.")
    if delimiter not in (",", ";", "\t"):
        raise InputError("Separador no admitido.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("Usa CSV UTF-8 o UTF-8 con BOM.") from exc
    if "\x00" in text:
        raise InputError("El CSV contiene bytes nulos.")
    try:
        reader = csv.reader(
            io.StringIO(text, newline=""), delimiter=delimiter, strict=True
        )
        headers = next(reader, None)
        if not headers or len(headers) > 40 or any(not h.strip() for h in headers):
            raise InputError("Cabecera vacía o más de 40 columnas.")
        if len(set(headers)) != len(headers):
            raise InputError("Hay nombres de columnas repetidos.")
        records = []
        while True:
            first_line = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                break
            if len(records) >= MAX_ROWS:
                raise InputError("El CSV supera 50 000 registros.")
            records.append((first_line, row))
        return headers, records
    except csv.Error as exc:
        raise InputError(
            "CSV mal formado o campo mayor de 2 000 caracteres. No se importó ninguna fila."
        ) from exc


def normalize(raw: dict, mapping: dict, date_format: str, number_format: str):
    values = {
        k: unicodedata.normalize("NFKC", str(raw.get(v, ""))).strip()
        for k, v in mapping.items()
    }
    missing = [k for k in FIELDS if not values.get(k)]
    if missing:
        raise InputError("Faltan campos: " + ", ".join(missing))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", values["sale_id"]):
        raise InputError(
            "Identificador inválido (1–80 letras, números, _, punto o guion)."
        )
    branch = " ".join(values["branch"].upper().split())
    if len(branch) > 80 or not all(c.isalnum() or c in " -_." for c in branch):
        raise InputError("Sucursal inválida.")
    try:
        date_text = values["sale_date"]
        pattern = r"\d{4}-\d{2}-\d{2}" if date_format == "iso" else r"\d{2}/\d{2}/\d{4}"
        if not re.fullmatch(pattern, date_text):
            raise ValueError()
        day = (
            datetime.strptime(
                date_text, "%Y-%m-%d" if date_format == "iso" else "%d/%m/%Y"
            )
            .date()
            .isoformat()
        )
    except ValueError as exc:
        raise InputError("Fecha inválida para el formato seleccionado.") from exc
    amount = values["amount"]
    pattern = (
        r"\d{1,10}(\.\d{1,2})?" if number_format == "point" else r"\d{1,10}(,\d{1,2})?"
    )
    if not re.fullmatch(pattern, amount):
        raise InputError(
            "Importe inválido: positivo, máximo 2 decimales, sin separador de miles."
        )
    cents = int(Decimal(amount.replace(",", ".")) * 100)
    if cents <= 0:
        raise InputError("El importe debe ser mayor que cero.")
    currency = values["currency"].upper()
    if currency not in ("PEN", "USD", "EUR"):
        raise InputError("Moneda no admitida: usa PEN, USD o EUR.")
    description = values.get("description", "")
    if len(description) > 200:
        raise InputError("Descripción mayor de 200 caracteres.")
    return (values["sale_id"], branch, day, cents, currency, description)


def import_csv(
    db: Database,
    content: bytes,
    filename: str,
    mapping: dict,
    delimiter=",",
    date_format="iso",
    number_format="point",
):
    started = time.perf_counter()
    if date_format not in ("iso", "dmy") or number_format not in ("point", "comma"):
        raise InputError("Formato de fecha o importe no admitido.")
    headers, rows = parse_csv(content, delimiter)
    if any(k not in (*FIELDS, "description") for k in mapping) or not all(
        k in mapping for k in FIELDS
    ):
        raise InputError("Asocia los cinco campos obligatorios.")
    if any(v not in headers for v in mapping.values()) or len(
        set(mapping.values())
    ) != len(mapping):
        raise InputError("Cada campo debe usar una columna existente y distinta.")
    config = json.dumps(
        dict(
            mapping=mapping,
            delimiter=delimiter,
            date_format=date_format,
            number_format=number_format,
        ),
        sort_keys=True,
    )
    sha = hashlib.sha256(content).hexdigest()
    fingerprint = hashlib.sha256((sha + config).encode()).hexdigest()
    batch = str(uuid.uuid4())
    # BEGIN IMMEDIATE serializes competing writers; uniqueness remains a database constraint.
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        prior = con.execute(
            "SELECT * FROM imports WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        if prior:
            return dict(prior) | {"replayed": True}
        safe_name = PurePath(filename.replace("\\", "/")).name[:180] or "archivo.csv"
        con.execute(
            "INSERT INTO imports(id,content_sha256,config_json,fingerprint,filename,created_at,total,accepted,rejected,duplicated,elapsed_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch,
                sha,
                config,
                fingerprint,
                safe_name,
                datetime.now(timezone.utc).isoformat(),
                0,
                0,
                0,
                0,
                0,
            ),
        )
        counts = {"accepted": 0, "rejected": 0, "duplicated": 0}
        for line, row in rows:
            raw = (
                dict(zip(headers, row)) if len(row) == len(headers) else {"_cells": row}
            )
            try:
                if len(row) != len(headers):
                    raise InputError("Cantidad de columnas distinta de la cabecera.")
                value = normalize(raw, mapping, date_format, number_format)
                existing = con.execute(
                    "SELECT sale_id,branch,sale_date,amount_cents,currency,description FROM sales WHERE branch=? AND sale_id=?",
                    (value[1], value[0]),
                ).fetchone()
                if existing:
                    if tuple(existing) == value:
                        status, reason = (
                            "duplicated",
                            "Misma sucursal e identificador; contenido idéntico.",
                        )
                    else:
                        raise InputError(
                            "Conflicto: existe la misma sucursal e identificador con otros datos."
                        )
                else:
                    con.execute(
                        "INSERT INTO sales(sale_id,branch,sale_date,amount_cents,currency,description,import_id,source_row) VALUES (?,?,?,?,?,?,?,?)",
                        (*value, batch, line),
                    )
                    status, reason = "accepted", "Registro válido."
            except InputError as exc:
                status, reason = "rejected", str(exc)
            counts[status] += 1
            con.execute(
                "INSERT INTO outcomes VALUES (?,?,?,?,?)",
                (batch, line, status, reason, json.dumps(raw, ensure_ascii=False)),
            )
        con.execute(
            "UPDATE imports SET total=?,accepted=?,rejected=?,duplicated=?,elapsed_ms=? WHERE id=?",
            (
                len(rows),
                counts["accepted"],
                counts["rejected"],
                counts["duplicated"],
                round((time.perf_counter() - started) * 1000, 2),
                batch,
            ),
        )
        return dict(
            con.execute("SELECT * FROM imports WHERE id=?", (batch,)).fetchone()
        ) | {"replayed": False}


def safe_cell(value):
    text = str(value)
    # Quoting alone does NOT prevent spreadsheet formula execution.
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or text.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + text
    return text


def to_csv(headers, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return "\ufeff" + output.getvalue()
