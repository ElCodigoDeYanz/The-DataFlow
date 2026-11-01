# Yanz DataFlow

Caso demostrativo propio de **Yanz Studio Systèmes / El Código de Yanz**. Construido desde cero; no representa un cliente ni experiencia laboral. Python 3.12+, FastAPI, SQLite y TypeScript estricto. Sin conexiones externas en la aplicación.

## Ejecutar

Desde esta carpeta, Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python run.py
```

Abre **http://127.0.0.1:8001** y pulsa **Cargar datos sintéticos**. Los dos CSV incluidos producen 60 filas: consulta `demo/expected.json` para el oráculo reproducible. Pulsa de nuevo y comprueba que los totales no cambian. Windows: activar con `.venv\Scripts\activate` y usar `python` para crear el entorno. No es necesario Node para ejecutar: el JavaScript compilado está incluido.

Opcional: `DATAFLOW_DB` cambia la ubicación de SQLite; por defecto es `runtime/dataflow.sqlite3`, anclada al proyecto. `.env.example` documenta la variable; la aplicación no carga `.env` automáticamente. No se entregan datos de ejecución ni secretos. El servidor escucha únicamente en localhost por defecto.

## Flujo propio

1. Selecciona un CSV UTF-8, separador, formato de fecha e importe.
2. Revisa las columnas y asocia identificador, sucursal, fecha, importe y moneda. Descripción opcional.
3. Valida y consolida. Cada fila queda registrada como válida, rechazada o duplicada.
4. Abre **Ver filas** para inspeccionar el número de línea física y el motivo. Hay paginación.
5. Descarga consolidado, incidencias y resumen, con archivo y fila de origen.

`demo/01-ventas.csv` y `02-ventas.csv` son sintéticos. Generación: `python scripts/generate_demo.py`. No hay datos personales ni archivos de clientes.

## Reglas

- Cinco campos obligatorios; esquema: `sale_id,branch,sale_date,amount,currency`, y `description` opcional.
- Una venta = una fila, sin líneas de detalle. Clave de negocio `(sucursal normalizada, identificador)`. Identificadores sensibles a mayúsculas. Sucursal normalizada con Unicode NFKC, mayúsculas y espacios colapsados.
- La misma clave y los mismos valores normalizados = duplicado. Misma clave y datos distintos = rechazo por conflicto, sin sobrescribir la venta anterior.
- SHA-256 del contenido + configuración canónica identifica una importación. El nombre del archivo no interviene. Repetirla devuelve su resultado original; cambiar reglas crea otra importación y aplica deduplicación por venta.
- Fechas explícitas `AAAA-MM-DD` o `DD/MM/AAAA`. Sin inferencia ambigua.
- Importes positivos, hasta diez dígitos enteros y dos decimales, sin separadores de miles. Decimal e integer cents; sin float en persistencia. Devoluciones/importes cero no se admiten en esta versión.
- PEN, USD y EUR, separados siempre en resúmenes. No se convierten monedas.
- UTF-8 o UTF-8 BOM, coma/punto y coma/tabulación; máximo 5 MiB, 50 000 registros, 40 columnas y 2 000 caracteres por campo. Descripción hasta 200. CSV mal formado, cabecera inválida o límite excedido rechaza todo el archivo; errores de datos rechazan solo la fila.
- Filas vacías cuentan como rechazadas. Campos CSV multilínea son un registro con procedencia en su primera línea física.
- Exportaciones prefijan con apóstrofo las celdas con `= + - @` iniciales, incluso tras espacios, o controles iniciales. No basta entrecomillar el CSV. Esto transforma el texto exportado; el original queda preservado en SQLite.

## Arquitectura mínima

`api.py` adapta HTTP; `pipeline.py` normaliza y aplica reglas; `database.py` persiste. Una transacción SQLite `BEGIN IMMEDIATE` por importación; constraints de unicidad, foreign keys y WAL. El fichero completo es acotado y se procesa en memoria. DuckDB/Pandas no son necesarios para este tamaño y la trazabilidad transaccional favorece SQLite. Las aplicaciones del portafolio no importan código entre sí.

La interfaz está en `frontend/app.ts`; TypeScript usa `strict`, `noUncheckedIndexedAccess` y `exactOptionalPropertyTypes`. HTML semántico, formularios etiquetados, estado accesible, foco visible y CSS adaptable con `prefers-reduced-motion`. No se han confirmado visualmente esos comportamientos en navegador en este entorno.

## API

Contrato completo: `GET /openapi.json`. Operaciones principales: `POST /api/preview`, `POST /api/imports` (multipart: file, mapping JSON, delimiter, date_format, number_format), `GET /api/imports`, `GET /api/imports/{id}/outcomes?offset=0&limit=20`, `GET /api/sales`, `GET /api/summary?period=2026-10`, `GET /api/export/sales|issues|summary`, `POST /api/demo`.

Listas: 30 importaciones recientes; resumen hasta 1 000 grupos; filas y ventas paginadas hasta 100 por página. Exportaciones abarcan todos los registros. Los indicadores de contabilidad son globales; el filtro de periodo afecta al resumen de ventas.

## Verificación

```bash
python -m pytest -q --junitxml=evidence/tests.xml
python -m compileall -q dataflow scripts run.py
# Linux: resource.getrusage usa KiB para ru_maxrss
python scripts/benchmark.py
# Solo al editar TypeScript; Node 20+
npm ci
npm run build
```

`requirements-lock.txt` fija las dependencias usadas en la verificación, incluidas las de pruebas. `evidence/tests.xml` contiene el resultado real. `evidence/benchmark.json` guarda tiempo, memoria máxima RSS y exactitud para 1k/10k/50k filas. Un proceso nuevo por tamaño; una medición por tamaño; tiempo de importación excluye generación; memoria incluye intérprete, datos de entrada y SQLite. Entorno compartido Linux, no laptop del autor. Sin afirmaciones de SLA ni de rendimiento en producción.

## Estado honesto

**Implementado y comprobado:** reglas, recuentos, importación atómica, concurrencia entre imports, reimportación, procedencia, exportación segura, API, datos y mediciones reproducibles. Interfaz compilada con TypeScript estricto; HTML servido por la API.

**Pendiente:** revisión visual de escritorio/móvil y capturas reales. La infraestructura de preview no dispone del runtime Python; no se adjuntan imágenes simuladas. Ver `evidence/verification.md`.

**Ampliación futura:** Excel, reglas de negocio configurables, trabajos en segundo plano y autenticación para equipos. Excel se aplaza: requiere parser adicional y validar tipos, hojas, fórmulas y límites propios. Esta versión no procesa hojas de cálculo.

Uso local de una persona. No exponer a internet: no hay control de acceso de usuarios, TLS ni cuotas por usuario. El límite acotado protege cada importación, pero no limita el crecimiento acumulado de la BD. Copia la BD con SQLite backup API para un respaldo coherente si la app está activa. No se despliega ni se publica con esta entrega.
