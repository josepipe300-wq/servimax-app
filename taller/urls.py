# taller/urls.py
from django.urls import path # Asegúrate de importar path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('ingresar-vehiculo/', views.ingresar_vehiculo, name='ingresar_vehiculo'),
    path('anadir-gasto/', views.anadir_gasto, name='anadir_gasto'),
    path('registrar-ingreso/', views.registrar_ingreso, name='registrar_ingreso'),
    path('stock-inicial/', views.stock_inicial_consumible, name='stock_inicial_consumible'),

    path('ordenes/', views.lista_ordenes, name='lista_ordenes'),
    path('orden/<int:orden_id>/', views.detalle_orden, name='detalle_orden'),
    path('historial-ordenes/', views.historial_ordenes, name='historial_ordenes'),

    path('orden/<int:orden_id>/facturar/', views.generar_factura, name='generar_factura'),
    path('factura/<int:factura_id>/pdf/', views.ver_factura_pdf, name='ver_factura_pdf'),
    path('factura/<int:factura_id>/editar/', views.editar_factura, name='editar_factura'),

    path('historial/', views.historial_movimientos, name='historial_movimientos'),
    path('movimiento/editar/<str:tipo>/<int:movimiento_id>/', views.editar_movimiento, name='editar_movimiento'),

    path('contabilidad/', views.contabilidad, name='contabilidad'),
    path('informe-gastos/', views.informe_gastos, name='informe_gastos'),
    path('informe-ingresos/', views.informe_ingresos, name='informe_ingresos'),
    path('informe-rentabilidad/', views.informe_rentabilidad, name='informe_rentabilidad'),
    path('informe-rentabilidad/orden/<int:orden_id>/', views.detalle_ganancia_orden, name='detalle_ganancia_orden'),
    path('cuentas-por-cobrar/', views.cuentas_por_cobrar, name='cuentas_por_cobrar'),

    # --- Rutas para Desglose de Gastos ---
    # La ruta de sueldos no necesita cambio porque empleado_nombre no debería tener '/'
    path('informe-gastos/desglose/sueldos/<str:empleado_nombre>/', views.informe_gastos_desglose, {'categoria': 'Sueldos'}, name='desglose_sueldos_empleado'),
    # --- MODIFICACIÓN AQUÍ: Cambiar <str:categoria> por <path:categoria> ---
    path('informe-gastos/desglose/<path:categoria>/', views.informe_gastos_desglose, name='informe_gastos_desglose'),

    # --- RUTA PARA DESGLOSE DE INGRESOS (También se beneficia del cambio si alguna categoría tuviera '/') ---
    path('informe-ingresos/desglose/<path:categoria>/', views.informe_ingresos_desglose, name='informe_ingresos_desglose'),

    # --- NUEVA RUTA PARA INFORME DE TARJETA ---
    path('informe-tarjeta/', views.informe_tarjeta, name='informe_tarjeta'),
]