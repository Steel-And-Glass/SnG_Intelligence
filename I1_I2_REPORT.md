# I1/I2 — integración de Intelligence con Control

Fecha: 13 de noviembre de 2026. Implementación local, sin commit ni push.

## Estado inicial y alcance

Los tres checkouts estaban limpios en `feature/identity-areas-v1`. No había cambios
locales de Claude que sobrescribir; se preservó la interfaz ya integrada.

| Repositorio | HEAD inicial y final (sin commits) |
| --- | --- |
| Intelligence | `dd8526c2cf45f81f9dead5bf7c90e13cfed9a57c` |
| Backend | `e792d34e91eeb5fd9c8482be1199778a226da471` |
| Frontend | `2a8b5671c01227d3ae4aba3d76047ef68e857503` |

Ya existían Agent Core, Responses, herramientas cerradas, referencias, presentación,
conversaciones persistentes/memoria, STT/TTS y Live con sideband. El Frontend ya tenía
`IntelligenceLauncher`, panel, chat, servicio/BFF, conversaciones, referencias y controles
de voz. No se reconstruyó ninguno. Backend no tiene cambios de código ni configuración.
No se ejecutaron migraciones ni consultas contra bases operativas o conversaciones reales.

## I1: matriz contractual

Rutas GET. `{id}` es un UUID validado. Las fuentes se inspeccionaron en el checkout
Backend indicado arriba: controladores, registros Application y stores/permisos relevantes.
Las proyecciones tipadas descartan campos no consumidos; no pasan JSON arbitrario al modelo.

| Endpoint | Contrato Control / compatibilidad inicial | Novedades u obsolescencia | Permiso efectivo | Consumidor / acción |
| --- | --- | --- | --- | --- |
| `/api/auth/me` | CurrentUserResponse, compatible | roles existe; identidad oficial sigue validada | autenticado | guard existente, sin conceder acceso por header |
| `/api/management/overview` | ManagementOverviewResponse, compatible | áreas Installation/Engineering | Management activo | overview/snapshot; labels humanos ampliados |
| `/api/management/tasks` | ManagementTaskResponse, compatible | nuevas tareas; quotationRound null operativo | Management activo | list_management_tasks/snapshot; labels ampliados |
| `/api/management/quotation-portfolio` | ManagementQuotationPortfolioResponse y Mix, compatible | rankings/coverage/precios COP vigentes | Management activo | get_quotation_portfolio conservada |
| `/api/management/analytics/surfaces` | ManagementSurfacesResponse, faltaba | Decimal string, tres coberturas, página ordenada | Management activo | nueva get_management_surfaces |
| `/api/management/dashboard-dataset` | dataset real adicional | dataset completo de proyectos/tareas | Management activo | auditado; no se añade otra fuente redundante/no acotada |
| `/api/projects` y `/api/projects/{id}` | ProjectResponse, incompatible | createdBy obsoleto; createdByName/isCreatedByMe actuales | ProjectReadScope | contrato corregido; find_projects/details existentes |
| `/api/projects/{id}/tasks` | ProjectTaskResponse, compatible | tipos de tarea operativos y áreas nuevas | acceso al proyecto | details/compare; sin recalcular plazos |
| `/api/projects/{id}/documents` | DocumentListResponse, compatible | metadata, reemplazos, handoff | permisos oficiales de documentos | tools y análisis existentes conservados |
| `/api/projects/{id}/notifications` | ProjectNotificationResponse, compatible | sin cambio requerido | acceso oficial del proyecto | get_project_activity conservada |
| `/api/projects/{id}/budget-quotation/view` | ConfirmedBudgetQuotationView, incompatible | economics nuevo rechazado por extra=forbid anterior | acceso oficial a la vista | DTO tipado opcional + proyección; precios de Presupuestos identificados |
| `/api/projects/{id}/commercial-quotation/view` | ConfirmedCommercialQuotationView, compatible | versiones y precios COP actuales | acceso oficial a la vista | get_commercial_quotation conservada |
| `/api/projects/{id}/quotation-rounds` | historial oficial, compatible | cobertura y límites existentes | acceso oficial | get_quotation_rounds conservada |
| `/api/projects/{id}/client-quotation-decision` | decisión oficial, compatible | no inferir decisión desde tareas | acceso oficial | get_client_quotation_decision conservada |
| `/api/projects/{id}/initial-deposit` | AccountingState, compatible | anticipo no equivale a ingreso/saldo | acceso oficial | get_initial_deposit conservada |
| `/api/projects/{id}/deposit-verifications` | VerificationState, faltaba | revisiones Pending/Approved/Rejected, fechas, documentos | ProjectReadScope | nueva get_deposit_verifications |
| `/api/projects/{id}/measurements` | MeasurementState, faltaba | estructuras activas/retiradas, medidas, entregas/snapshot | Installation o Management y scope | nueva get_project_measurements |
| `/api/projects/{id}/engineering` | EngineeringState/Workspace, faltaba | paquetes, Actas, documentos/versiones, avance oficial | ProjectReadScope | nueva get_project_engineering |
| `/api/projects/{id}/opening-records` | OpeningState, faltaba | rondas/documentos/estructuras de flujo anterior | ProjectReadScope | nueva get_project_opening_records |
| `/api/projects/{id}/incremental-opening-records` | CommercialOpeningState, faltaba | presentaciones, revisiones, aceptaciones por estructura/versión | ProjectReadScope | nueva get_project_incremental_opening_records |
| `/api/projects/{id}/opening-filings` | OpeningFilingsView, faltaba | radicaciones, OP, versiones borrador/confirmadas | ProjectReadScope | nueva get_project_opening_filings |
| `/api/operations/releases`, `/preparations` y subrutas | existen; fuera del permiso gerencial | extracciones/conflictos/revisión humana | OperationsHead y subject configurado | NO integradas ni incluidas en allowlist |

Clientes se identifican mediante campos oficiales ya presentes en búsqueda/listados/agregados;
no se incorpora un cliente HTTP genérico ni un acceso a tablas de clientes.

## I2: herramientas y evidencia

22 herramientas visibles: se mantienen las 15 anteriores y se agregan siete. La allowlist
solo suma las rutas verificadas. Superficies admite exclusivamente una query canónica generada
por código: `skip`, `ascending` y opcional `projectId`; no admite filtros arbitrarios, URLs,
parámetros repetidos ni queries en las nuevas rutas por proyecto.

Las seis nuevas lecturas por proyecto requieren referencia fresca y no ambigua en el turno.
Un 404 produce disponibilidad false con data null; no significa cantidad cero, ausencia de
trabajo ni permiso para intentar otra vía. 401/403/5xx abortan con los errores seguros existentes.
Los DTO con projectId verifican que corresponda al solicitado, incluido el AccountingState
anidado de verificación. OpeningFilingsView no incluye projectId: se mantiene el alcance de
la ruta oficial, sin fabricar una identidad desde su nombre.

Los resultados conservan IDs de estructuras, entregas, versiones, documentos y aceptaciones;
se mantienen borradores y confirmaciones como estados distintos. No hay conteos acumulados
sumando apariciones de una estructura entre documentos, Actas o versiones.
Las referencias públicas siguen siendo las referencias verificadas existentes a proyectos;
no se inventan enlaces navegables a una OP, Acta o radicación.

Las proyecciones operativas omiten Subjects, hashes, claves de almacenamiento, capacidades de
escritura, asignaciones de identidad e historial detallado de auditoría. Conservan estados,
fechas, revisiones, estructuras, cobertura y metadata necesarias para estas consultas.
No interpretan bytes de fotos/croquis ni exponen nuevas descargas. La lectura de metadata no
autoriza automáticamente al analizador documental: este conserva selección y permisos propios.
Se mantiene el límite de 48.000 bytes por resultado y 128.000 por transcript del agente;
resultados excesivos fallan sin truncar ni presentarse como completos.

### Superficies

- quoted: agregado oficial de los ítems comerciales vigentes, ya incluye cantidad.
- measured: referencia rectangular oficial de dimensiones reales por estructura activa válida.
- filed: puede ser null por falta de definición de versión congelada; no se reemplaza por medidas.
- Totales corresponden al filtro completo; projects es una página de hasta 50 filas, ordenada
  oficialmente por superficie cotizada. Se conservan skip/pageSize/hasMore/totalProjects.
- Se admiten proyecto, paginación y orden. Los otros filtros de Control (cliente, ciudad,
  línea, área y estado) no se exponen todavía al modelo.
- Decimal conserva precisión; no se multiplican cantidades, recalculan sumas ni calculan
  pendientes/porcentajes entre magnitudes no comparables. Cero y null siguen distintos.
- Prompt exige m² y formato colombiano; renderizado hablado expande m² a «metros cuadrados».
  La cifra de superficie no se convierte determinísticamente a palabras; TTS pronuncia el
  decimal. Se conservan nombre principal del proyecto, SG auxiliar y fechas Bogotá.

### Compatibilidad comercial

Se corrigieron dos incompatibilidades de wire contract: ProjectResponse y economics de
Presupuestos. Economics usa precios Decimal COP y conserva status, projectTotalCell,
mainItemTotalsDiffer y filas oficiales. Null significa fuente no disponible; no se deduce
un precio desde cantidades. La cotización comercial continúa siendo la fuente de precio vigente.
No se tocaron cálculos, decisiones comerciales, rondas, Portfolio/Mix ni workflows.

## Conversación y voz

Prueba offline nueva: ranking de superficies → consulta de tareas actualizadas → comparación
de dos referentes en orden. El repositorio de conversación es un doble en memoria;
no se cambió persistencia ni esquema. Los referentes históricos identifican, no acreditan
estados actuales. Las pruebas cubren ambigüedad, referencias inventadas y errores de lectura.

Chat HTTP y delegación Live simulada ejecutan get_management_surfaces mediante el mismo
Agent/ToolBox. Voice básico sigue inyectando ese mismo Agent. No hay catálogo empresarial
paralelo en GPT-Live ni ejecución de tools en el navegador. Se conservan reautorización,
credenciales efímeras, cierre, store=false y arquitectura STT/TTS/Live.
Las pruebas con FakeModel comprueban protocolo y límites; no demuestran por sí solas que un
modelo real elija la herramienta o formule correctamente la respuesta.

## Frontend

Se conservan launcher de Gerencia, panel, tipografía, colores, navegación, layout responsive,
referencias, conversación durable, estados vacíos/errores y controles de voz existentes.
No cambia el contrato HTTP de chat, conversación o Voice.

Solo se modifica el BFF para reenviar `X-SnG-Active-Role: Management` después de su comprobación
existente y declarar `Vary: Authorization, X-SnG-Active-Role`. Continúa omitiendo cookies y
headers privados. Intelligence rechaza un rol explícito distinto/vacío/duplicado antes de
consultar Control. Los clientes directos antiguos sin header siguen funcionando exclusivamente
con identidad Management validada por Backend; no se toma el header como autorización.

## Seguridad y validación

Se mantienen TLS verificado, origen fijo, GET cerrado, sin cookies/redirecciones ni URLs del
modelo. Nuevas pruebas verifican query/método/origen, permisos, rol activo, proyecto incorrecto,
privacidad, datos no disponibles, límite de payload y grounding. La suite anterior conserva
pruebas de documentos no autorizados, tokens inválidos, SDK store=false y limpieza Live.

| Validación | Resultado |
| --- | --- |
| Intelligence pytest completo | 1.298 pasan, 1 omitida opt-in PostgreSQL temporal |
| Nuevas pruebas I1/I2 | 52 casos pasan; fixtures sintéticas + HTTP/SDK/Live dobles |
| Ruff / format | pasan |
| mypy --strict app | pasa, 86 módulos |
| Frontend suite completa | 1.563 pasan, 81 archivos |
| Frontend BFF después de cuatro casos adicionales de rol | 34 pasan (incluye los 4 nuevos) |
| Frontend lint / typecheck / build | pasan; lint también repetido tras añadir esos casos |
| Backend regresión pertinente | 99 pasan: API Management/Accounting/QuotationRead/Measurement/Engineering y contratos incrementales |
| git diff --check | comprobado al cierre en ambos repositorios editados |

La primera ejecución de pytest encontró un bloqueo WinError 5 en temporales del sandbox;
la ejecución fuera del sandbox pasó sin alterar tests de migración. Hay un warning existente
de deprecación Starlette TestClient/httpx. La compilación Debug del Backend encontró DLL
bloqueadas por el servicio activo; se ejecutaron los tests con configuración aislada
`IntelligenceAudit`, sin detener el servicio. No se incluyeron suites Persistence del Backend.

### Qué se verificó y qué no

| Modalidad | Estado |
| --- | --- |
| Implementación + lectura de fuentes efectivas | Sí |
| Mocks/fixtures y contratos HTTP in-process | Sí |
| Backend de pruebas HTTP con stores dobles | Sí |
| PostgreSQL temporal | No ejecutado; prueba opt-in omitida |
| Control local con identidad Google real | No ejecutado en este bloque |
| OpenAI real (Responses/STT/TTS/Live) | No ejecutado en este bloque |
| Inspección visual autenticada en navegador | No ejecutada; UI conservada, pruebas de componentes pasan |

## Límites y funcionalidades no implementadas

No hay agregado gerencial específico para total de anticipos, verificaciones, paquetes o
liberaciones. Se puede consultar un proyecto y carga de tareas por área, sin presentar un
barrido de proyectos como agregado oficial. No se expone OperationsHead a Gerencia.
No existe fuente integrada de fabricación ejecutada, facturación, rentabilidad, saldo pendiente
ni recaudo completo. No se infieren desde cotización, anticipo, medición o liberación documental.
No se añaden nuevos permisos, endpoints Backend, producción, RAG, memoria o workflows.
Los nombres humanos de responsables de estas nuevas vistas no se fabrican a partir de Subjects.

## Smoke manual preciso (pendiente)

1. Mantener el Backend con su perfil HTTPS real: launchSettings.json declara
   `https://localhost:7265` (también http 5051). No desactivar TLS.
2. Configurar privadamente Intelligence: `SNG_CONTROL_BASE_URL=https://localhost:7265`, timeout
   positivo, `SNG_INTELLIGENCE_DATABASE_URL` apuntando exclusivamente a su DB propia ya preparada,
   `OPENAI_API_KEY` y `SNG_INTELLIGENCE_MODEL`. No copiar credenciales a consola, logs o reporte.
   No ejecutar migraciones de esta tarea sobre la base habitual.
3. Arrancar desde Intelligence con el puerto elegido explícitamente para este smoke:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --loop app.core.event_loop:loop_factory --env-file .env --host 127.0.0.1 --port 8001 --no-access-log
   ```

   El README general utiliza 8000; aquí 8001 coincide con la URL de ejemplo del BFF.
   Si las variables ya están en el proceso, omitir `--env-file .env`.
4. En Frontend configurar privadamente `SNG_INTELLIGENCE_BASE_URL=http://127.0.0.1:8001`,
   URL del Backend e identidad Google según su README. Ejecutar `pnpm dev --port 3000`.
   Abrir http://localhost:3000, iniciar sesión real y seleccionar rol Management.
5. Verificar GET http://127.0.0.1:8001/health; abrir Intelligence desde Gerencia.
   Session/resume deben responder 200 por el BFF. No copiar headers ni exportar HAR/SDP.
6. Preguntar «¿Cuántos metros cuadrados tenemos cotizados?» y «Muéstrame los proyectos con
   más metros cuadrados». Comparar con el endpoint oficial surfaces usando la misma identidad
   y filtro. Verificar totals, unidad, cobertura, hasMore y referencias, no solo el texto.
7. En la misma conversación: «¿Cuál de ellos tiene tareas vencidas?» y «Compara los dos
   primeros». Verificar nuevos GET de tareas/detalles y orden de referentes; luego F5 y repetir
   una consulta actual. No tomar la respuesta histórica como evidencia nueva.
8. Elegir un nombre REAL devuelto, nunca UUID inventado: preguntar por medidas radicadas,
   Ingeniería, Actas/aceptaciones parciales y Radicaciones de Vanos. Comparar las estructuras y
   versiones concretas con las vistas oficiales. Verificar que borradores no sean liberaciones.
9. Sobre ese proyecto consultar comprobantes pendientes/rechazados y anticipo; contrastar
   deposit-verifications/initial-deposit. Consultar precio comercial y, explícitamente, importes
   de Presupuestos; no mezclar fuentes ni afirmar ventas.
10. Preguntar «¿Cuántos m² hemos fabricado?» y «¿Cuánto hemos facturado?»; debe reconocer la
    falta de fuente. Preguntar por una búsqueda ambigua real si existe; debe pedir precisión.
11. Cambiar rol activo fuera de Management: el acceso del launcher desaparece y las solicitudes
    BFF con rol incompatible deben ser rechazadas, sin acceso alternativo a Operaciones.
12. Para voz básica configurar los modelos STT/TTS, `SNG_INTELLIGENCE_TRANSCRIPTION_LANGUAGE=es`
    y voz seleccionada. Probar la misma pregunta por voz; un .m4a se carga como audio/mp4.
    Confirmar transcripción, consulta oficial y pronunciación de metros cuadrados.
13. Para Live configurar `SNG_INTELLIGENCE_LIVE_MODEL`, `SNG_INTELLIGENCE_LIVE_DELEGATION_MODEL`,
    `SNG_INTELLIGENCE_LIVE_VOICE` y los límites de su configuración existente. Con permisos de
    micrófono, abrir Live, repetir superficies y un seguimiento sobre el proyecto real; verificar
    sideband, reautorización por turno, respuesta y cierre. Revisar solo telemetría segura
    (nombres de operaciones/latencias), nunca tokens, audio, preguntas completas o SDP.
14. Comprobar en móvil/escritorio apertura/cierre, foco, referencias, carga y errores sin alterar
    diseño. Documentar resultados manuales por separado, sin datos empresariales sensibles.

La certificación externa de voz queda pendiente de ese smoke real. No se presenta esta
validación offline como una integración autenticada completa contra Control/OpenAI.


## Estado final de archivos y seguridad

Intelligence: 25 archivos nuevos/modificados (contratos, cliente, tools, prompt/presentación,
rol activo, tests y documentación). Frontend: solo bridge.ts y su prueba. Backend: 0 cambios.
Ningún archivo en staging; los HEAD indicados se conservaron. No commit, push, reset ni clean.

La revisión de archivos modificados/no versionados no encontró .env, audio, SDP, logs ni
archivos temporales candidatos a versionado. La búsqueda de patrones de credenciales y de
valores secretos disponibles en el proceso no detectó coincidencias; no se imprimieron valores.
La revisión se limita a los cambios de este bloque, no constituye auditoría de toda la historia Git.
Ruff, formato, mypy estricto y diff --check se comprobaron nuevamente al cierre.

Tampoco se crea un ranking global de recotizaciones ni un archivo histórico de precios desde
barridos: se conserva el historial oficial por proyecto y sus límites. Comparar versiones solo
puede afirmar diferencias que las lecturas actuales acrediten, sin reconstruir valores ausentes.
