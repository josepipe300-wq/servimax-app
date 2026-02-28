# servimax_app/settings.py

from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv 

load_dotenv() 

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-p_%woq5*pl+-#ad=^=2_#i1vsyf9&a*-p6$xob*eak%3$cyp44')

# --- CONFIGURACIÓN SEGURA PARA PRODUCCIÓN (RENDER) Y LOCAL ---

# DEBUG: Será False en Render (si existe la variable RENDER) y True en tu PC.
# DEBUG FORZADO PARA VER EL ERROR:
DEBUG = 'RENDER' not in os.environ

ALLOWED_HOSTS = []

# 1. Si estamos en Render, añadir su dominio automáticamente
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# 2. Si estamos en modo DEBUG (Local), permitir todo para que funcione el móvil
if DEBUG:
    ALLOWED_HOSTS.extend(['127.0.0.1', 'localhost', '*'])

# -------------------------------------------------------------


# Application definition

INSTALLED_APPS = [
    'taller.apps.TallerConfig',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'cloudinary', 
    'cloudinary_storage', 
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
        'DIRS': [BASE_DIR / 'templates'],
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

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    "default": {}, 
}

# --- CONFIGURACIÓN DE ALMACENAMIENTO Y OPTIMIZACIÓN CLOUDINARY ---

CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')
CLOUDINARY_MEDIA_BACKEND = 'cloudinary_storage.storage.MediaCloudinaryStorage'

if CLOUDINARY_URL:
    STORAGES["default"]["BACKEND"] = CLOUDINARY_MEDIA_BACKEND
    MEDIA_URL = '/media/'
    MEDIA_ROOT = '' 
    
    # Configuración para reducir tamaño AUTOMÁTICAMENTE al subir
    CLOUDINARY_STORAGE = {
        # Intentamos obtener el CLOUD_NAME de la URL, si falla usa el valor por defecto de la librería
        'CLOUD_NAME': CLOUDINARY_URL.split('@')[1] if '@' in CLOUDINARY_URL else None,
        
        'HAVE_IMAGE_TRANSFORMATION': True,
        'IMAGE_TRANSFORMATION': {
            'quality': 'auto',      # Compresión inteligente
            'fetch_format': 'auto', # Formato eficiente (WebP/AVIF)
            'width': 1920,          # Reducir a Full HD
            'crop': 'limit'         # No estirar si es pequeña
        }
    }
else:
    # Configuración local si no hay Cloudinary (para desarrollo offline)
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    STORAGES["default"]["BACKEND"] = 'django.core.files.storage.FileSystemStorage' 


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- CONFIGURACIÓN DE AUTENTICACIÓN ---
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

# --- LÍMITES DE SUBIDA AMPLIADOS ---
# 100MB para permitir la subida inicial de fotos grandes (luego Cloudinary las reduce)
DATA_UPLOAD_MAX_MEMORY_SIZE = 104857600
FILE_UPLOAD_MAX_MEMORY_SIZE = 104857600