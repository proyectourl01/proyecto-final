Sistema de Gestión de Susceptibles (SGS)

El Sistema de Gestión de Susceptibles (SGS) es una aplicación web ligera diseñada para administrar, dar seguimiento y gestionar de forma segura los registros de vacunación, organizados por períodos (Año y Mes). Incluye una Papelera de Reciclaje (Soft Delete) para garantizar la integridad de los datos.

Tecnologías Utilizadas

Backend: Python 3.x

Framework: Flask

Base de Datos: SQLite 3 (demo.db)

Dependencia Crítica: python-dateutil

Frontend: HTML5, Jinja2, Bootstrap 5

1. Instalación y Ejecución Local (Desarrollo)
1.1. Preparación de Archivos

Asegúrate de que los archivos app.py y requirements.txt estén actualizados.

Elimina cualquier archivo demo.db existente para comenzar con una base de datos limpia.

1.2. Configuración e Instalación de Dependencias

Abre tu terminal y activa el entorno virtual (venv).

Instala las dependencias ejecutando:

pip install -r requirements.txt

1.3. Ejecutar la Aplicación

Ejecuta el script principal:

python app.py


Accede al sistema en el navegador:
http://127.0.0.1:5000/

Credenciales Iniciales

Usuario: admin

Contraseña: [La definida en app.py]

2. Despliegue en Producción (PythonAnywhere)
2.1. Actualizar Código e Instalar

Abre una consola Bash en PythonAnywhere.

Actualiza el repositorio:

git pull


Instala todas las dependencias:

pip install -r requirements.txt

2.2. Migración de la Base de Datos

Elimina la base de datos anterior:

rm demo.db


Ve a la pestaña Web y presiona Reload para aplicar los cambios.
