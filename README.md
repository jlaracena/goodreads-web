# goodreads-web

App web para visualizar y priorizar tu lista de lectura de Goodreads, con una calculadora de plan anual de libros.

Pensada para correr localmente y ser accesible desde cualquier dispositivo en la red.

---

## Qué hace

### Lista de libros
Consume la API de Goodreads y calcula un **score ponderado** para cada libro, combinando rating promedio y cantidad de ratings. Tres vistas:

| Ruta | Descripción |
|---|---|
| `/` | Lista `to-read` ordenada por score de rating |
| `/per-page/` | Lista `to-read` ordenada por score ajustado por páginas (favorece libros cortos) |
| `/own-paper/` | Shelf `own-paper` (libros físicos) |

La tabla es ordenable por cualquier columna con click. Los datos se cargan de forma asíncrona, por lo que la página responde de inmediato y muestra un spinner mientras consulta la API.

### Plan anual (`/plan/`)
Calculadora para cumplir la meta de leer N libros en el año. Ingresa:
- Libros ya leídos
- Meta total
- Páginas del libro actual y páginas ya leídas (opcional)

Muestra días restantes, días por libro, páginas/día para el libro actual, y el calendario de fechas límite para cada libro.

---

## Cómo correr

### Requisitos
- Python 3.10+
- Cuenta en Goodreads con API key

### Instalación

```bash
git clone https://github.com/jlaracena/goodreads-web.git
cd goodreads-web

python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp .env.example .env
# editar .env con tus credenciales
```

### Variables de entorno (`.env`)

```
DJANGO_SECRET_KEY=genera-una-clave-aleatoria
GOODREADS_API_KEY=tu-api-key
GOODREADS_USER_ID=tu-user-id
```

El `GOODREADS_USER_ID` es el identificador de tu perfil, visible en la URL de tu perfil de Goodreads.

### Correr

```bash
venv/bin/python manage.py runserver 0.0.0.0:8766
```

Luego abrir `http://localhost:8766` (o `http://<ip-del-servidor>:8766` desde otro dispositivo en la red).

---

## Correr al inicio del sistema (Linux/macOS con systemd/launchd)

El repo incluye un archivo `com.jinshi.goodreads.plist` de ejemplo para `launchd` (macOS). Ajusta las rutas al directorio del proyecto y al Python del virtualenv, luego:

```bash
cp com.goodreads-web.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.goodreads-web.plist
```

Logs en `/tmp/goodreads-web.log`.

---

## Score ponderado

El score combina rating promedio y popularidad del libro usando una función de saturación exponencial, para que los libros con muchos ratings no dominen desproporcionadamente sobre libros menos conocidos pero bien valorados.

```
score          = 0.5 × rating + 1.25 × (1 − e^(−ratings/720000))
score_per_page = score + 1.25 × (1 − e^(−300/(1+páginas)))
```

`score_per_page` penaliza los libros muy largos, útil para priorizar lecturas rápidas.
