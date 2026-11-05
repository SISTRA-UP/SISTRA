# SISTRA

Estructura base del proyecto. Es el punto de partida sobre el que cada integrante desarrolla el requisito que le corresponde.

**Con qué se trabaja:**

| | |
| --- | --- |
| Backend | Django 6.1 |
| Base de datos | PostgreSQL |
| **Diseño** | **Bootstrap 5.3** |
| Dependencias | [uv](https://docs.astral.sh/uv/) |

Las pantallas se construyen con plantillas de Django y **Bootstrap 5**. No se escribe CSS a mano salvo lo imprescindible: se usan las clases y los componentes de Bootstrap. Ver la [sección 4](#4-diseño-con-bootstrap).

---

## Tabla de contenidos

1. [Requisitos](#1-requisitos)
2. [Instalación paso a paso](#2-instalación-paso-a-paso)
3. [Estructura del proyecto](#3-estructura-del-proyecto)
4. [Diseño con Bootstrap](#4-diseño-con-bootstrap)
5. [Crear una app nueva](#5-crear-una-app-nueva)
6. [Comandos del día a día](#6-comandos-del-día-a-día)
7. [Migraciones](#7-migraciones)
8. [Convenciones de commits](#8-convenciones-de-commits)
9. [Cómo abrir un Pull Request](#9-cómo-abrir-un-pull-request)
10. [Problemas frecuentes](#10-problemas-frecuentes)

---

## 1. Requisitos

Necesitas tener instalado esto **antes** de empezar:

| Programa | Versión requerida | Para qué | Cómo verificar que lo tienes |
| --- | --- | --- | --- |
| **Git** | Versión estable reciente | Descargar y subir el código | `git --version` |
| **uv** | Versión estable reciente | Gestionar Python y las dependencias | `uv --version` |
| **Python** | **3.13 o superior** | Ejecutar el proyecto | `uv python list` |
| **PostgreSQL** | **18** (el servidor usa la 18.6) | Base de datos | `psql --version` |


### Instalar uv

Sigue las instrucciones oficiales de Astral para instalar `uv` en tu sistema operativo:

[Documentación oficial de instalación de uv](https://docs.astral.sh/uv/getting-started/installation/)

Cuando termines, cierra y vuelve a abrir la terminal. Comprueba que quedó instalado:

```bash
uv --version
```
---

## 2. Instalación paso a paso

### Paso 1 · Descargar el proyecto

```bash
git clone <url-del-repositorio> SISTRA
cd SISTRA
```

Todos los comandos que siguen se ejecutan **dentro de esa carpeta**.

### Paso 2 · Instalar las dependencias

```bash
uv sync
```

Esto crea la carpeta `.venv/` con Python y las librerías, en las versiones exactas que están en `uv.lock`. Puede tardar un par de minutos la primera vez.

### Paso 3 · Generar la clave secreta

Django necesita una clave secreta única. Genérala con:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Te va a imprimir algo como `k3jd8*v2...`. **Cópiala**, la necesitas en el paso siguiente.

### Paso 4 · Crear el archivo `.env`

En la raíz del proyecto crea un archivo llamado exactamente **`.env`** (con el punto al principio) y pega esto dentro:

```ini
# Django
DJANGO_SECRET_KEY=pega-aqui-la-clave-que-generaste
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# PostgreSQL
POSTGRES_DB=sistra
POSTGRES_USER=sistra
POSTGRES_PASSWORD=sistra
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Reemplaza `pega-aqui-la-clave-que-generaste` por la clave del paso 3.

> **Importante:** `.env` está en el `.gitignore`. **Nunca se sube al repositorio.** Cada quien tiene el suyo con sus propias credenciales.

#### Qué significa cada variable

| Variable | Qué es | Obligatoria |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Clave secreta de Django | Sí |
| `DJANGO_DEBUG` | `True` solo en tu máquina. En el servidor va `False` | No (por defecto `False`) |
| `DJANGO_ALLOWED_HOSTS` | Desde qué direcciones se puede abrir, separadas por coma | No |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Orígenes de confianza **con `https://`**, separados por coma. Solo hace falta en el servidor | No |
| `POSTGRES_DB` | Nombre de la base de datos | Sí |
| `POSTGRES_USER` | Usuario de PostgreSQL | Sí |
| `POSTGRES_PASSWORD` | Contraseña de ese usuario | Sí |
| `POSTGRES_HOST` | Dónde está PostgreSQL | No (por defecto `localhost`) |
| `POSTGRES_PORT` | Puerto de PostgreSQL | No (por defecto `5432`) |

### Paso 5 · Preparar la base de datos

Necesitas un PostgreSQL 18, la misma versión del servidor, corriendo en tu equipo o en Docker, como prefieras, con una base de datos y un usuario que **coincidan con los valores de tu `.env`**.

> **Cada quien trabaja con su propia base de datos local.** La estructura de las tablas se comparte por las migraciones (van en git), no copiando la base. Por eso, después de cada `git pull`, corre `migrate`.

### Paso 6 · Crear las tablas

```bash
uv run python manage.py migrate
```

Este comando crea en PostgreSQL las tablas que Django necesita. Si ves errores de conexión aquí, revisa el [punto 10](#10-problemas-frecuentes).

Para poder iniciar sesión en tu máquina, crea un administrador local:

```bash
uv run python manage.py createsuperuser
```

Te pide correo institucional, nombre, cédula, nombre de usuario y la contraseña dos veces. Queda con el rol **Administrador**. Es el mismo comando con el que se crea el administrador en el servidor.

### Paso 7 · Levantar el servidor

```bash
uv run python manage.py runserver
```

Si todo salió bien verás algo así:

```
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
```

Abre esa dirección en el navegador. **Vas a ver una página de error 404 (Page not found)**, y eso es lo correcto: las apps ya tienen sus rutas registradas, pero todavía no hay ninguna pantalla. Lo importante es que el servidor arrancó.

Para detenerlo: `Ctrl + C`.

---

## 3. Estructura del proyecto

```
SISTRA/
├── manage.py           # Con esto se ejecutan todos los comandos de Django
├── pyproject.toml      # Lista de dependencias
├── uv.lock             # Versiones exactas (se sube a git)
├── .gitignore          # Qué archivos NO se suben
├── .env                # Tus credenciales (NO se sube, lo creas tú)
│
├── config/             # Configuración del proyecto
│   ├── settings.py     # Toda la configuración
│   ├── urls.py         # Las rutas principales
│   ├── asgi.py
│   └── wsgi.py
│
├── apps/               # ← AQUÍ van todas las apps de SISTRA (ver tabla abajo)
│   ├── usuarios/
│   ├── parametrizacion/
│   ├── personas/
│   ├── procesos/
│   ├── propuestas/
│   ├── informes/
│   ├── cargue_up/
│   ├── seguimiento/
│   ├── reportes/
│   └── dashboard/
│
├── docs/
│   └── database/       # Diccionario de datos y reglas de negocio de la BD
│
├── documentos/         # Archivos que suben los usuarios (su contenido NO se sube a git)
├── static/             # CSS, JS e imágenes propios del proyecto
│
└── templates/          # Plantillas compartidas
    └── base.html       # Diseño base del que heredan todas las páginas
```

### Sobre `apps/`: dónde trabaja cada requisito

Las apps están organizadas **por tema, no por requisito**, porque varios requisitos usan las mismas tablas. Por ejemplo, la tabla `cargue_up` la usan SISTRA-03, 04, 05, 08 y 09, y una tabla solo puede vivir en una app. Por eso varios requisitos comparten app.

| App | Tablas (`models.py`) | Requisito → tu archivo en `views/`, `forms/` y `templates/` |
| --- | --- | --- |
| `usuarios` | `rol`, `permiso`, `rol_permiso`, `usuario` | SISTRA-10 → `roles` · SISTRA-13 → `logueo` |
| `parametrizacion` | `facultad`, `carrera`, `periodo_academico`, `actividad`, `tipo_rechazo`, `parametro`, `plantilla`, `version_plantilla` | SISTRA-11 → `parametrizacion` |
| `personas` | `estudiante`, `director`, `estudiante_carrera`, `director_carrera` | SISTRA-10 → `registro_estudiantes` |
| `procesos` | `proceso_trabajo_social`, `proceso_actividad` | Sin pantallas propias; la usan SISTRA-01, 06 y 14 |
| `propuestas` | `propuesta`, `actividad_cronograma` | SISTRA-01 → `montaje` · SISTRA-02 → `aprobacion` |
| `informes` | `informe` | SISTRA-06 → `montaje` · SISTRA-07 → `aprobacion` |
| `cargue_up` | `cargue_up`, `historial_cargue_up` | SISTRA-03 → `cargue_propuesta` · SISTRA-04 → `aviso_propuesta` · SISTRA-05 → `verificacion_propuesta` · SISTRA-08 → `aviso_informe` · SISTRA-09 → `verificacion_informe` |
| `seguimiento` | `historial_estado`, `notificacion`, `auditoria` | Sin pantallas propias; todos los requisitos escriben aquí historial, avisos y auditoría |
| `reportes` | — | SISTRA-12 → `reportes` |
| `dashboard` | — | SISTRA-14 → `dashboard` |

Las tablas son las del [diccionario de datos](docs/database/01_diccionario_de_datos.md). Las apps ya están registradas en `INSTALLED_APPS` y sus rutas en `config/urls.py`: **no hace falta crear apps nuevas** para ningún requisito.

### Cómo se trabaja dentro de una app

**Los modelos ya están definidos. Tú trabajas en tus vistas, formularios y plantillas.** Por ejemplo, en `propuestas`:

```
apps/propuestas/
├── models.py              # Tablas de la app. No se cambian sin avisar (ver reglas)
├── urls.py                # Rutas de la app: cada requisito agrega las suyas
├── views/
│   ├── montaje.py         # SISTRA-01
│   └── aprobacion.py      # SISTRA-02
├── forms/
│   ├── montaje.py         # SISTRA-01
│   └── aprobacion.py      # SISTRA-02
├── templates/propuestas/
│   ├── montaje/           # Plantillas de SISTRA-01
│   └── aprobacion/        # Plantillas de SISTRA-02
└── tests/
    ├── test_montaje.py    # Pruebas de SISTRA-01
    └── test_aprobacion.py # Pruebas de SISTRA-02
```

Los archivos de pruebas empiezan con `test_` para que `uv run python manage.py test` los encuentre solo. `procesos` y `seguimiento`, que no tienen pantallas, tienen un `tests/test_modelos.py` para probar sus restricciones.

Así se conectan las piezas, usando SISTRA-01 de ejemplo:

```python
# apps/propuestas/views/montaje.py
from django.shortcuts import render

from apps.propuestas.models import Propuesta


def inicio(request):
    propuestas = Propuesta.objects.filter(...)
    return render(request, 'propuestas/montaje/inicio.html', {'propuestas': propuestas})
```

```python
# apps/propuestas/urls.py  (el import de tu módulo ya está escrito)
urlpatterns = [
    # SISTRA-01 · Montaje de propuesta – Trabajo Social
    path('mi-propuesta/', montaje.inicio, name='montaje'),

    # SISTRA-02 · Aprobación de propuesta
]
```

La plantilla va en `apps/propuestas/templates/propuestas/montaje/inicio.html`, y para enlazar la pantalla desde otra plantilla se usa `{% url 'propuestas:montaje' %}`, siempre con el nombre de la app delante.

Si tu requisito usa tablas de otra app (por ejemplo, SISTRA-04 crea filas en `cargue_up` y escribe en `seguimiento`), **importa sus modelos; no los copies ni los vuelvas a definir**.

### Reglas para no pisarse con los compañeros

1. **Solo editas tus archivos**: tu módulo en `views/`, en `forms/` y en `tests/`, y tu carpeta en `templates/`. Si necesitas algo en el archivo de otro requisito, pídeselo a su responsable.
2. **En `urls.py`, tus rutas van debajo del comentario de tu requisito.** Es el único archivo que comparten todos los de la app; si dos agregan rutas al mismo tiempo y git marca conflicto, se conservan las líneas de los dos.
3. **`models.py` no se cambia por tu cuenta.** Si necesitas un campo nuevo o un cambio, avisa al equipo y hazlo en un PR aparte, solo con el modelo y su migración (ver [sección 7](#7-migraciones)). Así no salen dos migraciones a la vez en la misma app.
4. **Si tu archivo crece mucho**, puedes partirlo en otros con el mismo prefijo, por ejemplo `views/montaje_plantilla.py`, sin tocar los de los demás.

### Sobre el usuario del sistema

SISTRA no usa el usuario que trae Django (`auth.User`). Usa el suyo, `Usuario`, en `apps/usuarios/models.py`, con los campos de la tabla `usuario` del DER. Se inicia sesión con **correo institucional y contraseña**.

- **Si tu modelo apunta a un usuario, nunca importes `Usuario` ni uses `auth.User`.** Usa siempre `settings.AUTH_USER_MODEL`:

  ```python
  from django.conf import settings
  from django.db import models

  class Estudiante(models.Model):
      usuario = models.OneToOneField(
          settings.AUTH_USER_MODEL, on_delete=models.PROTECT, db_column='id_usuario'
      )
  ```

- En el resto del código (vistas, servicios), obtén el modelo con `get_user_model()`:

  ```python
  from django.contrib.auth import get_user_model

  Usuario = get_user_model()
  ```

- Para crear usuarios, usa `Usuario.objects.create_user(...)`: guarda la contraseña como hash. Nunca asignes `password` directamente.
- Los permisos salen de las tablas `rol` y `rol_permiso`. En las vistas se comprueban con `request.user.has_perm('nombre_del_permiso')` o con `@permission_required('nombre_del_permiso')`.

### Sobre el panel administrativo

El panel de Django (`/admin/`) **está desactivado**.

---

## 4. Diseño con Bootstrap

Toda la interfaz de SISTRA se construye con **Bootstrap 5.3**. Ya viene cargado en `templates/base.html`, no hay que instalar nada.

**La regla:** usa los componentes y las clases de Bootstrap. No escribas CSS propio salvo para lo que Bootstrap no cubra. Si cada quien inventa sus estilos, terminamos con catorce versiones distintas del mismo botón.

### Todas tus plantillas heredan de `base.html`

```django
{% extends 'base.html' %}

{% block titulo %}Mi pantalla · SISTRA-UP{% endblock %}

{% block contenido %}
    <h1>Hola</h1>
{% endblock %}
```

Bloques disponibles: `titulo`, `contenido`, `css` y `js`.

Nunca vuelvas a enlazar Bootstrap dentro de tu plantilla: ya viene de `base.html`.

### Componentes que vas a necesitar

La documentación oficial está en [getbootstrap.com](https://getbootstrap.com/docs/5.3/). Estos son los que pide el BRD:

| Necesidad | Componente de Bootstrap |
| --- | --- |
| Ventanas de confirmación y «Ver detalle» | Modal |
| Bandejas de propuestas e informes | Table |
| Etiquetas de estado y semáforo | Badge |
| Barra de avance del formulario | Progress |
| Mensajes de éxito, error y advertencia | Alert · Toast |
| Formularios con errores por campo | Forms · Validation |

> Antes de desplegar en el servidor de la universidad hay que bajar Bootstrap a una carpeta `static/` del proyecto, por si la red bloquea el CDN.

---

## 5. Crear una app nueva

> Las apps de los 14 requisitos **ya existen** (ver [sección 3](#3-estructura-del-proyecto)). Esto solo aplica si el equipo decide agregar una app que hoy no está prevista.

`startapp` **no crea la carpeta destino**, así que primero la creas tú y después se la pasas como segundo argumento:

```bash
mkdir apps/propuestas
uv run python manage.py startapp propuestas apps/propuestas
```

Después hay **dos ajustes obligatorios**, porque la app no está en la raíz:

**1.** En `apps/propuestas/apps.py`, cambia el `name`:

```python
class PropuestasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.propuestas'        # ← con el prefijo apps.
```

**2.** En `config/settings.py`, agrégala a `INSTALLED_APPS` con la ruta completa:

```python
INSTALLED_APPS = [
    ...
    'apps.propuestas',              # ← con el prefijo apps.
]
```

Si te saltas cualquiera de los dos, Django no encuentra la app y falla al arrancar.

Si la app tiene pantallas, registra también sus rutas en `config/urls.py` con `path('propuestas/', include('apps.propuestas.urls'))`, y sigue la misma organización de las demás: `views/`, `forms/` y `templates/<app>/` con un módulo por requisito.

---

## 6. Comandos del día a día

Todos se ejecutan desde la carpeta del proyecto.

| Comando | Qué hace |
| --- | --- |
| `uv sync` | Instala las dependencias del lockfile |
| `uv add <paquete>` | Agrega una dependencia nueva |
| `uv run python manage.py runserver` | Levanta el servidor |
| `uv run python manage.py makemigrations` | Genera las migraciones tras cambiar un modelo |
| `uv run python manage.py migrate` | Aplica las migraciones a tu base de datos |
| `uv run python manage.py check` | Revisa que no haya errores de configuración |
| `uv run python manage.py test` | Corre las pruebas de todas las apps |
| `uv run python manage.py test apps.propuestas.tests.test_montaje` | Corre solo las pruebas de un archivo |
| `uv run python manage.py startapp <nombre> apps/<nombre>` | Crea una app dentro de `apps/` |

### Después de cada `git pull`

```bash
uv sync                              # si cambiaron pyproject.toml o uv.lock
uv run python manage.py migrate      # si llegaron migraciones nuevas
```

Si no lo haces, te van a salir errores raros de columnas que no existen.

---

## 7. Migraciones

Las migraciones son el historial de cambios de la estructura de la base de datos. Viven en `apps/<app>/migrations/`, **se suben a git** y son lo que hace que todos tengan las mismas tablas aunque cada quien use su propia base local.

### Flujo normal

Cada vez que cambias un modelo en `models.py`:

```bash
uv run python manage.py makemigrations propuestas -n agrega_campo_estado   # genera la migración
uv run python manage.py migrate                                            # la aplica a tu base local
```

Revisa el archivo que se generó y súbelo **en el mismo commit** que el cambio del modelo. Con `-n` le pones un nombre que diga qué hace, así el historial se entiende.

Antes de crear una migración, trae lo último de `develop`: es la mejor forma de evitar conflictos.

### Reglas

- **Nunca edites ni borres una migración que ya está en `develop`.** A los demás ya se les aplicó. Si te equivocaste, crea una migración nueva que lo corrija.
- Solo puedes borrar y regenerar migraciones **tuyas que todavía no se han fusionado**.
- Nunca borres la carpeta `migrations/` ni su `__init__.py`.
- Si hiciste `pull`, `rebase` o cambiaste de rama y llegaron migraciones nuevas, corre `migrate`.

### Si `makemigrations` te hace una pregunta

Pasa al agregar un campo obligatorio a un modelo que ya tiene filas (el mensaje dice *"you are trying to add a non-nullable field..."*). Tienes dos salidas:

- Escoge la opción 1 y escribe un valor por defecto solo para esa migración, o
- Cancela con `Ctrl + C`, define `default=...` o `null=True` en el campo y vuelve a correr `makemigrations`.

### Conflicto de migraciones

Si dos personas crean una migración en la misma app (o en apps relacionadas por una `ForeignKey`) partiendo del mismo punto, ambas se llaman `0003_...` y Django se queja:

```
CommandError: Conflicting migrations detected; multiple leaf nodes in the migration graph
```

Git no marca conflicto, porque los archivos tienen nombres distintos; el error aparece al correr `migrate`. Como cada quien trabaja en su propia app no debería ser lo normal, pero puede pasar.

**Se arregla en tu rama, antes del PR, y la que se rehace es la tuya:**

1. Borra tu archivo de migración (solo el tuyo; el que ya está en `develop` no se toca).
2. Recrea tu base local vacía, con los mismos datos de tu `.env`, porque ahí ya estaba aplicada la migración que borraste.
3. Corre `migrate` (aplica las de `develop`), después `makemigrations` (regenera la tuya) y `migrate` otra vez.
4. Haz commit de la migración nueva.

Django también sugiere `makemigrations --merge`, pero regenerar la tuya deja un historial más limpio.

### Comandos útiles

| Comando | Qué hace |
| --- | --- |
| `uv run python manage.py showmigrations` | Lista las migraciones y cuáles ya aplicaste |
| `uv run python manage.py migrate <app> <numero>` | Devuelve esa app a una migración anterior |
| `uv run python manage.py makemigrations --check --dry-run` | Avisa si cambiaste un modelo y falta la migración |

---

## 8. Convenciones de commits

Los mensajes siguen el formato [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/):

```
tipo(módulo): descripción
```

### Tipos

| Tipo | Cuándo se usa |
| --- | --- |
| `feat` | Funcionalidad nueva |
| `fix` | Corrección de un error |
| `refactor` | Cambio interno que no altera el comportamiento |
| `style` | Formato o estilos, sin tocar la lógica |
| `docs` | Documentación |
| `test` | Pruebas |
| `chore` | Configuración y dependencias |

### Reglas

- El tipo va en **minúscula**, seguido de `:` y un espacio.
- La descripción va en **minúscula**, en **presente** y **sin punto final**: se escribe "agrega", no "agregado" ni "Agregar.".
- Máximo unos 72 caracteres en la primera línea.
- **Un commit por cambio lógico.** Si el mensaje necesita un "y", probablemente son dos commits.
- Si cambiaste un modelo, **la migración va en el mismo commit**.

### Ejemplos correctos

```
feat(propuestas): agrega el formulario de montaje
fix(login): corrige la validación del correo
refactor(informes): separa la lógica en services.py
docs: documenta la instalación en el README
chore: actualiza django a 6.1.3
```

### Ejemplos incorrectos

```
Cambios                       ← no dice nada
feat: Agregué el formulario.  ← mayúscula, pasado y punto final
arreglo de bugs varios        ← sin tipo y son varios cambios
```

---

## 9. Cómo abrir un Pull Request

`main` y `develop` están protegidas: **no se puede hacer `push` directo a ninguna de las dos.** Todo entra por Pull Request hacia `develop`.

### Las ramas

| Rama | Para qué |
| --- | --- |
| `main` | Versión estable, la que se entrega |
| `develop` | Donde se integra el trabajo de todos |
| `feature/<modulo>-<descripcion>` | Tu funcionalidad nueva |
| `fix/<descripcion>` | Corrección de un error |

Ejemplos de nombres de rama: `feature/propuestas-subir-archivo`, `fix/login-token-expirado`.

### Paso 1 · Parte siempre de `develop` actualizado

```bash
git checkout develop
git pull origin develop
```

### Paso 2 · Crea tu rama

```bash
git checkout -b feature/propuestas-subir-archivo
```

### Paso 3 · Trabaja y haz tus commits

```bash
git status                    # mira qué cambiaste
git add .                     # agrega los cambios
git commit -m "feat(propuestas): agrega el formulario de montaje"
```

Antes de hacer `commit`, revisa con `git status` que **no estés subiendo** `.env`, `.venv/` ni carpetas de tu editor.

### Paso 4 · Sube tu rama

```bash
git push origin feature/propuestas-subir-archivo
```

### Paso 5 · Abre el Pull Request

Después del `push`, GitHub te muestra un enlace en la terminal para crear el PR. También puedes entrar al repositorio en GitHub y usar la pestaña **Pull requests → New pull request**.

Configúralo así:

- **base:** `develop` ← aquí va tu trabajo
- **compare:** tu rama

El título sigue la misma convención que los commits: `feat(propuestas): agrega el formulario de montaje`.

En la descripción explica **qué hace** el cambio y **por qué**.

### Paso 6 · Espera la revisión

Lo revisa y aprueba el **full stack**. Mientras el PR esté abierto, los commits que subas a tu rama se agregan solos; no hace falta abrir otro PR.

### Antes de abrir el PR, revisa que

- `uv run python manage.py check` pasa sin errores
- `uv run python manage.py test` pasa sin errores
- `uv run python manage.py makemigrations --check --dry-run` no reporta migraciones sin generar
- Solo cambiaste los archivos de tu requisito (y tus líneas en `urls.py`)
- Las migraciones nuevas están incluidas en el commit
- Tu rama está actualizada con `develop`
- No subes `print()` ni credenciales
- No subes `.env`, `.venv/` ni archivos de tu editor

### Si `develop` avanzó mientras trabajabas

```bash
git checkout develop
git pull origin develop
git checkout feature/propuestas-subir-archivo
git rebase develop
git push --force-with-lease
```

Si al traer `develop` llegaron migraciones nuevas, corre `migrate`. Si Django reporta un conflicto de migraciones, sigue los pasos de la [sección 7](#7-migraciones).

### Cuando ya fusionaron tu PR

```bash
git checkout develop
git pull origin develop
git branch -d feature/propuestas-subir-archivo
```

---

## 10. Problemas frecuentes

| Problema | Solución |
| --- | --- |
| `KeyError: 'DJANGO_SECRET_KEY'` | Falta el archivo `.env` o le falta esa variable. Repite los pasos 3 y 4 |
| `connection refused` al migrar | PostgreSQL no está corriendo. En Linux o WSL: `sudo service postgresql start` |
| `password authentication failed` | El usuario o la contraseña de `.env` no coinciden con los de tu PostgreSQL local |
| `database "sistra" does not exist` | Falta crear la base de datos con el nombre que pusiste en `POSTGRES_DB` de tu `.env` |
| `permission denied to create database` al correr `test` | Las pruebas crean una base temporal (`test_<tu_base>`), y tu usuario de PostgreSQL necesita permiso para hacerlo: `ALTER USER <tu_usuario> CREATEDB;` |
| `No module named 'apps.X'` | Revisa el `name` en `apps/X/apps.py` y la entrada en `INSTALLED_APPS`. Los dos llevan el prefijo `apps.` |
| `relation "..." does not exist` | Falta correr `uv run python manage.py migrate` |
| `Conflicting migrations detected` | Dos migraciones salieron del mismo punto. Sigue los pasos de la [sección 7](#7-migraciones) |
| `InconsistentMigrationHistory` | Tu base local tiene migraciones aplicadas en un orden distinto al del código (pasa al cambiar de rama o al borrar una migración). Recrea tu base local vacía y corre `migrate` |
| El navegador muestra un 404 en `/` | Es lo esperado mientras no exista la pantalla de inicio (SISTRA-14). El servidor está bien |
| `NoReverseMatch` al usar `{% url %}` | Falta el prefijo de la app: es `{% url 'propuestas:montaje' %}`, no `{% url 'montaje' %}` |
| `TemplateDoesNotExist` | La plantilla va en `apps/<app>/templates/<app>/<tu_modulo>/` y se pide como `'<app>/<tu_modulo>/archivo.html'` |
