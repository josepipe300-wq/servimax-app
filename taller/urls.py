# taller/urls.py
from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.home, name='home'),
    path('ingresar-vehiculo/', views.ingresar_vehiculo, name='ingresar_vehiculo'),
    path('anadir-gasto/', views.anadir_gasto, name='anadir_gasto'),
    path('registrar-ingreso/', views.registrar_ingreso, name='registrar_ingreso'),
    path('stock-inicial/', views.stock_inicial_consumible, name='stock_inicial_consumible'),

    # --- PRESUPUESTOS ---
    path('presupuesto/crear/', views.crear_presupuesto, name='crear_presupuesto'),
    path('presupuestos/', views.lista_presupuestos, name='lista_presupuestos'),
    path('presupuesto/<int:presupuesto_id>/', views.detalle_presupuesto, name='detalle_presupuesto'),
    path('presupuesto/<int:presupuesto_id>/pdf/', views.ver_presupuesto_pdf, name='ver_presupuesto_pdf'),
    path('presupuesto/<int:presupuesto_id>/editar/', views.editar_presupuesto, name='editar_presupuesto'),

    # --- ÓRDENES ---
    path('ordenes/', views.lista_ordenes, name='lista_ordenes'),
    path('orden/<int:orden_id>/', views.detalle_orden, name='detalle_orden'),
    path('historial-ordenes/', views.historial_ordenes, name='historial_ordenes'),

    # --- FACTURACIÓN ---
    path('orden/<int:orden_id>/facturar/', views.generar_factura, name='generar_factura'),
    path('factura/<int:factura_id>/pdf/', views.ver_factura_pdf, name='ver_factura_pdf'),
    
    # NUEVA RUTA: Enlace público y seguro para enviar por WhatsApp
    path('factura/publica/<str:signed_id>/', views.ver_factura_publica, name='ver_factura_publica'),
    
    path('factura/<int:factura_id>/editar/', views.editar_factura, name='editar_factura'),

    # --- MOVIMIENTOS ---
    path('historial/', views.historial_movimientos, name='historial_movimientos'),
    path('movimiento/editar/<str:tipo>/<int:movimiento_id>/', views.editar_movimiento, name='editar_movimiento'),

    # --- CONTABILIDAD / INFORMES ---
    path('contabilidad/', views.contabilidad, name='contabilidad'),
    path('informe-gastos/', views.informe_gastos, name='informe_gastos'),
    path('informe-ingresos/', views.informe_ingresos, name='informe_ingresos'),
    path('informe-rentabilidad/', views.informe_rentabilidad, name='informe_rentabilidad'),
    path('informe-rentabilidad/orden/<int:orden_id>/', views.detalle_ganancia_orden, name='detalle_ganancia_orden'),
    path('cuentas-por-cobrar/', views.cuentas_por_cobrar, name='cuentas_por_cobrar'),
    path('informe-gastos/desglose/sueldos/<str:empleado_nombre>/', views.informe_gastos_desglose, {'categoria': 'Sueldos'}, name='desglose_sueldos_empleado'),
    path('informe-gastos/desglose/<path:categoria>/', views.informe_gastos_desglose, name='informe_gastos_desglose'),
    path('informe-ingresos/desglose/<path:categoria>/', views.informe_ingresos_desglose, name='informe_ingresos_desglose'),
    
    # --- TARJETA / CUENTAS BANCARIAS ---
    path('informe-tarjeta/', views.informe_tarjeta, name='informe_tarjeta'),
    path('informe-tarjeta/historial/<str:cuenta_nombre>/', views.historial_cuenta, name='historial_cuenta'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)