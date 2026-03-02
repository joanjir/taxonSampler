Proyecto NCBI_COL — comandos básicos

Este README lista los comandos más usados para trabajar en este proyecto (Windows). Ajusta según tu shell/entorno.

Entorno Python (venv)

PowerShell (recommended):

```powershell
# activar el virtualenv (PowerShell)
& .\.venv\Scripts\Activate.ps1

# o en cmd.exe
.\.venv\Scripts\activate.bat

# o en Git Bash / WSL
source .venv/bin/activate
```

Instalar dependencias

```bash
pip install -r requirements.txt
```

Migraciones y base de datos

```bash
# crear migraciones (si modificas modelos)
python manage.py makemigrations
# aplicar migraciones
python manage.py migrate
# crear superusuario
python manage.py createsuperuser
```

Desarrollo local (Django)

```bash
# ejecutar servidor de desarrollo
python manage.py runserver 0.0.0.0:8000
```

Archivos estáticos

```bash
# recolectar archivos estáticos para despliegue
python manage.py collectstatic --noinput
```

Comandos útiles de diagnóstico

```bash
# abrir shell de django
python manage.py shell
# ejecutar pruebas
python manage.py test
# revisar estado de la base de datos para el app taxonomy
python manage.py dbshell  # si está configurado
```

Git - flujo básico

```bash
# ver rama actual
git rev-parse --abbrev-ref HEAD
# ver cambios
git status --short
# añadir todos los cambios
git add -A
# commit con mensaje
git commit -m "Descripción corta del cambio"
# pushear la rama actual
git push origin HEAD
# crear y cambiar a nueva rama
git checkout -b feature/nombre
```

Frontend / assets

- Los archivos estáticos están en `taxbridge/apps/taxonomy/static/`.
- Si cambias JS/CSS, ejecuta `collectstatic` antes de desplegar.

Consejos rápidos

- Para forzar recarga completa en el navegador: Ctrl+Shift+R (Windows).
- Si tienes dudas con settings locales, revisa `config/settings/local.py`.

Si quieres, puedo ampliar este README con instrucciones de despliegue, CI/CD o comandos para Docker/Azure.
