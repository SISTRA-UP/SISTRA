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
7. [Convenciones de commits](#7-convenciones-de-commits)
8. [Cómo abrir un Pull Request](#8-cómo-abrir-un-pull-request)
9. [Problemas frecuentes](#9-problemas-frecuentes)

---

## 1. Requisitos

Necesitas tener instalado esto **antes** de empezar:

| Programa | Versión requerida | Para qué | Cómo verificar que lo tienes |
| --- | --- | --- | --- |
| **Git** | Versión estable reciente | Descargar y subir el código | `git --version` |
| **uv** | Versión estable reciente | Gestionar Python y las dependencias | `uv --version` |
| **Python** | **3.13 o superior** | Ejecutar el proyecto | `uv python list` |
| **PostgreSQL** | **14 o superior** | Base de datos | `psql --version` |


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

### Paso 5 · Crear la base de datos

Los valores tienen que coincidir con los que pusiste en `.env`.

En Linux, macOS o WSL:

```bash
sudo -u postgres psql -c "CREATE USER sistra WITH PASSWORD 'sistra';"
sudo -u postgres psql -c "CREATE DATABASE sistra OWNER sistra;"
```

En Windows:

```powershell
psql -U postgres -c "CREATE USER sistra WITH PASSWORD 'sistra';"
psql -U postgres -c "CREATE DATABASE sistra OWNER sistra;"
```

Te va a pedir la contraseña del usuario `postgres`, la que pusiste al instalar PostgreSQL.

### Paso 6 · Crear las tablas

```bash
uv run python manage.py migrate
```

Este comando crea en PostgreSQL las tablas que Django necesita. Si ves errores de conexión aquí, revisa el [punto 9](#9-problemas-frecuentes).

### Paso 7 · Levantar el servidor

```bash
uv run python manage.py runserver
```

Si todo salió bien verás algo así:

```
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
```

Abre esa dirección en el navegador. **Vas a ver una página de error 404**, y eso es lo correcto: el proyecto todavía no tiene ninguna pantalla. Lo importante es que el servidor arrancó.

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
├── apps/               # ← AQUÍ van todas las apps de SISTRA
│   └── __init__.py     # (está vacía a propósito)
│
└── templates/          # Plantillas compartidas
    └── base.html       # Diseño base del que heredan todas las páginas
```

### Sobre `apps/`

Está vacía a propósito. Ahí va **una app por cada requisito o grupo de requisitos del BRD**, y nunca sueltas en la raíz del proyecto.

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
| `uv run python manage.py startapp <nombre> apps/<nombre>` | Crea una app dentro de `apps/` |

### Después de cada `git pull`

```bash
uv sync                              # si cambiaron pyproject.toml o uv.lock
uv run python manage.py migrate      # si llegaron migraciones nuevas
```

Si no lo haces, te van a salir errores raros de columnas que no existen.

---

## 7. Convenciones de commits

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

## 8. Cómo abrir un Pull Request

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
- `uv run python manage.py makemigrations --check --dry-run` no reporta migraciones sin generar
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

### Cuando ya fusionaron tu PR

```bash
git checkout develop
git pull origin develop
git branch -d feature/propuestas-subir-archivo
```

---

## 9. Problemas frecuentes

| Problema | Solución |
| --- | --- |
| `KeyError: 'DJANGO_SECRET_KEY'` | Falta el archivo `.env` o le falta esa variable. Repite los pasos 3 y 4 |
| `connection refused` al migrar | PostgreSQL no está corriendo. En Linux o WSL: `sudo service postgresql start` |
| `password authentication failed` | El usuario o la contraseña de `.env` no coinciden con los del paso 5 |
| `database "sistra" does not exist` | Te faltó crear la base de datos. Repite el paso 5 |
| `No module named 'apps.X'` | Revisa el `name` en `apps/X/apps.py` y la entrada en `INSTALLED_APPS`. Los dos llevan el prefijo `apps.` |
| `relation "..." does not exist` | Falta correr `uv run python manage.py migrate` |
| El navegador muestra 404 en `/` | Es lo esperado: aún no hay pantallas. El servidor está bien |
