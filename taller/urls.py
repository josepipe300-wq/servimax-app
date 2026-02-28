# taller/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Funciones principales
    path('', views.home, name='home'),
    path('ingresar-vehiculo/', views.ingresar_vehiculo, name='ingresar_vehiculo'),
    path('anadir-gasto/', views.anadir_gasto, name='anadir_gasto'),
    path('registrar-ingreso/', views.registrar_ingreso, name='registrar_ingreso'),
    path('stock-inicial/', views.stock_inicial_consumible, name='stock_inicial_consumible'),

    # Presupuestos
    path('presupuestos/crear/', views.crear_presupuesto, name='crear_presupuesto'),
    path('presupuestos/', views.lista_presupuestos, name='lista_presupuestos'),
    path('presupuesto/<int:presupuesto_id>/', views.detalle_presupuesto, name='detalle_presupuesto'),
    path('presupuesto/<int:presupuesto_id>/editar/', views.editar_presupuesto, name='editar_presupuesto'),
    path('presupuesto/<int:presupuesto_id>/pdf/', views.ver_presupuesto_pdf, name='ver_presupuesto_pdf'),

    # Órdenes
    path('ordenes/', views.lista_ordenes, name='lista_ordenes'),
    path('orden/<int:orden_id>/', views.detalle_orden, name='detalle_orden'),
    path('historial-ordenes/', views.historial_ordenes, name='historial_ordenes'),
    
    # Facturas
    path('orden/<int:orden_id>/factura/generar/', views.generar_factura, name='generar_factura'),
    path('factura/<int:factura_id>/pdf/', views.ver_factura_pdf, name='ver_factura_pdf'),
    path('factura/publica/<str:signed_id>/', views.ver_factura_publica, name='ver_factura_publica'),
    path('factura/<int:factura_id>/editar/', views.editar_factura, name='editar_factura'),

    # Informes y Contabilidad
    path('historial-movimientos/', views.historial_movimientos, name='historial_movimientos'),
    path('editar-movimiento/<str:tipo>/<int:movimiento_id>/', views.editar_movimiento, name='editar_movimiento'),
    path('informes/rentabilidad/', views.informe_rentabilidad, name='informe_rentabilidad'),
    path('orden/<int:orden_id>/ganancia/', views.detalle_ganancia_orden, name='detalle_ganancia_orden'),
    
    # --- LA SOLUCIÓN AL ERROR (Cambio a <path:categoria> para que acepte barras) ---
    path('informes/gastos/', views.informe_gastos, name='informe_gastos'),
    path('informes/gastos/cat/<path:categoria>/', views.informe_gastos_desglose, name='informe_gastos_desglose'),
    path('informes/gastos/cat/<path:categoria>/emp/<str:empleado_nombre>/', views.informe_gastos_desglose, name='informe_gastos_desglose_empleado'),
    path('informes/ingresos/', views.informe_ingresos, name='informe_ingresos'),
    path('informes/ingresos/cat/<path:categoria>/', views.informe_ingresos_desglose, name='informe_ingresos_desglose'),

    path('contabilidad/', views.contabilidad, name='contabilidad'),
    path('cuentas-por-cobrar/', views.cuentas_por_cobrar, name='cuentas_por_cobrar'),
    path('informe-tarjeta/', views.informe_tarjeta, name='informe_tarjeta'),
    path('registrar-pago-tarjeta/', views.registrar_pago_tarjeta, name='registrar_pago_tarjeta'),
    path('eliminar-cierre-tarjeta/<int:cierre_id>/', views.eliminar_cierre_tarjeta, name='eliminar_cierre_tarjeta'),
    path('historial-cuenta/<str:cuenta_nombre>/', views.historial_cuenta, name='historial_cuenta'),

    # --- TABLÓN DE ANUNCIOS E HISTORIAL ---
    path('agregar-nota/', views.agregar_nota, name='agregar_nota'),
    path('completar-nota/<int:nota_id>/', views.completar_nota, name='completar_nota'),
    path('historial-notas/', views.historial_notas, name='historial_notas'),
]