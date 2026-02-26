# taller/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # --- PANTALLA PRINCIPAL ---
    path('', views.home, name='home'),

    # --- ENTRADA DE DATOS ---
    path('ingresar-vehiculo/', views.ingresar_vehiculo, name='ingresar_vehiculo'),
    path('anadir-gasto/', views.anadir_gasto, name='anadir_gasto'),
    path('registrar-ingreso/', views.registrar_ingreso, name='registrar_ingreso'),
    path('stock-inicial/', views.stock_inicial_consumible, name='stock_inicial_consumible'),

    # --- ÓRDENES DE REPARACIÓN ---
    path('ordenes/', views.lista_ordenes, name='lista_ordenes'),
    path('ordenes/historial/', views.historial_ordenes, name='historial_ordenes'),
    path('ordenes/<int:orden_id>/', views.detalle_orden, name='detalle_orden'),
    
    # --- PRESUPUESTOS ---
    path('presupuestos/', views.lista_presupuestos, name='lista_presupuestos'),
    path('presupuestos/crear/', views.crear_presupuesto, name='crear_presupuesto'),
    path('presupuestos/<int:presupuesto_id>/', views.detalle_presupuesto, name='detalle_presupuesto'),
    path('presupuestos/<int:presupuesto_id>/editar/', views.editar_presupuesto, name='editar_presupuesto'),
    path('presupuestos/<int:presupuesto_id>/pdf/', views.ver_presupuesto_pdf, name='ver_presupuesto_pdf'),

    # --- FACTURACIÓN Y RECIBOS ---
    path('ordenes/<int:orden_id>/generar-factura/', views.generar_factura, name='generar_factura'),
    path('facturas/<int:factura_id>/pdf/', views.ver_factura_pdf, name='ver_factura_pdf'),
    path('facturas/publica/<str:signed_id>/', views.ver_factura_publica, name='ver_factura_publica'), # Enlace seguro WhatsApp
    path('facturas/<int:factura_id>/editar/', views.editar_factura, name='editar_factura'),

    # --- CONTABILIDAD Y BANCOS ---
    path('contabilidad/', views.contabilidad, name='contabilidad'),
    path('contabilidad/pendientes/', views.cuentas_por_cobrar, name='cuentas_por_cobrar'),
    
    # --- NUEVO: GESTIÓN DE TARJETAS Y CUENTAS ---
    path('informe-tarjeta/', views.informe_tarjeta, name='informe_tarjeta'),
    path('tarjetas/registrar-pago/', views.registrar_pago_tarjeta, name='registrar_pago_tarjeta'),
    path('tarjetas/cierre/<int:cierre_id>/eliminar/', views.eliminar_cierre_tarjeta, name='eliminar_cierre_tarjeta'),
    path('cuenta/<str:cuenta_nombre>/', views.historial_cuenta, name='historial_cuenta'),

    # --- HISTORIAL DE MOVIMIENTOS ---
    path('movimientos/', views.historial_movimientos, name='historial_movimientos'),
    path('movimientos/editar/<str:tipo>/<int:movimiento_id>/', views.editar_movimiento, name='editar_movimiento'),

    # --- INFORMES Y DESGLOSES ---
    path('informes/rentabilidad/', views.informe_rentabilidad, name='informe_rentabilidad'),
    path('ordenes/<int:orden_id>/rentabilidad/', views.detalle_ganancia_orden, name='detalle_ganancia_orden'),
    
    path('informes/gastos/', views.informe_gastos, name='informe_gastos'),
    path('informes/gastos/<str:categoria>/', views.informe_gastos_desglose, name='informe_gastos_desglose'),
    path('informes/gastos/<str:categoria>/<str:empleado_nombre>/', views.informe_gastos_desglose, name='informe_gastos_desglose_empleado'),
    
    path('informes/ingresos/', views.informe_ingresos, name='informe_ingresos'),
    path('informes/ingresos/<str:categoria>/', views.informe_ingresos_desglose, name='informe_ingresos_desglose'),
]