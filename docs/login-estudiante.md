# Login de estudiantes (SISTRA-13)

## Alcance de esta entrega

Se implementan el formulario de inicio de sesión para estudiantes, su procesamiento, la comprobación del perfil de estudiante y del estado activo, el cierre de sesión y una página privada temporal para validar la sesión. No se implementan registro público, recuperación de contraseña ni pantallas administrativas.

## Adaptación de la pantalla anterior

> "usa la pantalla actual que se tiene para el logeo. adactandola a las tecnologias requeridas para el froten en el readme"

La estructura visual del acceso de Grado se recreó con una composición dividida, panel azul institucional, acentos vinotinto, jerarquía tipográfica y mensajes de acceso. El formulario usa plantillas Django y componentes Bootstrap 5.3; el CSS propio se limita a la composición y a los colores de marca. En esta etapa aparece únicamente el ingreso de estudiante; no se muestran opciones de registro ni de recuperación.

## Rutas

- `GET/POST /usuarios/login/`: muestra y procesa el formulario institucional.
- `GET /usuarios/inicio/`: página privada temporal para comprobar una sesión de estudiante. SISTRA-14 deberá sustituirla por el dashboard académico.
- `POST /usuarios/logout/`: cierra la sesión; la petición está protegida por CSRF.

## Reglas de acceso

- El correo se recorta, se normaliza a minúsculas y debe terminar exactamente en `@unipamplona.edu.co`. Un dominio externo se rechaza antes de consultar la base de datos.
- La cuenta debe existir en `usuario`, tener estado activo, pertenecer al rol activo `Estudiante` y contar con su relación `estudiante`.
- Para cuentas inexistentes, sin perfil, inactivas, con rol inválido o con contraseña incorrecta se muestra el mismo texto: **«Correo o contraseña incorrectos.»**
- La contraseña se verifica con `check_password`; al crear usuarios se usa `create_user`, que almacena el hash con sal de Django.
- Una contraseña incorrecta incrementa `intentos_fallidos`; una sesión válida reinicia ese contador. Un `bloqueado_hasta` futuro ya registrado impide el acceso. No se introduce un umbral nuevo de bloqueo porque las reglas institucionales no lo especifican.
- Django registra `last_login` al crear la sesión. La duración y renovación se mantienen según la configuración existente en `settings.py`.
- Los accesos válidos y fallidos se registran en `auditoria`; no se guarda la contraseña ni el contenido sensible del formulario.

## Cuentas de prueba locales

El comando `uv run python manage.py crear_estudiantes_prueba` prepara, de forma idempotente, estas cuentas y sus perfiles:

| Nombre | Correo | Usuario | Cédula ficticia |
| --- | --- | --- | --- |
| Estudiante Prueba Uno | `estudiante1@unipamplona.edu.co` | `estudiante1` | `1000000001` |
| Estudiante Prueba Dos | `estudiante2@unipamplona.edu.co` | `estudiante2` | `1000000002` |

Al crear cuentas nuevas, el comando pide la contraseña dos veces mediante una entrada que no la muestra. Usa la contraseña de prueba indicada en la guía de implementación. El comando no cambia contraseñas ni sobrescribe datos de cuentas existentes; solo crea el perfil si todavía falta. Ejecutarlo únicamente en una base de datos local/de desarrollo.

## Comprobaciones

```bash
uv sync
uv run python manage.py check
uv run python manage.py test apps.usuarios
```

Para aplicar migraciones pendientes en una base local configurada:

```bash
uv run python manage.py showmigrations
uv run python manage.py migrate
```
