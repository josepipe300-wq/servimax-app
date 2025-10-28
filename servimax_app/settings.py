# servimax_app/settings.py

from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv # <-- Importar dotenv

load_dotenv() # <-- Cargar variables del archivo .env

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-p_%woq5*pl+-#ad=^=2_#i1vsyf9&a*-p6$xob*eak%3$cyp44')

# DEBUG debe ser False en producción (Render lo configura automáticamente a False si no lo pones)
# Para pruebas, puedes leerlo de una variable de entorno, pero asegúrate que en Render sea False.
# DEBUG = True # <-- Descomentar esta línea para pruebas locales si da problemas ALLOWED_HOSTS
DEBUG = True

ALLOWED_HOSTS = []
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
# Añadir host local si DEBUG es True
if DEBUG:
    ALLOWED_HOSTS.append('127.0.0.1')
    ALLOWED_HOSTS.append('localhost')


# Application definition

INSTALLED_APPS = [
    'taller.apps.TallerConfig', # <-- Mejor usar la configuración explícita de la app
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic', # Necesario para runserver si usas whitenoise
    'django.contrib.staticfiles',
    'cloudinary', # App de Cloudinary
    'cloudinary_storage', # App para integración con Django Storages
    # 'django_storages', # django-storages ya no es necesaria si solo usas cloudinary_storage
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # Whitenoise primero después de Security
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
        # --- AÑADIR DIRECTORIO PARA PLANTILLAS DE AUTENTICACIÓN ---
        'DIRS': [BASE_DIR / 'templates'], # Busca plantillas en una carpeta 'templates' en la raíz
        # --- FIN AÑADIDO ---
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
DATABASES = {
    'default': dj_database_url.config(
        # Usa DATABASE_URL de Render, o sqlite local como fallback
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600
    )
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

# Internationalization
LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'Europe/Madrid'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images) served by Whitenoise
STATIC_URL = 'static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'taller/static'),]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
# Asegurar que Whitenoise esté configurado para estáticos
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    # --- MOVER LA CONFIGURACIÓN DE 'default' AQUÍ DENTRO ---
    "default": {}, # Dejar vacío por ahora, se llenará abajo
}

# --- CONFIGURACIÓN DE ALMACENAMIENTO DE MEDIOS (Cloudinary o Local) ---

CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')
CLOUDINARY_MEDIA_BACKEND = 'cloudinary_storage.storage.MediaCloudinaryStorage'

if CLOUDINARY_URL:
    # --- Configuración para Cloudinary (Producción/Render) ---
    # DEFAULT_FILE_STORAGE ya no se usa directamente, se configura en STORAGES
    STORAGES["default"]["BACKEND"] = CLOUDINARY_MEDIA_BACKEND # Configurar backend default
    MEDIA_URL = '/media/' # Cloudinary genera la URL final
    MEDIA_ROOT = '' # No usado por Cloudinary

else:
    # --- Configuración Local (Desarrollo) ---
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    STORAGES["default"]["BACKEND"] = 'django.core.files.storage.FileSystemStorage' # Configurar backend default


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- CONFIGURACIÓN DE AUTENTICACIÓN ---
LOGIN_REDIRECT_URL = '/'  # Redirigir a la página principal (home) después del login
LOGOUT_REDIRECT_URL = '/' # Redirigir a la página principal (home) después del logout
LOGIN_URL = '/accounts/login/' # La URL donde estará la página de login
# --- FIN CONFIGURACIÓN ---