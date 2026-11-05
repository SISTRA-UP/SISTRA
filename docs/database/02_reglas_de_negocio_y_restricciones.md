# SISTRA --- Reglas de negocio, integridad y decisiones aprobadas

**Versión:** consolidado de acuerdos\
**Motor:** PostgreSQL 18.1\
**Backend:** Django\
**Base de datos:** `sistra_db`\
**Estado:** acuerdos aprobados; algunos catálogos y valores siguen
pendientes de confirmación de la profesora.

## 1. Alcance y arquitectura

-   SISTRA administra los procesos universitarios de Trabajo Social.
-   Base de datos: PostgreSQL 18.1, base `sistra_db`.
-   Backend: Django. Django gestiona vistas, formularios, rutas,
    autenticación y lógica de negocio; el ORM se comunica con
    PostgreSQL.
-   El equipo trabaja en un mismo repositorio Django. No se contempla
    Angular.
-   La interfaz se construye con plantillas de Django y Bootstrap 5.3;
    no condiciona el diseño de la base de datos.
-   La integración con la plataforma universitaria UP es manual: no hay
    API ni integración automática confirmada.

## 2. Organización del proyecto

Estructura del repositorio:

``` text
SISTRA/
├── manage.py
├── pyproject.toml          # Dependencias (uv)
├── uv.lock
├── config/                 # settings.py, urls.py, asgi.py, wsgi.py
├── apps/                   # Una app de Django por requisito o grupo de requisitos
│   └── usuarios/           # usuario, rol, permiso y rol_permiso
│       ├── models.py
│       └── migrations/     # Estructura de las tablas (se versiona)
├── documentos/             # Archivos subidos por los usuarios (contenido no versionado)
├── static/
├── templates/
└── docs/
    └── database/           # Esta documentación
```

Documentación:

-   `docs/database/01_diccionario_de_datos.md`
-   `docs/database/02_reglas_de_negocio_y_restricciones.md`

**Las tablas se crean únicamente con las migraciones de Django.** Cada
tabla se define como modelo en el `models.py` de su app, se genera su
migración con `makemigrations` y se crea con `migrate`. No se escriben
ni se ejecutan scripts SQL para crear o modificar tablas: si una tabla
se crea por fuera de Django, `migrate` falla porque la tabla ya existe.

La base `sistra_db` ya existe en el servidor y está vacía, sin tablas.
Así debe quedar hasta que se ejecute `migrate`. No se debe borrar ni
recrear el contenedor o volumen existente.

Los respaldos de la base no se guardan en el repositorio, porque
contienen datos personales (cédulas y correos).

## 3. Usuarios, roles y acceso

1.  No existe autorregistro de estudiantes.
2.  El Director registra estudiantes individualmente o mediante CSV.
3.  El sistema genera usuario y contraseña temporal y envía las
    credenciales al correo institucional. El nombre de usuario es la
    parte del correo institucional antes de la @.
4.  Todo usuario que recibe contraseña temporal debe cambiarla en su
    primer ingreso antes de acceder al resto del sistema.
5.  La recuperación de contraseña también genera una contraseña temporal
    y exige cambio al ingresar.
6.  Roles iniciales: Estudiante, Director y Administrador (el rol que el
    BRD llama ADMO).
7.  El Administrador puede crear roles y asignar permisos.
8.  Un Director está asignado a una carrera; cada carrera tiene un solo
    Director activo a la vez.
9.  Correo electrónico se usa únicamente para credenciales y
    recuperación temporal. Las demás notificaciones son dentro de
    SISTRA.
10. Las contraseñas nunca se almacenan en texto plano. Se usa el sistema
    de autenticación de Django con su algoritmo por defecto (PBKDF2); la
    columna `contrasena_hash` guarda solo el hash.
11. Se inicia sesión con el correo institucional y la contraseña. El
    correo se guarda siempre en minúsculas, para que un mismo buzón no
    pueda registrarse dos veces con distintas mayúsculas. El login no
    distingue mayúsculas.
12. La tabla `usuario` es el modelo de usuario de Django
    (`AUTH_USER_MODEL = 'usuarios.Usuario'`); no existe una tabla de
    autenticación paralela. Todo modelo que referencie a `usuario` lo
    hace mediante `settings.AUTH_USER_MODEL`.
13. El primer Administrador se crea en el servidor con
    `python manage.py createsuperuser`.

## 4. Estudiante y carrera

1.  Un estudiante puede estar inscrito en varias carreras.
2.  Cada relación estudiante-carrera tiene su propio proceso de Trabajo
    Social, que se crea cuando el Director registra al estudiante en esa
    carrera (SISTRA-10).
3.  Un estudiante solo puede tener un proceso de Trabajo Social por
    carrera.
4.  La relación estudiante-carrera se conserva como historial aunque el
    estudiante deje o termine esa carrera.
5.  No se eliminan los trámites históricos de esa relación.
6.  La relación puede marcarse Inactiva o Finalizada, registrando fecha
    de finalización.

## 5. Director y asignación por carrera

1.  Cada carrera tiene un solo Director activo.
2.  Cuando cambia el Director, se cierra la asignación anterior y se
    registra una nueva.
3.  El Director nuevo asume la gestión de trámites pendientes e
    históricos de la carrera.
4.  Si un Director anterior regresa, se registra una nueva asignación
    para conservar los intervalos históricos.
5.  El Director actual puede revisar y corregir decisiones anteriores de
    esa carrera.
6.  El historial conserva el usuario/Director que realmente ejecutó cada
    acción; no se reemplaza por el Director actual.
7.  En `cargue_up`, el Director responsable puede quedar NULL hasta que
    se realice la verificación.

## 6. Propuestas

1.  La propuesta se diligencia en SISTRA mediante formulario o mediante
    plantilla Word descargada, completada y cargada.
2.  El sistema puede leer campos fijos de la plantilla; no se contempla
    IA para extraerlos.
3.  El formulario permanece como borrador mientras falten campos
    obligatorios.
4.  El porcentaje de avance se calcula automáticamente en Django con
    base en los campos obligatorios completos; no se almacena en
    PostgreSQL.
5.  El estudiante solo puede enviar cuando el formulario alcanza el 100
    % de campos obligatorios.
6.  Al enviar, el estado pasa a `En revisión`, el formulario queda
    bloqueado y se notifica al Director dentro de SISTRA.
7.  El periodo académico asociado es el periodo de creación. Si se
    reenvía en otro periodo, no se cambia el periodo original; el
    historial registra las fechas de los reenvíos.
8.  La propuesta conserva la versión exacta de la plantilla Word usada.
    Si se diligenció directamente en formulario, `id_version_plantilla`
    puede ser NULL.
9.  Solo puede existir una propuesta activa por proceso. Las propuestas
    históricas se conservan.
10. Una propuesta rechazada definitivamente permite que el estudiante
    cree otra para el mismo proceso, siempre que no exista otra activa.
11. El rechazo definitivo se archiva automáticamente después de un plazo
    configurable por el Administrador. No se elimina físicamente.
12. Si el rechazo se corrige antes del archivado, se cancela el
    archivado y la propuesta vuelve al flujo activo.
13. Una propuesta archivada no cuenta como activa y no se modifica ni
    reactiva por el estudiante.

## 7. Informes

1.  El informe sigue un flujo similar al de la propuesta, pero se
    diligencia en formulario; no se contempla plantilla Word para
    informe.
2.  Solo se crea después de que la propuesta haya sido aprobada en UP.
3.  Solo puede existir un informe activo por propuesta.
4.  Los informes históricos se conservan.
5.  Si un informe es rechazado definitivamente, el estudiante puede
    crear uno nuevo para la misma propuesta.
6.  El informe rechazado se archiva después de un plazo configurable por
    el Administrador; no se elimina físicamente.
7.  Si se corrige el rechazo antes del archivado, se cancela el
    archivado.
8.  `version_entrega` comienza en 1 para un informe nuevo y aumenta
    cuando se corrige y reenvía el mismo informe.
9.  Se conserva el periodo académico de creación aunque se reenvíe en
    otro periodo.

## 8. Estados de propuesta e informe

Estados acordados para ambos:

-   `Borrador`
-   `En revisión`
-   `Requiere modificación`
-   `Rechazado`
-   `Aprobado`
-   `Subido en UP`
-   `Aprobado en UP`

`Archivada` no es un estado académico. Se representa con un indicador
independiente (`archivada`) y su fecha.

Flujo general: 1. Borrador → En revisión, cuando el estudiante envía un
formulario completo. 2. En revisión → Aprobado, Requiere modificación o
Rechazado, según decisión del Director. 3. Requiere modificación → En
revisión, cuando el estudiante corrige y reenvía. 4. Aprobado → Subido
en UP, cuando el estudiante declara en SISTRA que realizó manualmente la
carga externa. 5. Subido en UP → Aprobado en UP o vuelve a Aprobado si
el Director rechaza la carga en UP. 6. Si UP rechaza, el estudiante debe
corregir lo necesario, volver a cargar en UP y pulsar de nuevo el botón
de declaración.

El flujo concreto de corrección y reenvío se debe validar en Django para
impedir saltos de estado no autorizados.

## 9. Revisión y corrección de decisiones

1.  El Director puede revisar trámites individualmente o en acciones
    masivas.
2.  Una acción masiva produce un registro de historial por cada
    propuesta o informe afectado.
3.  Para `Requiere modificación`, el Director escribe una observación
    general; se desbloquea el formulario completo.
4.  Si el Director rechazó una propuesta o informe por error, el
    Director actual de la carrera puede corregir la decisión:
    -   a `Aprobado`, si el trámite cumplía los requisitos;
    -   a `Requiere modificación`, si el estudiante todavía debe
        corregirlo.
5.  Toda corrección exige motivo obligatorio.
6.  Se conserva la decisión anterior y la nueva en el historial.
7.  El estudiante recibe notificación de la corrección.
8.  La corrección no debe borrar ni sobrescribir el registro histórico
    original.

## 10. Carga manual y verificación en UP

1.  UP es externa; SISTRA no se integra técnicamente con ella.
2.  Después de que la propuesta o informe esté aprobado en SISTRA, el
    estudiante realiza manualmente la carga en UP.
3.  Luego vuelve a SISTRA y pulsa `Subido en UP`.
4.  El Director consulta UP por su cuenta y registra en SISTRA
    `Aprobado en UP` o `Rechazado en UP`.
5.  Cada intento real de carga del estudiante genera un registro
    independiente en `cargue_up`.
6.  La verificación conserva el Director que la realizó, fecha,
    resultado y observación.
7.  Si el Director rechaza en UP, la observación es obligatoria.
8.  El estudiante debe volver a cargar el documento en UP después de un
    rechazo y registrar un nuevo intento en SISTRA.
9.  El Director puede corregir una decisión equivocada de UP en ambos
    sentidos:
    -   `Rechazado en UP` → `Aprobado en UP`.
    -   `Aprobado en UP` → `Rechazado en UP`.
10. La corrección exige motivo obligatorio; si el resultado corregido es
    rechazo, también observación obligatoria para el estudiante.
11. La corrección conserva el resultado anterior en
    `historial_cargue_up`, identifica al Director que corrigió, registra
    fecha y motivo y notifica al estudiante.
12. Si no hubo una nueva carga del estudiante, corregir la decisión no
    crea un nuevo intento.
13. El Director actual de la carrera puede corregir verificaciones
    hechas por Directores anteriores.

## 11. Etapas del proceso y cronograma

Se mantienen tres conceptos distintos:

-   `actividad`: catálogo de etapas generales del proceso de Trabajo
    Social.
-   `proceso_actividad`: avance de cada proceso en las etapas del
    catálogo.
-   `actividad_cronograma`: actividades planificadas dentro de cada
    propuesta, con descripción, fechas, orden y responsable.

La cantidad y nombres de las etapas generales están pendientes de
confirmación de la profesora. No se fija por ahora un número, por
ejemplo seis. Una vez definidas, se aplicarán las mismas etapas a todos
los procesos. La primera etapa inicia En curso y las restantes
Pendiente. Las modificaciones de propuesta no hacen retroceder
automáticamente al estudiante de etapa.

## 12. Historial, notificaciones y auditoría

1.  Cada cambio de estado de propuesta o informe queda en
    `historial_estado`.
2.  El historial registra estado anterior y nuevo, usuario actor,
    fecha/hora, observación, tipo de acción y, cuando aplique, tipo de
    rechazo o motivo de reactivación.
3.  Los historiales de carga/verificación UP y corrección se registran
    en `historial_cargue_up`.
4.  Las notificaciones y recordatorios son internos a SISTRA.
5.  No se envían correos de seguimiento ni SMS; el correo se reserva
    para credenciales y recuperación temporal.
6.  `fecha_lectura` NULL indica notificación no leída.
7.  La auditoría registra acciones relevantes, éxitos y fallos,
    incluyendo intentos de acceso cuando corresponda. No almacena
    contraseñas.

## 13. Semáforo y recordatorios

1.  El semáforo cuenta días calendario mientras el trámite permanece
    `En revisión`.
2.  Umbrales acordados:
    -   0 a 7 días: verde.
    -   8 a 14 días: amarillo.
    -   15 días o más: rojo.
3.  Los umbrales serán parametrizables por el Administrador.
4.  Se notifica al Director cuando un trámite entra en amarillo o rojo.
5.  Mientras una propuesta o informe esté aprobado pero el estudiante no
    haya declarado `Subido en UP`, se envía recordatorio semanal dentro
    de SISTRA.
6.  El cálculo del tiempo y la programación de recordatorios se
    implementan en el backend Django/tarea programada. Los eventos
    relevantes pueden registrarse para trazabilidad.

## 14. Parámetros y administración

El Administrador podrá configurar, entre otros: - Umbrales del semáforo. -
Frecuencia de recordatorios. - URL de la plataforma UP. - Formatos y
tamaños máximos permitidos. - Límites para archivos CSV. - Plazo para
archivar propuestas rechazadas. - Plazo para archivar informes
rechazados. - Plantillas y sus versiones.

El archivado automático se ejecuta desde el backend mediante tarea
programada/gestión de Django; PostgreSQL conserva los datos y fechas.

## 15. Reportes y paneles

-   El Administrador puede consultar información global de todas las
    carreras.
-   El Director consulta la información de su carrera.
-   Se contemplan reportes PDF por rango de fechas, incluidos resultados
    aprobados y rechazados.
-   Cada rol tiene su panel correspondiente.
-   El alcance exacto de indicadores y filtros se puede precisar durante
    la implementación.

## 16. Restricciones de integridad aprobadas

Se aprobaron estas reglas generales:

1.  Cédula, correo institucional y nombre de usuario únicos.
2.  Código de carrera único.
3.  Un estudiante no puede tener dos inscripciones a la misma carrera
    (`UNIQUE (id_estudiante, id_carrera)`).
4.  Una inscripción estudiante-carrera solo tiene un proceso de Trabajo
    Social (`UNIQUE (id_estudiante_carrera)`).
5.  Una propuesta activa por proceso.
6.  Un informe activo por propuesta.
7.  Un solo Director activo por carrera, usando índice único parcial.
8.  Una sola versión vigente por plantilla, usando índice único parcial.
9.  Una actividad del catálogo no se repite dentro del mismo proceso
    (`UNIQUE (id_proceso, id_actividad)`).
10. Un orden de actividad de cronograma no se repite dentro de la misma
    propuesta.
11. Las fechas finales no pueden ser anteriores a las iniciales.
12. `version_entrega` debe ser mayor que cero.
13. `cargue_up` debe relacionarse con exactamente una propuesta o un
    informe.
14. `historial_estado` debe relacionarse con exactamente una propuesta o
    un informe.
15. Una notificación puede ser general o asociarse a una propuesta o a
    un informe; no debe asociarse simultáneamente a ambos.
16. Fechas de verificación coherentes con la declaración de carga.
17. Rechazo en UP exige observación.
18. Correcciones de decisiones exigen motivo.
19. La fecha de finalización de asignación de Director no puede ser
    anterior a su fecha de inicio.
20. Los porcentajes de avance no se almacenan: Django los calcula a
    partir de campos obligatorios.

Para propuestas/informes, un registro activo se define como no archivado
y con estado distinto de `Rechazado`. La implementación debe contemplar
el archivado y la corrección de rechazos para mantener coherencia con
los índices únicos parciales.

## 17. Eliminación y conservación histórica

Se aprobó proteger los registros académicos, administrativos e
históricos contra eliminación física.

-   Usar `ON DELETE RESTRICT` en relaciones que protegen historial.
-   No eliminar estudiantes con procesos.
-   No eliminar carreras con inscripciones o trámites históricos.
-   No eliminar Directores con acciones registradas.
-   No eliminar propuestas, informes, historiales ni intentos de carga
    que tengan valor histórico.
-   No eliminar periodos académicos utilizados.
-   Desactivar usuarios y catálogos cuando corresponda.
-   Archivar propuestas e informes rechazados en lugar de borrarlos.

La política de retención es conservar los datos académicos y
administrativos relevantes.

## 18. Índices aprobados

Se aprobaron índices para apoyar las consultas frecuentes, evitando
duplicar los índices que ya crea PostgreSQL para PK y UNIQUE:

-   `usuario(correo_institucional)` para inicio de sesión: ya queda
    cubierto por el índice que crea su restricción UNIQUE, no se crea
    otro.
-   `estudiante_carrera(id_estudiante)` y
    `estudiante_carrera(id_carrera)`.
-   `director_carrera(id_carrera, activo)` y el índice único parcial de
    Director activo por carrera.
-   `propuesta(id_proceso, estado)` y el índice único parcial de
    propuesta activa por proceso.
-   `informe(id_propuesta, estado)` y el índice único parcial de informe
    activo por propuesta.
-   `historial_estado(id_propuesta, fecha_hora)` y
    `historial_estado(id_informe, fecha_hora)`.
-   `cargue_up(id_propuesta)` y `cargue_up(id_informe)`.
-   `notificacion(id_usuario, fecha_lectura)`.
-   `auditoria(fecha_hora)` y `auditoria(id_usuario)`.
-   Índice único parcial de versión vigente por plantilla.

Los índices definitivos se ajustarán a las consultas reales y a los
índices creados automáticamente por restricciones UNIQUE.

## 19. Pendientes de confirmación

Estos puntos no deben inventarse ni darse por aprobados como valores
definitivos:

1.  Cantidad, nombres, descripciones y orden de las etapas del proceso
    (`actividad`).
2.  Catálogo de tipos de rechazo (`tipo_rechazo`).
3.  Plazos concretos de archivado de propuestas e informes rechazados.
    El Administrador podrá parametrizarlos; falta definir valores
    iniciales.
4.  Confirmación final de algunos campos del formulario y de los
    documentos adicionales posteriores al cierre (por ejemplo, aval de
    horas, certificado y evidencias), incluidos requisitos y momento de
    entrega.
5.  Confirmación de si se requieren campos separados para primer envío y
    último reenvío, en lugar de un único `fecha_envio`.
6.  Confirmación institucional del algoritmo/formato de códigos de
    propuestas e informes.
7.  Confirmar el vocabulario de `historial_estado.tipo_accion` y de los
    demás campos de texto libre (`plantilla.tipo`, `plantilla.estado`,
    `notificacion.tipo`, `auditoria.resultado`). Los estados de
    `proceso_trabajo_social` y `proceso_actividad` quedaron como
    Pendiente/En curso/Finalizada; si cambian, se ajustan con una migración.
8.  Política de eliminación de usuarios sin trámites. Por ahora todas las
    relaciones que apuntan a `usuario` usan `ON DELETE RESTRICT`.

## 20. Criterio de implementación

-   Implementar primero los modelos y restricciones base, respetando
    dependencias.
-   Crear las tablas solo con `makemigrations` y `migrate` sobre la base
    existente `sistra_db`, que actualmente no tiene tablas; no ejecutar
    scripts SQL de creación ni recrear o borrar el contenedor o volumen.
-   Las restricciones `CHECK` y los índices únicos parciales se declaran
    en los modelos (`Meta.constraints`), para que también los cree la
    migración.
-   Las transiciones y operaciones que afectan varias tablas deben
    ejecutarse dentro de transacciones atómicas de Django.
-   Las reglas de acceso deben comprobar el Director activo de la
    carrera y el rol/permisos del usuario.
-   Cada corrección debe preservar la acción original y dejar
    trazabilidad.
-   Probar restricciones, índices parciales, flujos de estado, archivado
    y concurrencia antes de desplegar al servidor.
