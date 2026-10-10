# Guía del usuario

[English](en.md) · [Русский](ru.md) · [Deutsch](de.md) · [Español](es.md) · [中文](zh.md)

## Instalación y ejecución

okama Planner construye flujos de caja mensuales del hogar y proyecciones de Monte Carlo. Admite Python 3.11 o posterior. Instale los complementos `reports` para exportar a Excel. La configuración de desarrollo utiliza Python 3.14; seleccione ese intérprete explícitamente cuando contribuya al código:

```bash
git clone https://github.com/mbk-dev/okama-planner.git
cd okama-planner
poetry env use python3.14
poetry install --extras reports
poetry run python examples/localized_plan.py --output-dir tmp/localized-example
```

El ejemplo no necesita descargar datos de mercado, abrir un navegador ni acceder a una base de clientes. Utiliza importes ficticios en USD y rendimientos mensuales sintéticos congelados. Calcula una vez con `seed=42`, guarda `request.json` y `result.json`, y luego exporta `plan-en.xlsx`, `plan-ru.xlsx`, `plan-de.xlsx`, `plan-es.xlsx`, `plan-zh.xlsx` y archivos interactivos sin conexión `forecast.html` en los directorios `linear/` y `log/` de cada idioma. Abra un archivo HTML localmente para examinar la cartera y el patrimonio neto. Las cinco ediciones comparten los mismos importes en USD, supuestos y resultados numéricos. Una semilla no congela las dependencias: conserve las versiones del entorno para una reproducción exacta.

Seleccione menos ediciones con `--languages en es`. Añada `--image-format png` o `--image-format svg` para generar gráficos estáticos si Chrome o Chromium está instalado; `--browser-executable /path/to/chromium` selecciona el ejecutable. Los archivos HTML y Excel no necesitan navegador.

## Preparar un plan

Parta de [la solicitud ficticia](../../examples/baseline-request.json). Pase la solicitud completa a `forecast(request)` de `okama_planner`. `plan.t0` es el primer mes; indique el horizonte, la fecha de jubilación, activos, obligaciones e ingresos y gastos mensuales. Para cada objetivo, defina un `goal_id` único, su nombre `label`, tipo `kind`, importe actual `amount_pv`, año de valoración `pv_year` y fecha prevista. Las tasas y probabilidades se expresan como fracciones: `0.02` significa 2 %. Los ingresos y gastos se introducen como importes positivos; el registro de flujos asigna un signo negativo a los gastos.

`currency="USD"` determina la moneda del cálculo. `language="es"` en `export_report` o `export_charts` selecciona la presentación en español. El idioma no convierte dinero ni cambia la inflación, los rendimientos de la cartera o los supuestos legales. Las etiquetas del usuario se conservan tal como se introducen; tradúzcalas al preparar otra edición. Consulte [el contrato de localización](../localization.md) para mensajes, formatos y configuración del idioma al iniciar MCP.

Las solicitudes de una sola moneda utilizan una única moneda. Las solicitudes multidivisa definen explícitamente `reporting_currency`, los grupos nativos `currency_groups` y los supuestos cambiarios; los informes traducidos conservan las monedas originales y la moneda de presentación. Consulte [la planificación multidivisa](../multicurrency.md) y [los modos de cartera](../portfolio-modes.md). La localización no añade impuestos o comisiones ausentes de las entradas ni campos gamma/alpha no admitidos a la solicitud de proyección.

## Leer y conservar los resultados

Los importes de informes y gráficos son nominales; la indexación sigue las tasas indicadas. La inflación no convierte automáticamente los gráficos a poder adquisitivo constante. En una escala logarítmica se omiten valores cero y negativos, y las bandas afectadas presentan huecos; consulte el gráfico lineal para esos períodos.

Las exportaciones utilizan instantáneas guardadas de solicitud y resultado sin repetir el cálculo:

```python
import json
from pathlib import Path
from okama_planner.reports import export_report
from okama_planner.charts import export_charts

folder = Path("tmp/localized-example")
request = json.loads((folder / "request.json").read_text())
result = json.loads((folder / "result.json").read_text())
export_report([{"label": "Synthetic USD", "request": request, "result": result}],
              folder / "review.xlsx", language="es")
export_charts(result, folder / "review", language="es")
```

Editar las cifras del libro no recalcula Monte Carlo. Cambie las entradas, ejecute `forecast` de nuevo y guarde nuevas instantáneas antes de exportar un plan modificado. Recalcule las fórmulas de resumen de Excel antes de usar sus valores almacenados en caché. Conserve el JSON original y la información de procedencia junto con las exportaciones.

## Registros locales y privacidad

El registro opcional SQLite almacena localmente clientes, versiones de planes, escenarios y resultados. Guarde nombres y contactos en el registro; identifique a los clientes mediante sus códigos en los materiales compartidos. Mantenga bases y documentos de clientes reales fuera de Git público. La localización modifica textos visibles; los nombres de tablas y columnas SQL, claves JSON, valores enumerados e identificadores técnicos permanecen estables. Consulte [el almacenamiento](../storage.md) para configurar la base y ver ejemplos de API.
