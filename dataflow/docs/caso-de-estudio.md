# Caso propio: Yanz DataFlow

## Problema y alcance

Consolidar ventas de varias sucursales exige reconciliar formatos y separar errores de datos. Este caso utiliza exclusivamente CSV sintéticos reproducibles. No hay empresa contratante, ahorro comercial observado ni métricas inventadas.

## Solución

Interfaz de importación con asociaciones explícitas, formatos de fecha e importe seleccionables, ledger de resultados por línea y ventas únicas. Exporta datos consolidados e incidencias con procedencia. La transacción registra la contabilidad completa o revierte ante un fallo estructural.

## Decisiones

SQLite mantiene ventas, importaciones y resultados en un archivo transaccional. Restricciones persistentes y escritores serializados protegen reimportaciones simultáneas. Los importes son enteros; no se agregan monedas distintas. Un conflicto se conserva como incidencia, sin sustituir la venta original. Sin Pandas, Redis, nube ni colas porque el volumen inicial no los exige.

## Evidencias

`tests/test_pipeline.py` recorre los criterios de aceptación mediante ejemplos con totales conocidos, una BD temporal y HTTP TestClient. `evidence/tests.xml` recoge los resultados de ejecución. `evidence/benchmark.json` documenta tres tamaños con oráculo de conteos e importes. JavaScript compilado de TypeScript estricto. No hay captura real ni auditoría completa de accesibilidad; son pendientes explícitos.

## Límites y mejoras

CSV limitado a 5 MiB/50 000 registros por archivo y uso local sin cuentas. Benchmark de una sola ejecución por tamaño en un contenedor compartido. Añadir Excel después de diseñar límites y normalización de celdas; añadir autenticación y control de recursos antes de considerar un uso compartido.

## Cómo explicarlo en una demo

Cargar los datos sintéticos, comprobar que las categorías suman 60, inspeccionar un rechazo y su línea, exportar el consolidado, reimportar y demostrar que no varían los totales. Explicar la diferencia entre duplicado idéntico y conflicto con otra cantidad.
