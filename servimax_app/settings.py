# servimax_app/settings.py

from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-p_%woq5*pl+-#ad=^=2_#i1vsyf9&a*-p6$xob*eak%3$cyp44')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = []
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

INSTALLED_APPS = [
    'taller',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'cloudinary', # <-- Asegúrate que esta ya estaba
    'cloudinary_storage', # <-- AÑADE ESTA LÍNEA AQUÍ
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
        'DIRS': [],
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

DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'Europe/Madrid'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'taller/static'),]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# --- CONFIGURACIÓN DE ALMACENAMIENTO (Cloudinary o Local) ---

CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')
# *** TRYING A DIFFERENT BACKEND PATH ***
CLOUDINARY_MEDIA_BACKEND = 'cloudinary_storage.storage.MediaCloudinaryStorage' # Keep original name as fallback reference
# ALTERNATIVE_CLOUDINARY_BACKEND = 'cloudinary.storage.CloudinaryStorage' # Potential simpler path - LET'S TRY THIS

if CLOUDINARY_URL:
    # --- Configuración para Cloudinary (Producción/Render) ---
    # *** TRY USING THE ALTERNATIVE PATH ***
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage' # Revertimos al original por ahora, el error podría ser otro.

    STORAGES = {
        "default": {
            # *** TRY USING THE ALTERNATIVE PATH ***
             "BACKEND": 'cloudinary_storage.storage.MediaCloudinaryStorage', # Revertimos al original.
        },
        "staticfiles": {
             "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
             # "BACKEND": "cloudinary_storage.storage.StaticHashedCloudinaryStorage", # If using Cloudinary for static
        },
    }
    MEDIA_URL = '/media/'
    MEDIA_ROOT = ''

else:
    # --- Configuración Local (Desarrollo) ---
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# Ensure Whitenoise middleware is present if used for staticfiles
if STORAGES.get("staticfiles", {}).get("BACKEND") == 'whitenoise.storage.CompressedManifestStaticFilesStorage':
    pass # Middleware is already added above

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'