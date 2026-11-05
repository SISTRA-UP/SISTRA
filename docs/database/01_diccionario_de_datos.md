# SISTRA --- Diccionario de datos

**Versión:** borrador consolidado para revisión\
**Motor:** PostgreSQL 18.6\
**Backend:** Django\
**Base de datos:** `sistra_db`\
**Estado:** diseño revisado; pendiente de implementación y validación
técnica.

> Este documento consolida el diccionario de datos acordado. Los nombres
> y tipos son la propuesta de diseño para PostgreSQL. Los detalles que
> dependen de confirmación de la profesora se identifican como
> pendientes. Las tablas no se crean con scripts SQL: cada tabla se
> define como modelo de Django y se crea con `makemigrations` y
> `migrate`, respetando los nombres, tipos y restricciones de este
> documento.

## Convenciones generales

-   Las claves primarias usan `BIGINT GENERATED ALWAYS AS IDENTITY`,
    salvo las claves primarias compuestas indicadas.
-   Las fechas de creación y eventos usan `TIMESTAMP`; las fechas
    académicas sin hora usan `DATE`.
-   Las claves foráneas que protegen información histórica deben usar
    `ON DELETE RESTRICT`.
-   Los campos marcados como NULL son opcionales.
-   Los estados se guardan como texto controlado mediante restricciones
    `CHECK` o catálogos, según la implementación definitiva.
-   Los nombres de tablas y columnas se escriben en `snake_case`.

## 1. Estructura institucional y catálogos

### 1.1 `facultad`

  Campo           Tipo PostgreSQL   Restricción / descripción
  --------------- ----------------- ---------------------------------------------
  `id_facultad`   BIGINT IDENTITY   PK
  `nombre`        VARCHAR(120)      NOT NULL, UNIQUE
  `descripcion`   TEXT              NULL
  `estado`        VARCHAR(15)       NOT NULL, DEFAULT 'Activo'; Activo/Inactivo

### 1.2 `carrera`

  Campo           Tipo PostgreSQL   Restricción / descripción
  --------------- ----------------- ----------------------------
  `id_carrera`    BIGINT IDENTITY   PK
  `id_facultad`   BIGINT            FK a `facultad`, NOT NULL
  `nombre`        VARCHAR(120)      NOT NULL
  `codigo`        VARCHAR(20)       NOT NULL, UNIQUE
  `estado`        VARCHAR(15)       NOT NULL, DEFAULT 'Activo'

Se recomienda evitar duplicar el nombre de una carrera dentro de la
misma facultad mediante `UNIQUE (id_facultad, nombre)`.

### 1.3 `periodo_academico`

  Campo                      Tipo PostgreSQL   Restricción / descripción
  -------------------------- ----------------- --------------------------------------
  `id_periodo_academico`     BIGINT IDENTITY   PK
  `nombre`                   VARCHAR(20)       NOT NULL, UNIQUE
  `fecha_inicio`             DATE              NOT NULL
  `fecha_fin`                DATE              NOT NULL
  `fecha_cierre_propuesta`   DATE              NOT NULL
  `fecha_cierre_informe`     DATE              NOT NULL
  `estado`                   VARCHAR(15)       NOT NULL; Vigente/Cerrado
  `fecha_creacion`           TIMESTAMP         NOT NULL, DEFAULT CURRENT_TIMESTAMP

Orden de las fechas: `fecha_fin` no anterior a `fecha_inicio`;
`fecha_cierre_propuesta` dentro del periodo, y `fecha_cierre_informe`
posterior a `fecha_cierre_propuesta` (BRD SISTRA-11). Solo puede haber un
periodo Vigente a la vez (BRD RN-11-02), mediante un índice único parcial.

### 1.4 `actividad`

Catálogo de etapas generales del proceso de Trabajo Social. La cantidad,
nombres y orden definitivo están pendientes de confirmación de la
profesora.

  Campo            Tipo PostgreSQL   Restricción / descripción
  ---------------- ----------------- ---------------------------
  `id_actividad`   BIGINT IDENTITY   PK
  `nombre`         VARCHAR(150)      NOT NULL
  `descripcion`    TEXT              NULL
  `orden`          SMALLINT          NOT NULL, UNIQUE
  `obligatoria`    BOOLEAN           NOT NULL
  `estado`         VARCHAR(15)       NOT NULL; Activo/Inactivo

### 1.5 `tipo_rechazo`

Catálogo compartido para clasificar rechazos de propuestas e informes.
Los valores concretos están pendientes de confirmación.

  Campo               Tipo PostgreSQL   Restricción / descripción
  ------------------- ----------------- ---------------------------
  `id_tipo_rechazo`   BIGINT IDENTITY   PK
  `nombre`            VARCHAR(100)      NOT NULL, UNIQUE
  `descripcion`       TEXT              NULL
  `estado`            VARCHAR(15)       NOT NULL; Activo/Inactivo

## 2. Usuarios, roles y permisos

### 2.1 `usuario`

  ------------------------------------------------------------------------------
  Campo                          Tipo PostgreSQL         Restricción /
                                                         descripción
  ------------------------------ ----------------------- -----------------------
  `id_usuario`                   BIGINT IDENTITY         PK

  `id_rol`                       BIGINT                  FK a `rol`, NOT NULL

  `nombre`                       VARCHAR(120)            NOT NULL

  `cedula`                       VARCHAR(15)             NOT NULL, UNIQUE

  `correo_institucional`         VARCHAR(254)            NOT NULL, UNIQUE

  `nombre_usuario`               VARCHAR(80)             NOT NULL, UNIQUE

  `contrasena_hash`              VARCHAR(255)            NOT NULL; almacenar
                                                         hash, nunca contraseña
                                                         en texto

  `requiere_cambio_contrasena`   BOOLEAN                 NOT NULL, DEFAULT TRUE

  `estado`                       VARCHAR(10)             NOT NULL, DEFAULT
                                                         'Activo'

  `intentos_fallidos`            INTEGER                 NOT NULL, DEFAULT 0

  `bloqueado_hasta`              TIMESTAMP               NULL

  `ultimo_ingreso`               TIMESTAMP               NULL

  `fecha_creacion`               TIMESTAMP               NOT NULL, DEFAULT
                                                         CURRENT_TIMESTAMP
  ------------------------------------------------------------------------------

**Nota Django:** esta tabla es el modelo de usuario de Django
(`AUTH_USER_MODEL = 'usuarios.Usuario'`, en `apps/usuarios`). Ya está
implementada.

-   Se inicia sesión con `correo_institucional` y contraseña. El correo
    se guarda en minúsculas y el login no distingue mayúsculas.
-   `nombre_usuario` es la parte del correo institucional antes de la @.
-   La contraseña usa el algoritmo por defecto de Django (PBKDF2). No se
    implementa un almacenamiento de contraseñas propio.
-   Las tablas que referencian a `usuario` usan
    `settings.AUTH_USER_MODEL` en la `ForeignKey` o `OneToOneField`.

### 2.2 `rol`

  Campo           Tipo PostgreSQL   Restricción / descripción
  --------------- ----------------- ----------------------------
  `id_rol`        BIGINT IDENTITY   PK
  `nombre`        VARCHAR(30)       NOT NULL, UNIQUE
  `descripcion`   TEXT              NULL
  `estado`        VARCHAR(10)       NOT NULL, DEFAULT 'Activo'

Roles iniciales previstos: Estudiante, Director y Administrador (el rol
que el BRD llama ADMO). El Administrador podrá crear roles adicionales.

### 2.3 `permiso`

  Campo           Tipo PostgreSQL   Restricción / descripción
  --------------- ----------------- ----------------------------
  `id_permiso`    BIGINT IDENTITY   PK
  `nombre`        VARCHAR(80)       NOT NULL, UNIQUE
  `descripcion`   TEXT              NULL
  `estado`        VARCHAR(10)       NOT NULL, DEFAULT 'Activo'

### 2.4 `rol_permiso`

  Campo          Tipo PostgreSQL   Restricción / descripción
  -------------- ----------------- -----------------------------------------
  `id_rol`       BIGINT            PK compuesta y FK a `rol`, NOT NULL
  `id_permiso`   BIGINT            PK compuesta y FK a `permiso`, NOT NULL

Clave primaria compuesta: (`id_rol`, `id_permiso`).

## 3. Personas e inscripciones

### 3.1 `estudiante`

  Campo             Tipo PostgreSQL   Restricción / descripción
  ----------------- ----------------- ----------------------------------
  `id_estudiante`   BIGINT IDENTITY   PK
  `id_usuario`      BIGINT            FK a `usuario`, NOT NULL, UNIQUE

### 3.2 `director`

  Campo           Tipo PostgreSQL   Restricción / descripción
  --------------- ----------------- ----------------------------------
  `id_director`   BIGINT IDENTITY   PK
  `id_usuario`    BIGINT            FK a `usuario`, NOT NULL, UNIQUE

### 3.3 `estudiante_carrera`

  Campo                     Tipo PostgreSQL   Restricción / descripción
  ------------------------- ----------------- --------------------------------------
  `id_estudiante_carrera`   BIGINT IDENTITY   PK
  `id_estudiante`           BIGINT            FK a `estudiante`, NOT NULL
  `id_carrera`              BIGINT            FK a `carrera`, NOT NULL
  `fecha_registro`          DATE              NOT NULL, DEFAULT CURRENT_DATE
  `estado`                  VARCHAR(15)       NOT NULL; Activo/Inactivo/Finalizado
  `fecha_finalizacion`      DATE              NULL

Restricción UNIQUE (`id_estudiante`, `id_carrera`). La relación se
conserva aunque el estudiante deje o termine la carrera.

### 3.4 `director_carrera`

  Campo                   Tipo PostgreSQL   Restricción / descripción
  ----------------------- ----------------- ---------------------------
  `id_director_carrera`   BIGINT IDENTITY   PK
  `id_director`           BIGINT            FK a `director`, NOT NULL
  `id_carrera`            BIGINT            FK a `carrera`, NOT NULL
  `fecha_inicio`          DATE              NOT NULL
  `fecha_fin`             DATE              NULL
  `activo`                BOOLEAN           NOT NULL, DEFAULT TRUE

Se permitirá un solo Director activo por carrera mediante índice único
parcial. Cada periodo de asignación se conserva como registro histórico.

## 4. Proceso de Trabajo Social

### 4.1 `proceso_trabajo_social`

  -------------------------------------------------------------------------
  Campo                     Tipo PostgreSQL         Restricción /
                                                    descripción
  ------------------------- ----------------------- -----------------------
  `id_proceso`              BIGINT IDENTITY         PK

  `id_estudiante_carrera`   BIGINT                  FK a
                                                    `estudiante_carrera`,
                                                    NOT NULL, UNIQUE

  `fecha_inicio`            TIMESTAMP               NOT NULL

  `fecha_finalizacion`      TIMESTAMP               NULL

  `estado`                  VARCHAR(20)             NOT NULL;
                                                    Pendiente/En
                                                    curso/Finalizada
  -------------------------------------------------------------------------

Cada inscripción estudiante-carrera tiene un único proceso de Trabajo
Social. El proceso se crea cuando el Director registra al estudiante en
una carrera (SISTRA-10).

### 4.2 `proceso_actividad`

Registra el avance de un proceso en las etapas del catálogo `actividad`.

  ----------------------------------------------------------------------------
  Campo                    Tipo PostgreSQL         Restricción / descripción
  ------------------------ ----------------------- ---------------------------
  `id_proceso_actividad`   BIGINT IDENTITY         PK

  `id_proceso`             BIGINT                  FK a
                                                   `proceso_trabajo_social`,
                                                   NOT NULL

  `id_actividad`           BIGINT                  FK a `actividad`, NOT NULL

  `estado`                 VARCHAR(20)             NOT NULL;
                                                   Pendiente/En
                                                   curso/Finalizada

  `fecha_inicio`           TIMESTAMP               NULL

  `fecha_finalizacion`     TIMESTAMP               NULL

  `observacion`            TEXT                    NULL
  ----------------------------------------------------------------------------

UNIQUE (`id_proceso`, `id_actividad`). La primera etapa inicia En curso
y las siguientes Pendiente, una vez que la profesora confirme el
catálogo.

## 5. Propuestas, informes y cronogramas

### 5.1 `propuesta`

  --------------------------------------------------------------------------------
  Campo                        Tipo PostgreSQL         Restricción / descripción
  ---------------------------- ----------------------- ---------------------------
  `id_propuesta`               BIGINT IDENTITY         PK

  `id_proceso`                 BIGINT                  FK a
                                                       `proceso_trabajo_social`,
                                                       NOT NULL

  `id_periodo_academico`       BIGINT                  FK a `periodo_academico`,
                                                       NOT NULL

  `id_version_plantilla`       BIGINT                  FK a `version_plantilla`,
                                                       NULL

  `codigo`                     VARCHAR(30)             NOT NULL, UNIQUE

  `titulo`                     VARCHAR(200)            NOT NULL

  `resena_historica`           TEXT                    NOT NULL

  `identificacion_necesidad`   TEXT                    NOT NULL

  `justificacion`              TEXT                    NOT NULL

  `objetivos`                  TEXT                    NOT NULL

  `referente_teorico`          TEXT                    NOT NULL

  `impacto_social`             TEXT                    NOT NULL

  `identificacion_poblacion`   TEXT                    NOT NULL

  `propuesta_social`           TEXT                    NOT NULL

  `entidad`                    VARCHAR(200)            NOT NULL

  `sector_entidad`             VARCHAR(20)             NULL en Borrador;
                                                       Público/Privado

  `poblacion_beneficiada`      TEXT                    NOT NULL

  `zona`                       TEXT                    NOT NULL

  `area`                       TEXT                    NOT NULL

  `sector`                     TEXT                    NOT NULL

  `unidad`                     TEXT                    NOT NULL

  `fecha_inicio`               DATE                    NULL en Borrador

  `fecha_fin`                  DATE                    NULL en Borrador

  `estado`                     VARCHAR(30)             NOT NULL

  `fecha_creacion`             TIMESTAMP               NOT NULL

  `fecha_actualizacion`        TIMESTAMP               NOT NULL

  `fecha_envio`                TIMESTAMP               NULL; se recomienda
                                                       precisar primer/último
                                                       envío

  `archivada`                  BOOLEAN                 NOT NULL, DEFAULT FALSE

  `fecha_archivado`            TIMESTAMP               NULL
  --------------------------------------------------------------------------------

Estados acordados: Borrador, En revisión, Requiere modificación,
Rechazado, Aprobado, Subido en UP y Aprobado en UP. Archivada no es un
estado: se representa con `archivada` y `fecha_archivado`.

La propuesta se guarda como Borrador aunque falten campos obligatorios
(BRD SISTRA-01). Por eso `fecha_inicio`, `fecha_fin` y `sector_entidad`
admiten NULL, y los campos de texto se guardan vacíos mientras no se
diligencien. Django exige que todos estén completos antes de enviar
(avance al 100 %).

Se permitirá una sola propuesta activa por proceso mediante índice único
parcial. El periodo académico registra el periodo de creación y no
cambia al reenviar. La plantilla usada se conserva cuando la propuesta
proviene de Word; puede ser NULL si se diligenció directamente en el
formulario.

### 5.2 `informe`

  ------------------------------------------------------------------------
  Campo                    Tipo PostgreSQL         Restricción /
                                                   descripción
  ------------------------ ----------------------- -----------------------
  `id_informe`             BIGINT IDENTITY         PK

  `id_propuesta`           BIGINT                  FK a `propuesta`, NOT
                                                   NULL

  `id_periodo_academico`   BIGINT                  FK a
                                                   `periodo_academico`,
                                                   NOT NULL

  `codigo`                 VARCHAR(30)             NOT NULL, UNIQUE

  `resultados`             TEXT                    NOT NULL

  `conclusiones`           TEXT                    NOT NULL

  `recomendaciones`        TEXT                    NOT NULL

  `estado`                 VARCHAR(30)             NOT NULL; mismos
                                                   estados de propuesta

  `version_entrega`        INTEGER                 NOT NULL, DEFAULT 1;
                                                   CHECK \> 0

  `fecha_creacion`         TIMESTAMP               NOT NULL

  `fecha_actualizacion`    TIMESTAMP               NOT NULL

  `fecha_envio`            TIMESTAMP               NULL; se recomienda
                                                   precisar primer/último
                                                   envío

  `archivado`              BOOLEAN                 NOT NULL, DEFAULT FALSE

  `fecha_archivado`        TIMESTAMP               NULL
  ------------------------------------------------------------------------

Se permitirá un solo informe activo por propuesta mediante índice único
parcial. Un nuevo informe comienza en versión 1; una corrección y
reentrega del mismo informe incrementa `version_entrega`. El periodo de
creación se conserva al reenviar.

### 5.3 `actividad_cronograma`

Registra las actividades planificadas dentro de una propuesta; no
equivale a las etapas generales del proceso.

  Campo                       Tipo PostgreSQL   Restricción / descripción
  --------------------------- ----------------- ----------------------------
  `id_actividad_cronograma`   BIGINT IDENTITY   PK
  `id_propuesta`              BIGINT            FK a `propuesta`, NOT NULL
  `nombre`                    VARCHAR(200)      NOT NULL
  `descripcion`               TEXT              NULL
  `fecha_inicio`              DATE              NOT NULL
  `fecha_fin`                 DATE              NOT NULL
  `orden`                     SMALLINT          NOT NULL
  `responsable`               VARCHAR(200)      NULL

UNIQUE (`id_propuesta`, `orden`); validar fecha_fin \>= fecha_inicio.

## 6. Historiales y cargas en UP

### 6.1 `historial_estado`

  Campo                   Tipo PostgreSQL   Restricción / descripción
  ----------------------- ----------------- ---------------------------
  `id_historial`          BIGINT IDENTITY   PK
  `id_propuesta`          BIGINT            FK a `propuesta`, NULL
  `id_informe`            BIGINT            FK a `informe`, NULL
  `id_usuario`            BIGINT            FK a `usuario`, NOT NULL
  `id_tipo_rechazo`       BIGINT            FK a `tipo_rechazo`, NULL
  `estado_anterior`       VARCHAR(30)       NULL
  `estado_nuevo`          VARCHAR(30)       NOT NULL
  `observacion`           TEXT              NULL
  `motivo_reactivacion`   TEXT              NULL
  `tipo_accion`           VARCHAR(30)       NOT NULL
  `fecha_hora`            TIMESTAMP         NOT NULL

CHECK: exactamente uno entre `id_propuesta` e `id_informe` debe tener
valor. Cada cambio genera un registro, incluso en acciones masivas (una
fila por trámite).

### 6.2 `cargue_up`

  Campo                   Tipo PostgreSQL   Restricción / descripción
  ----------------------- ----------------- ---------------------------------------------
  `id_cargue_up`          BIGINT IDENTITY   PK
  `id_propuesta`          BIGINT            FK a `propuesta`, NULL
  `id_informe`            BIGINT            FK a `informe`, NULL
  `id_director`           BIGINT            FK a `director`, NULL hasta la verificación
  `fecha_declaracion`     TIMESTAMP         NOT NULL
  `estado_verificacion`   VARCHAR(25)       NOT NULL
  `fecha_verificacion`    TIMESTAMP         NULL
  `observacion`           TEXT              NULL

CHECK: exactamente uno entre `id_propuesta` e `id_informe` debe tener
valor. Cada intento de carga del estudiante crea una fila nueva. Estados
de verificación: Pendiente, Aprobado en UP, Rechazado en UP. El rechazo
requiere observación obligatoria. El Director y la fecha se registran al
verificar.

### 6.3 `historial_cargue_up`

  Campo                   Tipo PostgreSQL   Restricción / descripción
  ----------------------- ----------------- ----------------------------
  `id_historial_cargue`   BIGINT IDENTITY   PK
  `id_cargue_up`          BIGINT            FK a `cargue_up`, NOT NULL
  `id_director`           BIGINT            FK a `director`, NOT NULL
  `estado_anterior`       VARCHAR(25)       NULL
  `estado_nuevo`          VARCHAR(25)       NOT NULL
  `observacion`           TEXT              NULL
  `motivo_correccion`     TEXT              NULL
  `fecha_hora`            TIMESTAMP         NOT NULL

Conserva correcciones de decisiones de UP. Se exige motivo; cuando el
resultado corregido sea Rechazado en UP, también observación para el
estudiante. La corrección no crea un nuevo intento si el estudiante no
volvió a cargar el documento.

## 7. Comunicación y auditoría

### 7.1 `notificacion`

  Campo               Tipo PostgreSQL   Restricción / descripción
  ------------------- ----------------- -------------------------------
  `id_notificacion`   BIGINT IDENTITY   PK
  `id_usuario`        BIGINT            FK a `usuario`, NOT NULL
  `id_propuesta`      BIGINT            FK a `propuesta`, NULL
  `id_informe`        BIGINT            FK a `informe`, NULL
  `tipo`              VARCHAR(50)       NOT NULL
  `mensaje`           TEXT              NOT NULL
  `fecha_creacion`    TIMESTAMP         NOT NULL
  `fecha_lectura`     TIMESTAMP         NULL; NULL significa no leída

Se recomienda CHECK para impedir que una notificación se relacione
simultáneamente con propuesta e informe. Puede ser general (ambas FK
NULL).

### 7.2 `auditoria`

  ------------------------------------------------------------------------
  Campo                    Tipo PostgreSQL         Restricción /
                                                   descripción
  ------------------------ ----------------------- -----------------------
  `id_auditoria`           BIGINT IDENTITY         PK

  `id_usuario`             BIGINT                  FK a `usuario`, NULL si
                                                   no se identifica al
                                                   usuario

  `accion`                 VARCHAR(100)            NOT NULL

  `tabla_afectada`         VARCHAR(80)             NOT NULL

  `id_registro_afectado`   BIGINT                  NULL; referencia lógica

  `detalle`                TEXT                    NULL

  `resultado`              VARCHAR(30)             NOT NULL

  `fecha_hora`             TIMESTAMP               NOT NULL
  ------------------------------------------------------------------------

La referencia genérica a la tabla/registro no lleva FK porque puede
apuntar a distintas tablas. Nunca guardar contraseñas ni secretos en
auditoría.

## 8. Configuración y plantillas

### 8.1 `parametro`

  Campo                        Tipo PostgreSQL   Restricción / descripción
  ---------------------------- ----------------- ---------------------------
  `id_parametro`               BIGINT IDENTITY   PK
  `clave`                      VARCHAR(100)      NOT NULL, UNIQUE
  `valor`                      TEXT              NOT NULL
  `descripcion`                TEXT              NULL
  `fecha_actualizacion`        TIMESTAMP         NOT NULL
  `id_usuario_actualizacion`   BIGINT            FK a `usuario`, NOT NULL

Incluye parámetros de semáforo, recordatorios, URL de UP, formatos y
tamaños permitidos, límites de CSV y plazos de archivado, entre otros.
Claves previstas: `dias_archivado_propuesta_rechazada` y
`dias_archivado_informe_rechazado`.

### 8.2 `plantilla`

  Campo            Tipo PostgreSQL   Restricción / descripción
  ---------------- ----------------- ---------------------------
  `id_plantilla`   BIGINT IDENTITY   PK
  `nombre`         VARCHAR(120)      NOT NULL
  `tipo`           VARCHAR(30)       NOT NULL
  `descripcion`    TEXT              NULL
  `estado`         VARCHAR(15)       NOT NULL

Plantillas previstas: Word de propuesta y archivo CSV de registro de
estudiantes. No se prevé plantilla Word para informe.

### 8.3 `version_plantilla`

  Campo                    Tipo PostgreSQL   Restricción / descripción
  ------------------------ ----------------- ----------------------------
  `id_version_plantilla`   BIGINT IDENTITY   PK
  `id_plantilla`           BIGINT            FK a `plantilla`, NOT NULL
  `id_usuario`             BIGINT            FK a `usuario`, NOT NULL
  `numero_version`         INTEGER           NOT NULL
  `nombre_archivo`         VARCHAR(200)      NOT NULL
  `ruta_archivo`           TEXT              NOT NULL
  `fecha_carga`            TIMESTAMP         NOT NULL
  `es_vigente`             BOOLEAN           NOT NULL

UNIQUE (`id_plantilla`, `numero_version`) y un índice único parcial para
permitir una sola versión vigente por plantilla.

## 9. Resumen de tablas

1.  `facultad`
2.  `carrera`
3.  `periodo_academico`
4.  `actividad`
5.  `tipo_rechazo`
6.  `usuario`
7.  `rol`
8.  `permiso`
9.  `rol_permiso`
10. `estudiante`
11. `director`
12. `estudiante_carrera`
13. `director_carrera`
14. `proceso_trabajo_social`
15. `proceso_actividad`
16. `propuesta`
17. `informe`
18. `actividad_cronograma`
19. `historial_estado`
20. `cargue_up`
21. `historial_cargue_up`
22. `notificacion`
23. `auditoria`
24. `parametro`
25. `plantilla`
26. `version_plantilla`

**Total: 26 tablas.**

## 10. Observaciones para la implementación

-   El orden de creación debe respetar las dependencias de claves
    foráneas. Por ejemplo, `rol` debe existir antes de `usuario`;
    `plantilla` y `version_plantilla` deben existir antes de crear la FK
    opcional de `propuesta` (o esa FK se agrega después).
-   Las reglas que involucran varias tablas o flujos de trabajo se
    validarán en Django y se ejecutarán en transacciones atómicas.
-   El cálculo del porcentaje de avance de formularios se hará en
    Django; no se almacenará como columna.
-   `usuario` está integrado con la autenticación de Django
    (`AUTH_USER_MODEL`); no existe una tabla de autenticación paralela.
-   El diccionario es la base de diseño acordada; no sustituye las
    migraciones/modelos definitivos ni la revisión técnica de
    consistencia.
