"""Local, read-only viewer for an already exported recommendations CSV."""

from __future__ import annotations

import csv
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = PROJECT_ROOT / "var" / "recommendations_real.csv"
VIEWER_DIR = PROJECT_ROOT / "web" / "viewer"
HEADERS = {
    "sku": ("sku", "sku_id"),
    "supplier": ("supplier", "supplier_id"),
    "qty_recommended": ("qty_recommended", "recommended_qty"),
    "reason": ("reason", "reason_short", "reason_short.ru", "reason_ru"),
    "urgency": ("urgency",),
}
SUPPLIERS = {"se": "SE", "systeme electric": "SE", "iek": "IEK", "иэк": "IEK"}


def read_recommendations(csv_path: Path) -> list[dict[str, str]]:
    """Read five display columns without changing codes, quantities or the file."""
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
            header_line = source.readline()
            if not header_line.strip():
                raise ValueError("CSV пуст: требуется строка заголовков.")
            # Infer the delimiter from the header, never from free-form reasons.
            try:
                dialect = csv.Sniffer().sniff(header_line, delimiters=",;\t")
            except csv.Error as exc:
                raise ValueError("Не удалось распознать разделитель CSV.") from exc
            source.seek(0)
            reader = csv.DictReader(source, delimiter=dialect.delimiter, strict=True)
            raw_headers = reader.fieldnames or []
            normalized = [header.strip() for header in raw_headers]
            if len(normalized) != len(set(normalized)):
                raise ValueError("CSV содержит повторяющиеся заголовки.")
            mapping: dict[str, str] = {}
            for target, aliases in HEADERS.items():
                matches = [raw for raw in raw_headers if raw.strip() in aliases]
                if len(matches) != 1:
                    raise ValueError(
                        f"Для поля {target} требуется ровно одна колонка: "
                        + ", ".join(aliases)
                        + "."
                    )
                mapping[target] = matches[0]

            result: list[dict[str, str]] = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(
                        "Число полей строки не совпадает с заголовком CSV."
                    )
                item = {target: row[column] for target, column in mapping.items()}
                supplier = item["supplier"].strip()
                item["supplier"] = SUPPLIERS.get(supplier.casefold(), supplier)
                result.append(item)
            return result
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail="CSV недоступен. Проверьте наличие готового файла и права чтения.",
        ) from exc
    except UnicodeError as exc:
        raise HTTPException(
            status_code=422, detail="CSV должен быть в кодировке UTF-8 (допустим BOM)."
        ) from exc
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail="Некорректный формат CSV.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def create_app(csv_path: Path | None = None) -> FastAPI:
    """Build a separate demo app; no dependency on engine, adapters or main API."""
    configured = csv_path or Path(
        os.environ.get("EKT_RECOMMENDATIONS_CSV", DEFAULT_CSV)
    )
    if not configured.is_absolute():
        configured = PROJECT_ROOT / configured
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"]
    )

    @app.middleware("http")
    async def local_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/recommendations", response_class=JSONResponse)
    def recommendations() -> list[dict[str, str]]:
        return read_recommendations(configured)

    # Only this directory is public, never the repository or var/.
    app.mount("/", StaticFiles(directory=VIEWER_DIR, html=True, check_dir=False))
    return app


app = create_app()
