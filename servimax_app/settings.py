from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv 

load_dotenv() 

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-p_%woq5*pl+-#ad=^=2_#i1vsyf9&a*-p6$xob*eak%3$cyp44')

# --- CONFIGURACIÓN SEGURA PARA PRODUCCIÓN (RENDER) Y LOCAL ---

# DEBUG: Será False en Render (si existe la variable RENDER) y True en tu PC.
DEBUG = 'RENDER' not in os.environ

ALLOWED_HOSTS = ['*']

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

# --- CONFIGURACIÓN DE BASE DE DATOS INTELIGENTE ---
if 'RENDER' in os.environ:
    # Si estamos en Render, usamos PostgreSQL (la real)
    DATABASES = {
        'default': dj_database_url.config(
            default=os.environ.get('DATABASE_URL'),
            conn_max_age=600,
            ssl_require=True
        )
    }
else:
    # Si estamos en LOCAL (tu PC), usamos SQLite (el laboratorio)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
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

# --- CONFIGURACIÓN DE ALMACENAMIENTO CLOUDINARY ---

CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')
CLOUDINARY_MEDIA_BACKEND = 'cloudinary_storage.storage.MediaCloudinaryStorage'

if CLOUDINARY_URL:
    STORAGES["default"]["BACKEND"] = CLOUDINARY_MEDIA_BACKEND
    MEDIA_URL = '/media/'
    MEDIA_ROOT = '' 
    
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': CLOUDINARY_URL.split('@')[1].split('.')[0] if '@' in CLOUDINARY_URL else None,
        'HAVE_IMAGE_TRANSFORMATION': True,
        'IMAGE_TRANSFORMATION': {
            'quality': 'auto',
            'fetch_format': 'auto',
            'width': 1920,
            'crop': 'limit'
        }
    }
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    STORAGES["default"]["BACKEND"] = 'django.core.files.storage.FileSystemStorage' 

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

DATA_UPLOAD_MAX_MEMORY_SIZE = 104857600
FILE_UPLOAD_MAX_MEMORY_SIZE = 104857600

# =========================================================
# CONFIGURACIÓN DE CORREO ELECTRÓNICO (SMTP) - SEGURO
# =========================================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'  # Asumiendo que el correo que usas es de Gmail
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_USUARIO')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_CONTRASENA')