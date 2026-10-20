> **Absorbido por [Writer's Hoard](https://github.com/Luissalet/Writers-Hoard-Desktop).**
> Las funciones de este proyecto se mantienen en el Hoard fusionado, con módulos independientes y apagados inicialmente.
> El código y las instrucciones siguientes se conservan como referencia histórica; usa el repositorio enlazado para la instalación actual.

# Gutenberg's Hoard

**Un espacio local para publicaciones editoriales paginadas.** Gutenberg organiza los documentos de publicación y sus referencias de origen. El motor incorporado de Gutenberg es responsable de la maquetación nativa, las historias, los marcos, las páginas maestras, los estilos, las muestras de color, el historial y el renderizado.

El motor y el editor completos viven en `native/`, con código fuente, formato ZIP, bibliotecas, licencias y build propios. La fuente inicial es DesignCraft0.2.1, revisión `80b3e3cb74618b02f40b80ac7c2fa35e5da4e1af`, incorporada y mantenida en este repositorio. No requiere un checkout, paquete ni CLI/GUI de aquella aplicación. `native/PROVENANCE.json`, NOTICE y los avisos MIT/Apache/OFL conservan la procedencia y derechos originales. El icono es el del Hoard y la marca protegida de la referencia se ha retirado del código. No se afirma equivalencia universal con otras suites.

## Funciones actuales

- Crear y reabrir archivos `.gutenberg` con páginas A4, A5, Letter o Legal, márgenes, páginas enfrentadas y un flujo de color solicitado.
- Consultar el catálogo MCP real, sus recursos y el registro completo de comandos de Gutenberg. La versión probada devuelve 25 herramientas MCP y 432 comandos; el catálogo se descubre del motor instalado, no se codifica a mano.
- Invocar herramientas, prompts y recursos nativos sin lista restrictiva. Cada publicación puede mantener un `session_id` estable para conservar vivo el proceso de Gutenberg y su historial entre llamadas. El servidor guarda después de cada edición. Al reiniciar Gutenberg, las sesiones del motor se cierran; el deshacer nativo vive durante el proceso, y Gutenberg conserva hasta 30 instantáneas para deshacer tras un reinicio.
- Añadir marcos de texto, consultar y editar historias nativas, crear y aplicar páginas maestras y crear muestras de proceso CMYK desde el espacio de páginas. Para distribuir historias enlazadas, ajustar tipografía, estilos y composición avanzada, se puede continuar en Gutenberg.
- Enlazar una publicación con su fuente mediante referencias `hoard://` y Hoard Hub. La fuente conserva su propietario y no se copia.
- Renderizar vistas previas con Gutenberg.
- Exportar PDF multipágina nativo mediante `file.exportPdf` de Gutenberg. Gutenberg verifica el archivo y el número de páginas, devuelve las advertencias del motor y comprueba si el PDF real permite extraer algún texto. Esa comprobación no demuestra que todas las historias sean buscables: si falla la incrustación de fuentes, el motor puede convertir los glifos en contornos. La exportación nativa no afirma conformidad PDF/X ni PDF/UA.
- Mantener la exportación PDF raster existente para compatibilidad e imágenes RGB previsibles. El texto raster no se puede seleccionar ni buscar; tampoco se conservan trazados vectoriales, separaciones CMYK, tintas planas, sangrado ni conformidad PDF/X. Un límite de megapíxeles evita que documentos grandes agoten la memoria; para documentos largos se reduce la escala.
- Leer los perfiles de trabajo existentes de Hoard Hub. Seleccionar un perfil guarda el contexto de trabajo; no crea cuentas ni inicia o detiene perfiles.

## Instalación en Windows

Python3.11+ y Rust1.95, con HoardLink disponible en su checkout compartido. La instalación crea un entorno dedicado, instala las dependencias y construye los dos ejecutables propios:

```powershell
$env:HOARD_LINK_ROOT = 'C:\ruta\a\HoardLink'
./scripts/setup.ps1 -DebugEngine
```

Sin `-DebugEngine` se solicita un build release. La verificación de esta entrega usa debug; no se atribuye un build release no ejecutado. También puede ejecutarse `python scripts/build_engine.py --debug`. Los binarios quedan en `native/bin/`; source y Cargo.lock están versionados. Las configuraciones históricas `designcraft_cli/gui` se conservan como datos, pero no seleccionan el motor. No se descarga ni configura la app de referencia.

## Asistente de Faustus

Con el lanzador compartido de Hoard Link instalado, la app muestra el panel de Faustus de la familia (un botón flotante). La conversación, el modelo y las herramientas viven en Faustus; esta app solo le dice al panel qué hay abierto.

- **Contexto por vista.** Una publicación abierta se envía como `publication` con su id real (también como proyecto externo del panel), título, número de páginas, preajuste, espacio de color, páginas enfrentadas, márgenes, ruta del archivo, hora de actualización y si se puede deshacer. En la vista de páginas añade la `page` abierta (id `<publicación>:<índice>`, maqueta madre) y los objetos `story` disponibles (id `<publicación>:<historia>`, marcos, desbordada, seleccionada), incluidas las selecciones posteriores a las primeras treinta historias. Solo la historia guardada seleccionada lleva una vista previa de 300 caracteres; las tools nativas recuperan su texto guardado completo. La vista, los ids y los formularios pendientes se capturan juntos antes de resolver los objetos; cambiar de vista mientras espera afecta al siguiente contexto. Las vistas sin publicación abierta no dan objeto activo.
- **Campos sin guardar.** El panel los pide con el evento de ventana `gutenberg:context-request`. Los formularios `publication_create` (aún sin id), `story_edit`, `page_parent`, `frame_create`, `swatch_create` y `source_link` responden solo con los campos que han cambiado, conservando sus valores pendientes completos. El asistente recibe también los cambios al final de un borrador largo.
- **Refresco.** Cuando el asistente termina un turno, la vista abierta se recarga desde el documento en el sitio (`hoard:copilot-turn-end` / `window.hoardCopilot.onTurnEnd`, unidos en una sola recarga); los formularios conservan lo escrito.
- **Guardado.** Guardar una historia envía el texto cambiado junto con el texto con el que se cargó al nuevo `POST /api/publications/{id}/stories/{story}/text` (`text`, `base_text`). Es un compare-and-set atómico bajo el bloqueo de la publicación: si la historia cambió entretanto responde 409 (`StoryConflict`) y no se escribe nada hasta que recargues. Sin `base_text` el texto se reemplaza.
- **Pruebas.** `node --test tests/copilot-context.test.mjs` y `python -m pytest tests/test_copilot_ui.py tests/test_story_save.py tests/test_publication_engine.py`.

La regresión opcional `tests/browser_copilot_context.py` acepta rutas `--cli`, `--sdk` y `--output-dir`, más `--playwright-sitepackages` si hace falta. Usa datos privados, MCP nativo sin ventana, navegador real y el SDK común con proveedor simulado para comprobar borradores largos, la historia31 seleccionada, navegación durante la resolución y un turno con tool nativa que conserva el editor y el borrador. Véase [el contrato API y copilot](docs/copilot.md).

## MCP

El manifiesto de plugin está en [`faustus-plugin.json`](faustus-plugin.json). Inicia `python -m gutenberg_hoard.mcp_server` mediante stdio y configura `PYTHONPATH` para este repositorio y HoardLink. El entorno dedicado contiene HoardLink; el motor se selecciona únicamente del build local.

Las herramientas principales son `gutenberg_publications`, `gutenberg_create_publication`, `gutenberg_engine_catalog`, `gutenberg_engine_session`, `gutenberg_engine_raw_session`, `gutenberg_undo`, `gutenberg_export_pdf` y `gutenberg_link_source`. `gutenberg_export_pdf` acepta `renderer="native"` o `renderer="raster"`; raster sigue siendo el valor por defecto para las llamadas existentes y admite `scale`. La exportación nativa abre el documento registrado sin guardarlo ni modificarlo y devuelve la URL, el número de páginas, el resultado de extracción de texto y las advertencias del motor. Las dos herramientas de sesión permiten despachar herramientas, prompts y recursos nativos sin un filtro de funciones. El catálogo devuelve los esquemas que anuncia el ejecutable instalado. Cada consumidor puede mantener una sesión estable; las ediciones de publicaciones se guardan y generan una instantánea.

La API se inicia con `python -m gutenberg_hoard`; la entrada MCP usa stdio y no abre un servidor web. Las rutas locales incluyen `/api/health`, `/api/publications`, `/api/native/catalog`, `/api/native/session` y `/api/profiles`.

MCP stdio y el contrato agente HTTP ofrecen19 herramientas. Se conservan los cuatro nombres históricos `gutenberg_designcraft_*` como alias; `gutenberg_render_page` ofrece el PNG de una página y `gutenberg_open_editor` abre el editor completo incorporado. Detalles en [API.md](docs/API.md).

## Datos y compatibilidad

- `data/gutenberg.db` contiene el catálogo local y el historial; cada original se conserva como archivo `.gutenberg` independiente en `data/publications/`.
- El código importa el paquete compartido `hoard-link`; no incluye una copia privada ni recrea contratos compartidos de rutas, escrituras atómicas, tokens, referencias, tema o perfiles.
- `hoard://gutenberg/publication/<id>` identifica una publicación propiedad de Gutenberg. Los otros Hoards mantienen sus registros y originales.
- El motor incorporado, el formato y las APIs evolucionan en este repositorio. La importación histórica no promete compatibilidad futura con la aplicación de referencia.

## Verificación

`./.venv/Scripts/python.exe -m pytest -q` ejecuta la suite y el motor real construido. Datos de QA en carpetas temporales o instancia privada con `GUTENBERG_DATA_DIR` explícito. Los CLI/GUI históricos se fijaron a rutas inexistentes. Se comprobó creación/edición, texto con comparación de base, páginas maestras, CMYK, imágenes incrustadas, cierre/reapertura, undo y PDF multipágina nativo/raster. La UI mantiene Deshacer disponible tras guardar mediante la metadata compartida. No se cargan modelos.

Los ZIP/JSON históricos `.designcraft` se importan a una copia `.gutenberg`, conservando original, ID, carpeta base para recursos enlazados, perfiles e historial. Nuevos guardados usan `application/vnd.gutenberg+zip` y `meta.format=gutenberg`; un snapshot histórico puede conservar su contenedor anterior, que el lector propio admite. Se guarda `original_native_path` sin borrar columnas previas. La GUI y el motor directo también abren un histórico hacia una copia; guardar sin ruta usa esa copia. Guardados explícitos en una sesión raw siguen siendo operaciones elegidas por el llamante.

## Referencias upstream

- [Código y README de DesignCraft](https://github.com/storytold/designcraft/blob/main/README.md)
- [Lanzamientos de DesignCraft](https://github.com/storytold/designcraft/releases)
- [Documentación MCP de DesignCraft](https://github.com/storytold/designcraft/blob/main/docs/mcp.md)
- [Protocolo de control de DesignCraft](https://github.com/storytold/designcraft/blob/main/docs/control-protocol.md)
- [Paquete compartido HoardLink](https://github.com/Luissalet/HoardLink)

## Licencias

Gutenberg's Hoard se distribuye bajo MIT. DesignCraft es una dependencia upstream separada, bajo MIT o Apache-2.0. Sus avisos y licencias de recursos permanecen en esa distribución.
