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
    # 'cloudinary_storage', # App name is just 'cloudinary'
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'cloudinary', # Correct app name
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
                'django.contrib.messages.messages',
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

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'taller/static'),]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# --- CONFIGURACIÓN DE ALMACENAMIENTO (Cloudinary o Local) ---

CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')

if CLOUDINARY_URL:
    # --- Configuración para Cloudinary (Producción/Render) ---
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
    # Opcional: Descomentar si quieres usar Cloudinary para archivos estáticos también
    # STATICFILES_STORAGE = 'cloudinary_storage.storage.StaticHashedCloudinaryStorage'

    # **AÑADIR ESTO:** Definir explícitamente el backend 'default' en STORAGES
    STORAGES = {
        "default": {
            "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
        },
        # Mantener Whitenoise para estáticos si NO se usa Cloudinary para ellos
        "staticfiles": {
             "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
             # Descomentar la siguiente línea si usas Cloudinary para estáticos
             # "BACKEND": "cloudinary_storage.storage.StaticHashedCloudinaryStorage",
        },
    }
    # MEDIA_URL y MEDIA_ROOT no son necesarios explícitamente aquí, Cloudinary los maneja

else:
    # --- Configuración Local (Desarrollo) ---
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage' # Usar el sistema de archivos por defecto

    # **AÑADIR ESTO:** Definir explícitamente los backends en STORAGES para local
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage", # O Django por defecto si no usas whitenoise localmente
            # "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'