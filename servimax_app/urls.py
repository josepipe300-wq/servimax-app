# servimax_app/urls.py

from django.contrib import admin
from django.urls import path, include # Asegúrate de que 'include' esté aquí
from django.conf import settings # Necesario para servir archivos media en desarrollo
from django.conf.urls.static import static # Necesario para servir archivos media en desarrollo

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('taller.urls')), # Esta línea ya la tenías
    # --- LÍNEA AÑADIDA PARA AUTENTICACIÓN ---
    path('accounts/', include('django.contrib.auth.urls')), # URLs de login, logout, etc.
    # --- FIN LÍNEA AÑADIDA ---
]

# --- Añadir esto al final si quieres servir archivos media localmente (Cloudinary no lo necesita) ---
# Esto es útil para desarrollo local si NO estás usando Cloudinary (si CLOUDINARY_URL no está definida)
if settings.DEBUG and not settings.CLOUDINARY_URL:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)