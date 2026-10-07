# Gutenberg's Hoard

**Un espacio local para publicaciones editoriales paginadas.** Gutenberg organiza los documentos de publicación y sus referencias de origen. DesignCraft es responsable de la maquetación nativa, las historias, los marcos, las páginas maestras, los estilos, las muestras de color, el historial y el renderizado.

Esta primera versión es operativa, pero no afirma paridad con las suites de autoedición. El motor verificado es DesignCraft `0.2.1` (commit de lanzamiento `80b3e3c`, 2026-10-06), con licencia MIT o Apache-2.0. Su README incluye el formato `.designcraft`, importación/exportación IDML y exportación PNG; el PDF nativo sigue en su hoja de ruta. Gutenberg conserva todo el catálogo MCP nativo y su vía de llamada, y añade catálogo de publicaciones, referencias de origen, espacio de páginas, sesiones de agente persistentes, instantáneas y deshacer, vistas previas y exportación PDF multipágina verificada.

## Funciones actuales

- Crear y reabrir archivos `.designcraft` con páginas A4, A5, Letter o Legal, márgenes, páginas enfrentadas y un flujo de color solicitado.
- Consultar el catálogo MCP real, sus recursos y el registro completo de comandos de DesignCraft. La versión probada devuelve 25 herramientas MCP y 432 comandos; el catálogo se descubre del motor instalado, no se codifica a mano.
- Invocar herramientas, prompts y recursos nativos sin lista restrictiva. Cada publicación puede mantener un `session_id` estable para conservar vivo el proceso de DesignCraft y su historial entre llamadas. El servidor guarda después de cada edición. Al reiniciar Gutenberg, las sesiones del motor se cierran; el deshacer nativo vive durante el proceso, y Gutenberg conserva hasta 30 instantáneas para deshacer tras un reinicio.
- Añadir marcos de texto, consultar y editar historias nativas, crear y aplicar páginas maestras y crear muestras de proceso CMYK desde el espacio de páginas. Para distribuir historias enlazadas, ajustar tipografía, estilos y composición avanzada, se puede continuar en DesignCraft.
- Enlazar una publicación con su fuente mediante referencias `hoard://` y Hoard Hub. La fuente conserva su propietario y no se copia.
- Renderizar vistas previas con DesignCraft.
- Exportar un PDF multipágina auténtico a partir de imágenes renderizadas. Es **raster RGB**: el texto no se puede seleccionar ni buscar; no conserva trazados vectoriales, separaciones CMYK, tintas planas, sangrado ni conformidad PDF/X. Un límite de megapíxeles evita que documentos grandes agoten la memoria; para documentos largos se reduce la escala.
- Leer los perfiles de trabajo existentes de Hoard Hub. Seleccionar un perfil guarda el contexto de trabajo; no crea cuentas ni inicia o detiene perfiles.

## Instalación en Windows

Instala Python 3.11 o posterior y descarga por separado DesignCraft desde su proyecto oficial. No copies sus ejecutables a este repositorio. La instalación crea el `.venv` dedicado, instala HoardLink en modo editable e instala esta app:

```powershell
$env:HOARD_LINK_ROOT = 'C:\ruta\a\HoardLink'
$env:GUTENBERG_DESIGNCRAFT_CLI = 'D:\ruta\a\designcraft-cli.exe'
.\scripts\setup.ps1 -HoardLink $env:HOARD_LINK_ROOT -DesignCraftCli $env:GUTENBERG_DESIGNCRAFT_CLI
```

La instalación guarda la ruta de DesignCraft en `local-config.json`, ignorado por Git, solo cuando todavía no hay una. Las siguientes instalaciones preservan el valor existente. La app prefiere `GUTENBERG_DESIGNCRAFT_CLI` y después lee el archivo local. Arranca con el Python dedicado:

```powershell
.\.venv\Scripts\python.exe .\scripts\launch.py
```

Hub inicia la app en loopback, puerto estricto `5218`, y ejecuta MCP stdio con el mismo `.venv`. El lanzador manual busca un puerto disponible desde `5218`; `GUTENBERG_PORT=0` solicita un puerto libre al sistema. Los datos se guardan por defecto en `./data`, incluido el perfil aislado de DesignCraft. La aplicación no tiene inicio de sesión ni administración de cuentas.

El botón de escritorio abre el `.designcraft` seleccionado mediante el canal de control documentado por DesignCraft: ejecuta `designcraft.exe --control <puerto>` y luego la CLI verificada llama a `file.open {path}`. El canal solo escucha en loopback y usa un puerto local disponible.

## MCP

El manifiesto de plugin está en [`faustus-plugin.json`](faustus-plugin.json). Inicia `python -m gutenberg_hoard.mcp_server` mediante stdio y configura `PYTHONPATH` para este repositorio y HoardLink. Define `FAUSTUS_PYTHON`, `GUTENBERG_DESIGNCRAFT_CLI` y `HOARDLINK_DIR` en el host.

Las herramientas principales son `gutenberg_publications`, `gutenberg_create_publication`, `gutenberg_designcraft_catalog`, `gutenberg_designcraft_session`, `gutenberg_designcraft_raw_session`, `gutenberg_undo`, `gutenberg_export_pdf` y `gutenberg_link_source`. Las dos herramientas de sesión permiten despachar herramientas, prompts y recursos nativos sin un filtro de funciones. El catálogo devuelve los esquemas que anuncia el ejecutable instalado. Cada consumidor puede mantener una sesión estable; las ediciones de publicaciones se guardan y generan una instantánea.

La API se inicia con `python -m gutenberg_hoard`; la entrada MCP usa stdio y no abre un servidor web. Las rutas locales incluyen `/api/health`, `/api/publications`, `/api/native/catalog`, `/api/native/session` y `/api/profiles`.

## Datos y compatibilidad

- `data/gutenberg.db` contiene el catálogo local y el historial; cada original se conserva como archivo `.designcraft` independiente en `data/publications/`.
- El código importa el paquete compartido `hoard-link`; no incluye una copia privada ni recrea contratos compartidos de rutas, escrituras atómicas, tokens, referencias, tema o perfiles.
- `hoard://gutenberg/publication/<id>` identifica una publicación propiedad de Gutenberg. Los otros Hoards mantienen sus registros y originales.
- La compatibilidad del formato y las funciones de DesignCraft dependen de la versión oficial instalada. Gutenberg no afirma implementar por su cuenta todos los flujos de edición que describe el upstream.

## Verificación

Ejecuta las pruebas con HoardLink y las dependencias instaladas:

```powershell
$env:GUTENBERG_DESIGNCRAFT_CLI = 'D:\ruta\a\designcraft-cli.exe'
pytest -q
```

Las pruebas de integración usan sesiones MCP reales de DesignCraft, crean documentos aislados, los editan y deshacen, renderizan PNG auténticos y verifican cuántas páginas tiene el PDF exportado. No arrancan modelos ni acceden a servicios de red. Pytest guarda las pruebas y los artefactos temporales en sus propios directorios temporales.

## Referencias upstream

- [Código y README de DesignCraft](https://github.com/storytold/designcraft/blob/main/README.md)
- [Lanzamientos de DesignCraft](https://github.com/storytold/designcraft/releases)
- [Documentación MCP de DesignCraft](https://github.com/storytold/designcraft/blob/main/docs/mcp.md)
- [Protocolo de control de DesignCraft](https://github.com/storytold/designcraft/blob/main/docs/control-protocol.md)
- [Paquete compartido HoardLink](https://github.com/Luissalet/HoardLink)

## Licencias

Gutenberg's Hoard se distribuye bajo MIT. DesignCraft es una dependencia upstream separada, bajo MIT o Apache-2.0. Sus avisos y licencias de recursos permanecen en esa distribución.
