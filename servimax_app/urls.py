# servimax_app/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from taller import views  # <--- AQUÍ ESTÁ LA SOLUCIÓN MÁGICA 🪄

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('taller.urls')), 
    path('accounts/', include('django.contrib.auth.urls')), 
    path('taller/alternar/', views.alternar_estado_taller, name='alternar_taller'), # Ahora sí funcionará
]

# --- Añadir esto al final si quieres servir archivos media localmente (Cloudinary no lo necesita) ---
# Esto es útil para desarrollo local si NO estás usando Cloudinary (si CLOUDINARY_URL no está definida)
if settings.DEBUG and not hasattr(settings, 'CLOUDINARY_URL'):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)