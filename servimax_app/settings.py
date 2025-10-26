# servimax_app/settings.py

from pathlib import Path
import os
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Lee la SECRET_KEY desde una variable de entorno, con un valor por defecto para desarrollo
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-p_%woq5*pl+-#ad=^=2_#i1vsyf9&a*-p6$xob*eak%3$cyp44')

# SECURITY WARNING: don't run with debug turned on in production!
# DEBUG se lee de una variable de entorno, por defecto es 'True' en desarrollo
DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = []
# Configuración para Render (o cualquier otro host)
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# Application definition

INSTALLED_APPS = [
    'taller',
    # 'cloudinary_storage', # <-- ESTA LÍNEA SE ELIMINA O COMENTA SI EXISTÍA
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic', # Para servir estáticos en desarrollo con runserver
    'django.contrib.staticfiles',
    'cloudinary', # <-- ASEGÚRATE DE QUE ESTA LÍNEA ESTÉ PRESENTE
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # Whitenoise para servir estáticos eficientemente
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'servimax_app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [], # Puedes añadir directorios de plantillas globales aquí si es necesario
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'servimax_app.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

# Usa dj_database_url para configurar la base de datos desde DATABASE_URL (para Render/Heroku)
# Si no está definida, usa SQLite localmente.
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600 # Tiempo de vida de la conexión (bueno para PostgreSQL)
    )
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'Europe/Madrid'
USE_I18N = True
USE_TZ = True # Recomendado activar para manejar zonas horarias


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
# Directorios donde Django buscará archivos estáticos además de los de cada app
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'taller/static'),]
# Directorio donde `collectstatic` reunirá todos los archivos estáticos para producción
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')


# --- CONFIGURACIÓN PARA CLOUDINARY ---

# Leer la URL de Cloudinary desde la variable de entorno CLOUDINARY_URL
CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')

# Solo configurar Cloudinary si la URL está presente (típicamente en producción/Render)
if CLOUDINARY_URL:
    # Indicar a Django que use Cloudinary para los archivos multimedia (fotos)
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

    # Opcional: Si también quieres que Cloudinary maneje los archivos estáticos (CSS, JS)
    # Descomenta la siguiente línea si quieres usar Cloudinary para estáticos
    # STATICFILES_STORAGE = 'cloudinary_storage.storage.StaticHashedCloudinaryStorage'

    # MEDIA_URL lo gestionará Cloudinary basado en tu CLOUDINARY_URL
    # MEDIA_ROOT no es necesario ya que los archivos van a la nube

    # Limpiamos la configuración de STORAGES para "default" si la teníamos
    # (El backend de staticfiles se configurará abajo condicionalmente)
    STORAGES = {} # Empezamos vacío aquí

else:
    # Configuración local (si CLOUDINARY_URL no está definida)
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    # Mantenemos la configuración de STORAGES solo para staticfiles localmente
    STORAGES = {
         "staticfiles": {
             "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
         },
     }


# --- Configuración de Archivos Estáticos (continuación) ---

# Configurar Whitenoise para servir archivos estáticos si NO usamos Cloudinary para ellos
# Si STATICFILES_STORAGE fue definido arriba para Cloudinary, esta sección no se aplica.
if not CLOUDINARY_URL or STORAGES.get("staticfiles", {}).get("BACKEND") != 'cloudinary_storage.storage.StaticHashedCloudinaryStorage':
    # Aseguramos que Whitenoise esté configurado para estáticos si no usamos Cloudinary para ellos
     STORAGES = STORAGES or {} # Asegura que STORAGES sea un diccionario
     STORAGES["staticfiles"] = {
             "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
     }


# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'