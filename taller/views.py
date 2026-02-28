# taller/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import (
    Ingreso, Gasto, Cliente, Vehiculo, OrdenDeReparacion, Empleado,
    TipoConsumible, CompraConsumible, Factura, LineaFactura, FotoVehiculo,
    Presupuesto, LineaPresupuesto, UsoConsumible, AjusteStockConsumible,
    CierreTarjeta, NotaTablon, NotaInternaOrden
)
from django.db.models import Sum, F, Q
from django.db import transaction
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from django.http import HttpResponse, HttpResponseForbidden
from django.template.loader import get_template
from xhtml2pdf import pisa
import os
from django.conf import settings
from django.utils import timezone
import json
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from functools import wraps

# --- NUEVOS IMPORTS PARA WHATSAPP Y SEGURIDAD ---
from django.core.signing import Signer, BadSignature
from urllib.parse import quote

# ==============================================================
# --- CANDADO DE SEGURIDAD PARA EL MODO LECTURA (PADRE) ---
# ==============================================================
def bloquear_lectura(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.user.groups.filter(name='Solo Ver').exists():
            return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Tu cuenta está en 'Modo Lectura'. No tienes permiso para añadir o modificar datos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")
        return view_func(request, *args, **kwargs)
    return _wrapped_view

# --- FUNCIÓN AUXILIAR PARA LOS FILTROS DE FECHA ---
def get_anos_y_meses_con_datos():
    fechas_gastos = Gasto.objects.values_list('fecha', flat=True)
    fechas_ingresos = Ingreso.objects.values_list('fecha', flat=True)
    fechas_facturas = Factura.objects.values_list('fecha_emision', flat=True)
    fechas_presupuestos = Presupuesto.objects.values_list('fecha_creacion', flat=True)

    fechas_presupuestos_date = [dt.date() for dt in fechas_presupuestos if dt]

    fechas_combinadas = set(fechas_gastos) | set(fechas_ingresos) | set(fechas_facturas) | set(fechas_presupuestos_date)
    fechas_combinadas = {f for f in fechas_combinadas if f is not None}
    fechas = sorted(list(fechas_combinadas), reverse=True)

    anos_y_meses = {}
    for fecha in fechas:
        ano = fecha.year
        mes = fecha.month
        if ano not in anos_y_meses:
            anos_y_meses[ano] = []
        if mes not in anos_y_meses[ano]:
            anos_y_meses[ano].append(mes)

    for ano in anos_y_meses:
        anos_y_meses[ano].sort()

    anos_ordenados = sorted(anos_y_meses.keys(), reverse=True)
    anos_y_meses_ordenado = {ano: anos_y_meses[ano] for ano in anos_ordenados}

    return anos_y_meses_ordenado

# --- FUNCIÓN AUXILIAR PARA OBTENER ÓRDENES RELEVANTES ---
def obtener_ordenes_relevantes():
    ordenes_no_entregadas = OrdenDeReparacion.objects.exclude(estado='Entregado')
    ordenes_entregadas_con_saldo = []
    ordenes_entregadas = OrdenDeReparacion.objects.filter(estado='Entregado').select_related('factura').prefetch_related('ingreso_set')

    for orden in ordenes_entregadas:
        try:
            factura = orden.factura
            abonos = sum(ing.importe for ing in orden.ingreso_set.all()) if orden.ingreso_set.exists() else Decimal('0.00')
            pendiente = factura.total_final - abonos
            if pendiente > Decimal('0.01'):
                ordenes_entregadas_con_saldo.append(orden.id)
        except Factura.DoesNotExist:
            ordenes_entregadas_con_saldo.append(orden.id)
        except AttributeError:
             ordenes_entregadas_con_saldo.append(orden.id)

    ids_relevantes = list(ordenes_no_entregadas.values_list('id', flat=True)) + ordenes_entregadas_con_saldo
    return OrdenDeReparacion.objects.filter(id__in=list(set(ids_relevantes))).select_related('vehiculo', 'cliente')

# --- FUNCIÓN AUXILIAR PARA GENERAR PDF DE FACTURA ---
def generar_pdf_response(factura):
    cliente = factura.orden.cliente
    vehiculo = factura.orden.vehiculo
    abonos = factura.orden.ingreso_set.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    pendiente = factura.total_final - abonos
    lineas = factura.lineas.all()
    
    orden_tipos = ['Mano de Obra', 'Repuesto', 'Consumible', 'Externo']
    lineas_agrupadas = {tipo: [] for tipo in orden_tipos}
    otros_tipos = []
    
    for linea in lineas:
        if linea.tipo in lineas_agrupadas:
            lineas_agrupadas[linea.tipo].append(linea)
        else:
            otros_tipos.append(linea)
            
    lineas_ordenadas_agrupadas = []
    for tipo in orden_tipos:
        lineas_ordenadas_agrupadas.extend(lineas_agrupadas[tipo])
    lineas_ordenadas_agrupadas.extend(otros_tipos)
    
    context = { 
        'factura': factura, 
        'cliente': cliente, 
        'vehiculo': vehiculo, 
        'lineas': lineas_ordenadas_agrupadas, 
        'abonos': abonos, 
        'pendiente': pendiente, 
        'STATIC_URL': settings.STATIC_URL, 
        'logo_path': os.path.join(settings.BASE_DIR, 'taller', 'static', 'taller', 'images', 'logo.jpg') 
    }
    
    template_path = 'taller/plantilla_factura.html'
    template = get_template(template_path)
    html = template.render(context)
    
    response = HttpResponse(content_type='application/pdf')
    matricula_filename = factura.orden.vehiculo.matricula if factura.orden.vehiculo else 'SIN_MATRICULA'
    response['Content-Disposition'] = f'inline; filename="fact_{matricula_filename}_{factura.id}.pdf"'
    
    def link_callback(uri, rel):
        logo_uri_abs = context.get('logo_path')
        if logo_uri_abs: logo_uri_abs = logo_uri_abs.replace("\\", "/")
        if uri == logo_uri_abs: return logo_uri_abs
        if uri.startswith(settings.STATIC_URL):
            path = uri.replace(settings.STATIC_URL, "", 1)
            for static_dir in settings.STATICFILES_DIRS:
                file_path = os.path.join(static_dir, path)
                if os.path.exists(file_path): return file_path
            if hasattr(settings, 'STATIC_ROOT') and settings.STATIC_ROOT:
                 file_path = os.path.join(settings.STATIC_ROOT, path)
                 if os.path.exists(file_path): return file_path
        if uri.startswith("http://") or uri.startswith("https://"): return uri
        return None

    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err:
        return HttpResponse('Error al generar PDF: <pre>' + html + '</pre>')
    return response


# --- VISTA HOME ---
@login_required
def home(request):
    hoy = timezone.now()

    ano_seleccionado_str = request.GET.get('ano')
    mes_seleccionado_str = request.GET.get('mes')

    if ano_seleccionado_str:
        try: ano_actual = int(ano_seleccionado_str)
        except (ValueError, TypeError): ano_actual = hoy.year
    else: ano_actual = hoy.year

    if mes_seleccionado_str:
        try:
            mes_actual = int(mes_seleccionado_str)
            if not 1 <= mes_actual <= 12: mes_actual = hoy.month
        except (ValueError, TypeError): mes_actual = hoy.month
    else: mes_actual = hoy.month
    
    # Totales del Mes seleccionado (Globales)
    ingresos_mes = Ingreso.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    gastos_mes = Gasto.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    
    total_ingresos = ingresos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos = gastos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

    # Balances de cuentas
    ing_efectivo = Ingreso.objects.filter(metodo_pago='EFECTIVO').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gas_efectivo = Gasto.objects.filter(metodo_pago='EFECTIVO').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_efectivo = ing_efectivo - gas_efectivo
    
    ing_erika = Ingreso.objects.filter(metodo_pago='CUENTA_ERIKA').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gas_erika = Gasto.objects.filter(metodo_pago='CUENTA_ERIKA').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_erika = ing_erika - gas_erika

    ing_taller = Ingreso.objects.filter(metodo_pago='CUENTA_TALLER').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gas_taller = Gasto.objects.filter(metodo_pago='CUENTA_TALLER').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_taller = ing_taller - gas_taller
    
    def calcular_tarjeta(tag, limite):
        gastos = Gasto.objects.filter(metodo_pago=tag).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        abonos = Ingreso.objects.filter(metodo_pago=tag).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        dispuesto = gastos - abonos
        return {'limite': limite, 'dispuesto': dispuesto, 'disponible': limite - dispuesto}

    tarjeta_1 = calcular_tarjeta('TARJETA_1', Decimal('2000.00'))
    tarjeta_2 = calcular_tarjeta('TARJETA_2', Decimal('1000.00'))

    ultimos_gastos = Gasto.objects.order_by('-id')[:5]
    ultimos_ingresos = Ingreso.objects.order_by('-id')[:5]
    movimientos_combinados = sorted(
        list(ultimos_gastos) + list(ultimos_ingresos),
        key=lambda mov: mov.fecha if hasattr(mov, 'fecha') else timezone.now().date(),
        reverse=True
    )
    movimientos_recientes = movimientos_combinados[:5]

    tipos_consumible = TipoConsumible.objects.all()
    alertas_stock = []
    for tipo in tipos_consumible:
        total_comprado = CompraConsumible.objects.filter(tipo=tipo).aggregate(total=Sum('cantidad'))['total'] or Decimal('0.00')
        total_usado_ordenes = UsoConsumible.objects.filter(tipo=tipo).aggregate(total=Sum('cantidad_usada'))['total'] or Decimal('0.00')
        total_ajustado = AjusteStockConsumible.objects.filter(tipo=tipo).aggregate(total=Sum('cantidad_ajustada'))['total'] or Decimal('0.00')
        stock_actual = total_comprado - total_usado_ordenes + total_ajustado

        if tipo.nivel_minimo_stock is not None and stock_actual <= tipo.nivel_minimo_stock:
            alertas_stock.append({
                'nombre': tipo.nombre, 'stock_actual': stock_actual,
                'unidad': tipo.unidad_medida, 'minimo': tipo.nivel_minimo_stock
            })
    
    is_read_only_user = request.user.groups.filter(name='Solo Ver').exists()
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)

    # --- Cargar las notas del tablón (SOLO LAS NO COMPLETADAS) ---
    notas_tablon = NotaTablon.objects.filter(completada=False).order_by('-fecha_creacion')[:20]

    context = {
        'total_ingresos': total_ingresos,
        'total_gastos': total_gastos,
        'balance_efectivo': balance_efectivo,
        'balance_erika': balance_erika,
        'balance_taller': balance_taller,
        'tarjeta_1': tarjeta_1,
        'tarjeta_2': tarjeta_2,
        'movimientos_recientes': movimientos_recientes,
        'alertas_stock': alertas_stock,
        'is_read_only_user': is_read_only_user,
        'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_actual,
        'mes_seleccionado': mes_actual,
        'meses_del_ano': range(1, 13),
        'notas_tablon': notas_tablon, # Pasamos las notas a la pantalla
    }
    return render(request, 'taller/home.html', context)


# --- REGISTRAR PAGO Y AJUSTAR INTERESES ---
@login_required
@bloquear_lectura # CANDADO
def registrar_pago_tarjeta(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Solo el administrador puede registrar pagos de tarjeta.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if request.method == 'POST':
        tarjeta = request.POST.get('tarjeta')
        importe_pago = Decimal(request.POST.get('importe_pago', '0'))
        saldo_real_banco = Decimal(request.POST.get('saldo_real_banco', '0'))
        
        gastos = Gasto.objects.filter(metodo_pago=tarjeta).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        pagos = Ingreso.objects.filter(metodo_pago=tarjeta).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        deuda_app_antes = gastos - pagos
        deuda_app_despues = deuda_app_antes - importe_pago
        intereses = saldo_real_banco - deuda_app_despues
        
        with transaction.atomic():
            Gasto.objects.create(fecha=timezone.now().date(), categoria='Otros', importe=importe_pago, descripcion=f"PAGO CUOTA MENSUAL {tarjeta}", metodo_pago='CUENTA_TALLER')
            Ingreso.objects.create(fecha=timezone.now().date(), categoria='ABONO_TARJETA', importe=importe_pago, descripcion="ABONO RECIBIDO DESDE CUENTA TALLER", metodo_pago=tarjeta)
            if intereses > 0:
                Gasto.objects.create(fecha=timezone.now().date(), categoria='COMISIONES_INTERESES', importe=intereses, descripcion="AJUSTE AUTOMÁTICO DE INTERESES Y COMISIONES", metodo_pago=tarjeta)
            CierreTarjeta.objects.create(tarjeta=tarjeta, pago_cuota=importe_pago, saldo_deuda_banco=saldo_real_banco, intereses_calculados=intereses if intereses > 0 else Decimal('0.00'))

        return redirect('informe_tarjeta')
    return render(request, 'taller/registrar_pago_tarjeta.html')

# --- ELIMINAR CIERRE DE TARJETA ---
@login_required
@bloquear_lectura # CANDADO
def eliminar_cierre_tarjeta(request, cierre_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Acceso Denegado")

    if request.method == 'POST':
        cierre = get_object_or_404(CierreTarjeta, id=cierre_id)
        with transaction.atomic():
            Gasto.objects.filter(fecha=cierre.fecha_cierre, metodo_pago='CUENTA_TALLER', importe=cierre.pago_cuota, descripcion__icontains=f"PAGO CUOTA MENSUAL {cierre.tarjeta}").delete()
            Ingreso.objects.filter(fecha=cierre.fecha_cierre, metodo_pago=cierre.tarjeta, importe=cierre.pago_cuota, categoria='ABONO_TARJETA').delete()
            if cierre.intereses_calculados > 0:
                Gasto.objects.filter(fecha=cierre.fecha_cierre, metodo_pago=cierre.tarjeta, importe=cierre.intereses_calculados, categoria='COMISIONES_INTERESES').delete()
            cierre.delete()
    return redirect('informe_tarjeta')


# --- INGRESAR VEHÍCULO ---
@login_required
@bloquear_lectura # CANDADO
def ingresar_vehiculo(request):
    if not (request.user.is_superuser or request.user.has_perm('taller.add_ordendereparacion')):
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para ingresar vehículos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if request.method == 'POST':
        nombre_cliente = request.POST['cliente_nombre'].upper()
        telefono_cliente = request.POST['cliente_telefono']
        tipo_documento = request.POST.get('cliente_tipo_documento', 'DNI')
        documento_fiscal = request.POST.get('cliente_documento_fiscal', '')
        direccion_fiscal = request.POST.get('cliente_direccion_fiscal', '')
        codigo_postal_fiscal = request.POST.get('cliente_codigo_postal_fiscal', '')
        ciudad_fiscal = request.POST.get('cliente_ciudad_fiscal', '')
        provincia_fiscal = request.POST.get('cliente_provincia_fiscal', '')
        matricula_vehiculo = request.POST['vehiculo_matricula'].upper()
        marca_vehiculo = request.POST['vehiculo_marca'].upper()
        modelo_vehiculo = request.POST['vehiculo_modelo'].upper()
        kilometraje_vehiculo_str = request.POST.get('vehiculo_kilometraje')
        kilometraje_vehiculo = int(kilometraje_vehiculo_str) if kilometraje_vehiculo_str else 0
        problema_reportado = request.POST['problema'].upper()

        with transaction.atomic():
            cliente, created = Cliente.objects.get_or_create(telefono=telefono_cliente, defaults={'nombre': nombre_cliente})
            cliente.nombre = nombre_cliente; cliente.tipo_documento = tipo_documento; cliente.documento_fiscal = documento_fiscal
            cliente.direccion_fiscal = direccion_fiscal; cliente.codigo_postal_fiscal = codigo_postal_fiscal
            cliente.ciudad_fiscal = ciudad_fiscal; cliente.provincia_fiscal = provincia_fiscal
            cliente.save()

            vehiculo, v_created = Vehiculo.objects.get_or_create(matricula=matricula_vehiculo, defaults={'marca': marca_vehiculo, 'modelo': modelo_vehiculo, 'kilometraje': kilometraje_vehiculo, 'cliente': cliente})
            if not v_created:
                if kilometraje_vehiculo > vehiculo.kilometraje: vehiculo.kilometraje = kilometraje_vehiculo
                if vehiculo.cliente != cliente: vehiculo.cliente = cliente
                vehiculo.save()

            presupuesto_id = request.POST.get('presupuesto_asociado')
            presupuesto = None
            if presupuesto_id:
                try:
                    presupuesto = Presupuesto.objects.get(id=presupuesto_id, estado='Aceptado')
                    if v_created and presupuesto.marca_nueva and not vehiculo.marca:
                         vehiculo.marca = presupuesto.marca_nueva
                         vehiculo.modelo = presupuesto.modelo_nuevo
                         vehiculo.save()
                except Presupuesto.DoesNotExist: pass

            nueva_orden = OrdenDeReparacion.objects.create(cliente=cliente, vehiculo=vehiculo, problema=problema_reportado, presupuesto_origen=presupuesto)
            if presupuesto:
                presupuesto.estado = 'Convertido'; presupuesto.save()

            descripciones = ['Frontal', 'Trasera', 'Lateral Izquierdo', 'Lateral Derecho', 'Cuadro/Km']
            for i in range(1, 6):
                foto_campo = f'foto{i}'
                if foto_campo in request.FILES:
                    FotoVehiculo.objects.create(orden=nueva_orden, imagen=request.FILES[foto_campo], descripcion=descripciones[i-1])

        return redirect('detalle_orden', orden_id=nueva_orden.id)

    presupuestos_disponibles_qs = Presupuesto.objects.filter(estado='Aceptado').select_related('cliente', 'vehiculo').order_by('-fecha_creacion')
    presupuestos_con_datos_fiscales = []
    for p in presupuestos_disponibles_qs:
        presupuestos_con_datos_fiscales.append({
            'presupuesto': p,
            'cliente_data': {
                'tipo_documento': p.cliente.tipo_documento or 'DNI', 'documento_fiscal': p.cliente.documento_fiscal or '',
                'direccion_fiscal': p.cliente.direccion_fiscal or '', 'codigo_postal_fiscal': p.cliente.codigo_postal_fiscal or '',
                'ciudad_fiscal': p.cliente.ciudad_fiscal or '', 'provincia_fiscal': p.cliente.provincia_fiscal or 'TARRAGONA',
            }
        })
    context = { 'presupuestos_disponibles_data': presupuestos_con_datos_fiscales }
    return render(request, 'taller/ingresar_vehiculo.html', context)


# --- AÑADIR GASTO ---
@login_required
@bloquear_lectura # CANDADO
def anadir_gasto(request):
    if not (request.user.is_superuser or request.user.has_perm('taller.add_gasto') or request.user.has_perm('taller.add_compraconsumible')):
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para acceder a la gestión de gastos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if request.method == 'POST':
        categoria = request.POST.get('categoria', '')
        metodo_pago = request.POST.get('metodo_pago', 'EFECTIVO')
        pagado_con_tarjeta_bool = (metodo_pago != 'EFECTIVO')

        if categoria == 'Compra de Consumibles':
            tipo_id = request.POST.get('tipo_consumible')
            fecha_compra_str = request.POST.get('fecha_compra') or request.POST.get('fecha_gasto')
            cantidad_str = request.POST.get('cantidad') or '1' 
            coste_total_str = request.POST.get('coste_total') or request.POST.get('importe')

            if not tipo_id or not coste_total_str:
                 return redirect('anadir_gasto')
                 
            try:
                with transaction.atomic():
                    cantidad = Decimal(cantidad_str)
                    coste_total = Decimal(coste_total_str)
                    if cantidad <= 0 or coste_total < 0: return redirect('anadir_gasto')
                    tipo_consumible = get_object_or_404(TipoConsumible, id=tipo_id)
                    try: fecha_compra = datetime.strptime(fecha_compra_str, '%Y-%m-%d').date() if fecha_compra_str else timezone.now().date()
                    except ValueError: fecha_compra = timezone.now().date()

                    CompraConsumible.objects.create(tipo=tipo_consumible, fecha_compra=fecha_compra, cantidad=cantidad, coste_total=coste_total)
                    Gasto.objects.create(fecha=fecha_compra, categoria=categoria, importe=coste_total, descripcion=f"COMPRA DE {cantidad} {tipo_consumible.unidad_medida} DE {tipo_consumible.nombre}".upper(), pagado_con_tarjeta=pagado_con_tarjeta_bool, metodo_pago=metodo_pago)
            except (ValueError, TypeError, Decimal.InvalidOperation): return redirect('anadir_gasto')

        else:
            importe_str = request.POST.get('importe')
            descripcion = request.POST.get('descripcion', '')
            fecha_gasto_str = request.POST.get('fecha_gasto')
            try: fecha_gasto = datetime.strptime(fecha_gasto_str, '%Y-%m-%d').date() if fecha_gasto_str else timezone.now().date()
            except ValueError: fecha_gasto = timezone.now().date()
            try:
                importe = Decimal(importe_str) if importe_str else None
                if importe is not None and importe < 0: importe = None
            except (ValueError, TypeError, Decimal.InvalidOperation): importe = None

            gasto = Gasto(fecha=fecha_gasto, categoria=categoria, importe=importe, descripcion=descripcion.upper(), pagado_con_tarjeta=pagado_con_tarjeta_bool, metodo_pago=metodo_pago)

            if categoria in ['Repuestos', 'Otros']:
                orden_id = request.POST.get('orden')
                if orden_id:
                    try:
                        orden = OrdenDeReparacion.objects.get(id=orden_id)
                        gasto.orden = orden 
                        if orden.estado in ['Recibido', 'En Diagnostico']:
                            orden.estado = 'En Reparacion'
                            orden.save()
                    except OrdenDeReparacion.DoesNotExist: pass

            if categoria == 'Sueldos':
                empleado_id = request.POST.get('empleado')
                if empleado_id:
                     try: gasto.empleado = Empleado.objects.get(id=empleado_id)
                     except Empleado.DoesNotExist: pass
            gasto.save()

        return redirect('home')

    ordenes_activas = OrdenDeReparacion.objects.exclude(estado='Entregado').select_related('vehiculo', 'cliente').order_by('-id')
    empleados = Empleado.objects.all()
    tipos_consumible = TipoConsumible.objects.all()
    categorias_gasto_choices = [choice for choice in Gasto.CATEGORIA_CHOICES if choice[0] != 'Compra de Consumibles']
    metodos_pago = Gasto.METODO_PAGO_CHOICES 
    
    context = {
        'ordenes_activas': ordenes_activas, 'empleados': empleados, 'tipos_consumible': tipos_consumible,
        'categorias_gasto': Gasto.CATEGORIA_CHOICES, 'categorias_gasto_select': categorias_gasto_choices,
        'metodos_pago': metodos_pago
    }
    return render(request, 'taller/anadir_gasto.html', context)


# --- REGISTRAR INGRESO ---
@login_required
@bloquear_lectura # CANDADO
def registrar_ingreso(request):
    if not (request.user.is_superuser or request.user.has_perm('taller.add_ingreso')):
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para acceder a la gestión de ingresos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if request.method == 'POST':
        categoria = request.POST['categoria']; importe_str = request.POST.get('importe')
        descripcion = request.POST.get('descripcion', '')
        metodo_pago = request.POST.get('metodo_pago', 'EFECTIVO')
        es_tpv_bool = (metodo_pago != 'EFECTIVO')

        fecha_ingreso_str = request.POST.get('fecha_ingreso')
        try: fecha_ingreso = datetime.strptime(fecha_ingreso_str, '%Y-%m-%d').date() if fecha_ingreso_str else timezone.now().date()
        except ValueError: fecha_ingreso = timezone.now().date()
        try:
            importe = Decimal(importe_str) if importe_str else Decimal('0.00')
            if importe <= 0: return redirect('registrar_ingreso')
        except (ValueError, TypeError, Decimal.InvalidOperation): return redirect('registrar_ingreso')

        ingreso = Ingreso(fecha=fecha_ingreso, categoria=categoria, importe=importe, descripcion=descripcion.upper(), es_tpv=es_tpv_bool, metodo_pago=metodo_pago)

        if categoria == 'Taller':
            orden_id = request.POST.get('orden')
            if orden_id:
                ordenes_relevantes = obtener_ordenes_relevantes()
                try:
                    orden_seleccionada = ordenes_relevantes.get(id=orden_id)
                    ingreso.orden = orden_seleccionada
                except OrdenDeReparacion.DoesNotExist: pass
        ingreso.save()
        return redirect('home')

    ordenes_filtradas = obtener_ordenes_relevantes().order_by('-fecha_entrada')
    categorias_ingreso = Ingreso.CATEGORIA_CHOICES
    metodos_pago = Ingreso.METODO_PAGO_CHOICES 

    context = { 'ordenes': ordenes_filtradas, 'categorias_ingreso': categorias_ingreso, 'metodos_pago': metodos_pago }
    return render(request, 'taller/registrar_ingreso.html', context)


# --- STOCK INICIAL CONSUMIBLES ---
@login_required
@bloquear_lectura # CANDADO
def stock_inicial_consumible(request):
    if not (request.user.is_superuser or request.user.has_perm('taller.add_compraconsumible')):
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para registrar compras de stock.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if request.method == 'POST':
        tipo_id = request.POST['tipo_consumible']; cantidad_str = request.POST.get('cantidad'); coste_total_str = request.POST.get('coste_total')
        try:
            cantidad = Decimal(cantidad_str); coste_total = Decimal(coste_total_str)
            if cantidad <= 0 or coste_total < 0: return redirect('stock_inicial_consumible')
            tipo_consumible = get_object_or_404(TipoConsumible, id=tipo_id)
            fecha_compra = timezone.now().date()
            CompraConsumible.objects.create(tipo=tipo_consumible, fecha_compra=fecha_compra, cantidad=cantidad, coste_total=coste_total)
            return redirect('home')
        except (ValueError, TypeError, Decimal.InvalidOperation): return redirect('stock_inicial_consumible')

    tipos_consumible = TipoConsumible.objects.all()
    context = { 'tipos_consumible': tipos_consumible }
    return render(request, 'taller/stock_inicial_consumible.html', context)

# --- CREAR PRESUPUESTO ---
@login_required
@bloquear_lectura # CANDADO
def crear_presupuesto(request):
    if not (request.user.is_superuser or request.user.has_perm('taller.add_presupuesto')):
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para crear presupuestos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if request.method == 'POST':
        cliente_id = request.POST.get('cliente_existente')
        nombre_cliente_form = request.POST.get('cliente_nombre', '').upper()
        telefono_cliente_form = request.POST.get('cliente_telefono', '')
        tipo_documento = request.POST.get('cliente_tipo_documento', 'DNI')
        documento_fiscal = request.POST.get('cliente_documento_fiscal', '')
        direccion_fiscal = request.POST.get('cliente_direccion_fiscal', '')
        codigo_postal_fiscal = request.POST.get('cliente_codigo_postal_fiscal', '')
        ciudad_fiscal = request.POST.get('cliente_ciudad_fiscal', '')
        provincia_fiscal = request.POST.get('cliente_provincia_fiscal', '')
        aplicar_iva = 'aplicar_iva' in request.POST

        cliente = None
        try:
            with transaction.atomic():
                if cliente_id:
                    try: cliente = Cliente.objects.get(id=cliente_id)
                    except Cliente.DoesNotExist: pass
                elif nombre_cliente_form and telefono_cliente_form:
                    cliente, created = Cliente.objects.get_or_create(telefono=telefono_cliente_form, defaults={'nombre': nombre_cliente_form})
                    cliente.nombre = nombre_cliente_form; cliente.tipo_documento = tipo_documento; cliente.documento_fiscal = documento_fiscal
                    cliente.direccion_fiscal = direccion_fiscal; cliente.codigo_postal_fiscal = codigo_postal_fiscal
                    cliente.ciudad_fiscal = ciudad_fiscal; cliente.provincia_fiscal = provincia_fiscal
                    cliente.save()

                if not cliente: return HttpResponse("Error: Cliente inválido o no proporcionado.", status=400)

                vehiculo_id = request.POST.get('vehiculo_existente')
                matricula_nueva = request.POST.get('matricula_nueva', '').upper()
                marca_nueva = request.POST.get('marca_nueva', '').upper()
                modelo_nuevo = request.POST.get('modelo_nuevo', '').upper()
                vehiculo = None
                if vehiculo_id:
                    try:
                        vehiculo = Vehiculo.objects.get(id=vehiculo_id)
                        if vehiculo.cliente != cliente: vehiculo.cliente = cliente; vehiculo.save()
                    except Vehiculo.DoesNotExist: pass
                
                problema = request.POST.get('problema_o_trabajo', '').upper()
                
                presupuesto = Presupuesto.objects.create(
                    cliente=cliente, vehiculo=vehiculo, matricula_nueva=matricula_nueva if not vehiculo and matricula_nueva else None,
                    marca_nueva=marca_nueva if not vehiculo and marca_nueva else None, modelo_nuevo=modelo_nuevo if not vehiculo and modelo_nuevo else None,
                    problema_o_trabajo=problema, estado='Pendiente', aplicar_iva=aplicar_iva
                )

                tipos_linea = request.POST.getlist('linea_tipo'); descripciones_linea = request.POST.getlist('linea_descripcion')
                cantidades_linea = request.POST.getlist('linea_cantidad'); precios_linea = request.POST.getlist('linea_precio_unitario')
                subtotal_calculado = Decimal('0.00')

                for i in range(len(tipos_linea)):
                    if all([tipos_linea[i], descripciones_linea[i], cantidades_linea[i], precios_linea[i]]):
                        try:
                            cantidad = Decimal(cantidades_linea[i]); precio_unitario = Decimal(precios_linea[i])
                            if cantidad <= 0 or precio_unitario < 0: continue
                            linea_total = cantidad * precio_unitario; subtotal_calculado += linea_total
                            LineaPresupuesto.objects.create(presupuesto=presupuesto, tipo=tipos_linea[i], descripcion=descripciones_linea[i].upper(), cantidad=cantidad, precio_unitario_estimado=precio_unitario)
                        except: pass

                iva_calculado = Decimal('0.00')
                if aplicar_iva: iva_calculado = (subtotal_calculado * Decimal('0.21')).quantize(Decimal('0.01'))
                
                presupuesto.subtotal = subtotal_calculado; presupuesto.iva = iva_calculado; presupuesto.total_estimado = subtotal_calculado + iva_calculado
                presupuesto.save()
                
                return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)
        except Exception as e: return redirect('crear_presupuesto')

    clientes = Cliente.objects.all().order_by('nombre')
    vehiculos = Vehiculo.objects.select_related('cliente').order_by('matricula')
    tipos_linea = LineaFactura.TIPO_CHOICES
    
    clientes_con_datos_fiscales = []
    for cliente in clientes:
        clientes_con_datos_fiscales.append({
            'cliente': cliente,
            'cliente_data_json': json.dumps({
                'tipo_documento': cliente.tipo_documento or 'DNI', 'documento_fiscal': cliente.documento_fiscal or '',
                'direccion_fiscal': cliente.direccion_fiscal or '', 'codigo_postal_fiscal': cliente.codigo_postal_fiscal or '',
                'ciudad_fiscal': cliente.ciudad_fiscal or '', 'provincia_fiscal': cliente.provincia_fiscal or 'TARRAGONA',
            })
        })
    
    context = { 'clientes_data': clientes_con_datos_fiscales, 'vehiculos': vehiculos, 'tipos_linea': tipos_linea }
    return render(request, 'taller/crear_presupuesto.html', context)


# --- LISTA PRESUPUESTOS ---
@login_required
def lista_presupuestos(request):
    estado_filtro = request.GET.get('estado'); ano_seleccionado = request.GET.get('ano'); mes_seleccionado = request.GET.get('mes')
    presupuestos_qs = Presupuesto.objects.select_related('cliente', 'vehiculo').order_by('-fecha_creacion')
    if estado_filtro and estado_filtro in [choice[0] for choice in Presupuesto.ESTADO_CHOICES]:
        presupuestos_qs = presupuestos_qs.filter(estado=estado_filtro)
    if ano_seleccionado:
        try: ano_int = int(ano_seleccionado); presupuestos_qs = presupuestos_qs.filter(fecha_creacion__year=ano_int)
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
         try:
            mes_int = int(mes_seleccionado)
            if 1 <= mes_int <= 12: presupuestos_qs = presupuestos_qs.filter(fecha_creacion__month=mes_int)
            else: mes_seleccionado = None
         except (ValueError, TypeError): mes_seleccionado = None
    anos_y_meses_data = get_anos_y_meses_con_datos(); anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None; mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None
    context = {
        'presupuestos': presupuestos_qs, 'estado_actual': estado_filtro, 'estados_posibles': Presupuesto.ESTADO_CHOICES,
        'anos_y_meses': anos_y_meses_data, 'anos_disponibles': anos_disponibles, 'ano_seleccionado': ano_sel_int,
        'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/lista_presupuestos.html', context)


# --- DETALLE PRESUPUESTO ---
@login_required
def detalle_presupuesto(request, presupuesto_id):
    presupuesto = get_object_or_404(Presupuesto.objects.select_related('cliente', 'vehiculo__cliente').prefetch_related('lineas'), id=presupuesto_id)

    if request.method == 'POST' and 'nuevo_estado' in request.POST:
        if request.user.groups.filter(name='Solo Ver').exists():
            return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Tu cuenta está en 'Modo Lectura'. No tienes permiso para modificar datos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

        nuevo_estado = request.POST['nuevo_estado']; estados_validos_cambio = ['Aceptado', 'Rechazado', 'Pendiente']
        if nuevo_estado in estados_validos_cambio and presupuesto.estado != 'Convertido':
            presupuesto.estado = nuevo_estado; presupuesto.save()
            return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)

    orden_generada = None
    try: orden_generada = presupuesto.orden_generada
    except OrdenDeReparacion.DoesNotExist: pass
    context = { 'presupuesto': presupuesto, 'lineas': presupuesto.lineas.all(), 'estados_posibles': Presupuesto.ESTADO_CHOICES, 'orden_generada': orden_generada }
    return render(request, 'taller/detalle_presupuesto.html', context)

# --- EDITAR PRESUPUESTO ---
@login_required
@bloquear_lectura # CANDADO
def editar_presupuesto(request, presupuesto_id):
    if not (request.user.is_superuser or request.user.has_perm('taller.change_presupuesto')):
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para editar presupuestos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    presupuesto = get_object_or_404(Presupuesto.objects.select_related('cliente', 'vehiculo').prefetch_related('lineas'), id=presupuesto_id)
    if presupuesto.estado == 'Convertido': return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                aplicar_iva = 'aplicar_iva' in request.POST

                LineaPresupuesto.objects.filter(presupuesto=presupuesto).delete(); presupuesto.delete()
                
                cliente_id = request.POST.get('cliente_existente'); nombre_cliente_form = request.POST.get('cliente_nombre', '').upper()
                telefono_cliente_form = request.POST.get('cliente_telefono', ''); tipo_documento = request.POST.get('cliente_tipo_documento', 'DNI')
                documento_fiscal = request.POST.get('cliente_documento_fiscal', ''); direccion_fiscal = request.POST.get('cliente_direccion_fiscal', '')
                codigo_postal_fiscal = request.POST.get('cliente_codigo_postal_fiscal', ''); ciudad_fiscal = request.POST.get('cliente_ciudad_fiscal', '')
                provincia_fiscal = request.POST.get('cliente_provincia_fiscal', '')
                
                cliente = None
                if cliente_id:
                    try: cliente = Cliente.objects.get(id=cliente_id)
                    except Cliente.DoesNotExist: pass
                elif nombre_cliente_form and telefono_cliente_form:
                    cliente, created = Cliente.objects.get_or_create(telefono=telefono_cliente_form, defaults={'nombre': nombre_cliente_form})
                    cliente.nombre = nombre_cliente_form; cliente.tipo_documento = tipo_documento; cliente.documento_fiscal = documento_fiscal
                    cliente.direccion_fiscal = direccion_fiscal; cliente.codigo_postal_fiscal = codigo_postal_fiscal
                    cliente.ciudad_fiscal = ciudad_fiscal; cliente.provincia_fiscal = provincia_fiscal; cliente.save()

                if not cliente: raise ValueError("Cliente inválido")

                vehiculo_id = request.POST.get('vehiculo_existente'); matricula_nueva = request.POST.get('matricula_nueva', '').upper()
                marca_nueva = request.POST.get('marca_nueva', '').upper(); modelo_nuevo = request.POST.get('modelo_nuevo', '').upper()
                vehiculo = None
                if vehiculo_id:
                    try:
                        vehiculo = Vehiculo.objects.get(id=vehiculo_id)
                        if vehiculo.cliente != cliente: vehiculo.cliente = cliente; vehiculo.save()
                    except Vehiculo.DoesNotExist: pass

                problema = request.POST.get('problema_o_trabajo', '').upper()
                
                nuevo_presupuesto = Presupuesto.objects.create(
                    cliente=cliente, vehiculo=vehiculo, matricula_nueva=matricula_nueva if not vehiculo and matricula_nueva else None,
                    marca_nueva=marca_nueva if not vehiculo and marca_nueva else None, modelo_nuevo=modelo_nuevo if not vehiculo and modelo_nuevo else None,
                    problema_o_trabajo=problema, estado='Pendiente', aplicar_iva=aplicar_iva
                )

                tipos_linea = request.POST.getlist('linea_tipo'); descripciones_linea = request.POST.getlist('linea_descripcion')
                cantidades_linea = request.POST.getlist('linea_cantidad'); precios_linea = request.POST.getlist('linea_precio_unitario')
                subtotal_calculado = Decimal('0.00')

                for i in range(len(tipos_linea)):
                     if all([tipos_linea[i], descripciones_linea[i], cantidades_linea[i], precios_linea[i]]):
                         try:
                             cantidad = Decimal(cantidades_linea[i]); precio_unitario = Decimal(precios_linea[i])
                             if cantidad <= 0 or precio_unitario < 0: continue
                             linea_total = cantidad * precio_unitario; subtotal_calculado += linea_total
                             LineaPresupuesto.objects.create(presupuesto=nuevo_presupuesto, tipo=tipos_linea[i], descripcion=descripciones_linea[i].upper(), cantidad=cantidad, precio_unitario_estimado=precio_unitario)
                         except: pass
                
                iva_calculado = Decimal('0.00')
                if aplicar_iva: iva_calculado = (subtotal_calculado * Decimal('0.21')).quantize(Decimal('0.01'))
                
                nuevo_presupuesto.subtotal = subtotal_calculado; nuevo_presupuesto.iva = iva_calculado; nuevo_presupuesto.total_estimado = subtotal_calculado + iva_calculado
                nuevo_presupuesto.save()
                
                return redirect('detalle_presupuesto', presupuesto_id=nuevo_presupuesto.id)
        except Exception as e: return redirect('lista_presupuestos')

    clientes = Cliente.objects.all().order_by('nombre'); vehiculos = Vehiculo.objects.select_related('cliente').order_by('matricula')
    tipos_linea = LineaFactura.TIPO_CHOICES
    
    clientes_con_datos_fiscales = []
    for cliente in clientes:
        clientes_con_datos_fiscales.append({
            'cliente': cliente,
            'cliente_data_json': json.dumps({
                'tipo_documento': cliente.tipo_documento or 'DNI', 'documento_fiscal': cliente.documento_fiscal or '',
                'direccion_fiscal': cliente.direccion_fiscal or '', 'codigo_postal_fiscal': cliente.codigo_postal_fiscal or '',
                'ciudad_fiscal': cliente.ciudad_fiscal or '', 'provincia_fiscal': cliente.provincia_fiscal or 'TARRAGONA',
            })
        })
    
    lineas_existentes_list = []
    for linea in presupuesto.lineas.all():
        lineas_existentes_list.append({ 'tipo': linea.tipo, 'descripcion': linea.descripcion, 'cantidad': float(linea.cantidad), 'precio_unitario_estimado': float(linea.precio_unitario_estimado) })
        
    context = { 'presupuesto_existente': presupuesto, 'clientes_data': clientes_con_datos_fiscales, 'vehiculos': vehiculos, 'tipos_linea': tipos_linea, 'lineas_existentes_json': json.dumps(lineas_existentes_list) }
    return render(request, 'taller/editar_presupuesto.html', context)


# --- LISTA ORDENES ---
@login_required
def lista_ordenes(request):
    # Si hacemos clic en el botón de mover de lista
    if request.method == 'POST':
        orden_id = request.POST.get('orden_id')
        accion = request.POST.get('accion')
        if orden_id and accion:
            from django.shortcuts import get_object_or_404
            orden = get_object_or_404(OrdenDeReparacion, id=orden_id)
            if accion == 'hacer_interno':
                orden.trabajo_interno = True
            elif accion == 'hacer_cliente':
                orden.trabajo_interno = False
            orden.save()
        return redirect('lista_ordenes')

    # Traemos las órdenes que no estén "Entregadas"
    ordenes_activas = OrdenDeReparacion.objects.exclude(estado='Entregado').select_related('vehiculo', 'cliente')
    
    # Las separamos en dos grupos y las ordenamos por las más antiguas primero
    ordenes_clientes = ordenes_activas.filter(trabajo_interno=False).order_by('id')
    ordenes_taller = ordenes_activas.filter(trabajo_interno=True).order_by('id')

    return render(request, 'taller/lista_ordenes.html', {
        'ordenes_clientes': ordenes_clientes,
        'ordenes_taller': ordenes_taller
    })

# --- DETALLE ORDEN (CON WHATSAPP DIRECTO Y NOTAS INTERNAS) ---
@login_required
def detalle_orden(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('cliente', 'vehiculo', 'presupuesto_origen').prefetch_related('fotos', 'ingreso_set', 'factura', 'notas_internas'), id=orden_id)
    repuestos = Gasto.objects.filter(orden=orden, categoria='Repuestos')
    gastos_otros = Gasto.objects.filter(orden=orden, categoria='Otros')
    abonos = sum(ing.importe for ing in orden.ingreso_set.all()) if hasattr(orden, 'ingreso_set') and orden.ingreso_set.exists() else Decimal('0.00')
    tipos_consumible = TipoConsumible.objects.all()
    
    factura = None; pendiente_pago = Decimal('0.00'); whatsapp_url = None 
    
    if request.user.is_superuser:
        try: 
            factura = orden.factura
            pendiente_pago = factura.total_final - abonos
            
            if orden.cliente.telefono:
                signer = Signer(); signed_id = signer.sign(factura.id) 
                public_url = request.build_absolute_uri(reverse('ver_factura_publica', args=[signed_id]))
                telefono_limpio = "".join(filter(str.isdigit, orden.cliente.telefono))
                if not telefono_limpio.startswith('34') and len(telefono_limpio) == 9: telefono_limpio = '34' + telefono_limpio
                tipo_doc = "factura" if factura.es_factura else "recibo"
                mensaje = f"Hola {orden.cliente.nombre}, aquí tienes el enlace para descargar tu {tipo_doc} del taller:\n\n{public_url}\n\n¡Gracias por confiar en ServiMax!"
                mensaje_encoded = quote(mensaje); whatsapp_url = f"https://wa.me/{telefono_limpio}?text={mensaje_encoded}"
        except Factura.DoesNotExist: pass

    if request.method == 'POST':
        if request.user.groups.filter(name='Solo Ver').exists():
            return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Tu cuenta está en 'Modo Lectura'.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

        form_type = request.POST.get('form_type')

        if form_type == 'estado':
            nuevo_estado = request.POST.get('nuevo_estado')
            if nuevo_estado in [choice[0] for choice in OrdenDeReparacion.ESTADO_CHOICES]:
                orden.estado = nuevo_estado; orden.save()
            return redirect('detalle_orden', orden_id=orden.id)

        elif form_type == 'kilometraje':
            try:
                nuevo_km_str = request.POST.get('nuevo_kilometraje')
                if int(nuevo_km_str) >= 0:
                    vehiculo = orden.vehiculo; vehiculo.kilometraje = int(nuevo_km_str); vehiculo.save()
            except (ValueError, TypeError): pass
            return redirect('detalle_orden', orden_id=orden.id)
        
        elif form_type == 'subir_fotos':
            descripciones = ['Frontal', 'Trasera', 'Lateral Izquierdo', 'Lateral Derecho', 'Cuadro/Km']
            for i in range(1, 6):
                foto_campo = f'foto{i}'
                if foto_campo in request.FILES:
                    FotoVehiculo.objects.create(orden=orden, imagen=request.FILES[foto_campo], descripcion=descripciones[i-1])
            return redirect('detalle_orden', orden_id=orden.id)
            
        # NUEVA LÓGICA PARA GUARDAR NOTA INTERNA
        elif form_type == 'nota_interna':
            texto_nota = request.POST.get('texto_nota')
            if texto_nota:
                NotaInternaOrden.objects.create(orden=orden, autor=request.user, texto=texto_nota)
            return redirect('detalle_orden', orden_id=orden.id)

    context = {
        'orden': orden, 'repuestos': repuestos, 'gastos_otros': gastos_otros, 'factura': factura,
        'abonos': abonos, 'pendiente_pago': pendiente_pago, 'tipos_consumible': tipos_consumible,
        'fotos': orden.fotos.all(), 'estados_orden': OrdenDeReparacion.ESTADO_CHOICES, 'whatsapp_url': whatsapp_url,
        'notas_internas': orden.notas_internas.all(), # Pasamos las notas a la pantalla
    }
    return render(request, 'taller/detalle_orden.html', context)

# --- HISTORIAL ORDENES ---
@login_required
def historial_ordenes(request):
    ordenes_qs = OrdenDeReparacion.objects.filter(estado='Entregado').select_related('cliente', 'vehiculo', 'factura')
    anos_y_meses_data = get_anos_y_meses_con_datos(); anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano'); mes_seleccionado = request.GET.get('mes')
    
    matricula_buscada = request.GET.get('matricula', '').strip()
    if matricula_buscada: ordenes_qs = ordenes_qs.filter(vehiculo__matricula__icontains=matricula_buscada)

    if ano_seleccionado:
        try: ano_int = int(ano_seleccionado); ordenes_qs = ordenes_qs.filter(factura__fecha_emision__year=ano_int)
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
         try:
            mes_int = int(mes_seleccionado)
            if 1 <= mes_int <= 12: ordenes_qs = ordenes_qs.filter(factura__fecha_emision__month=mes_int)
            else: mes_seleccionado = None
         except (ValueError, TypeError): mes_seleccionado = None
         
    ordenes = ordenes_qs.order_by('-factura__fecha_emision', '-id')
    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None
    mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None
    
    context = { 'ordenes': ordenes, 'anos_y_meses': anos_y_meses_data, 'anos_disponibles': anos_disponibles, 'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13), 'matricula_buscada': matricula_buscada }
    return render(request, 'taller/historial_ordenes.html', context)


# --- HISTORIAL MOVIMIENTOS ---
@login_required
def historial_movimientos(request):
    from django.utils import timezone
    from django.db.models.functions import ExtractYear
    
    tipo_seleccionado = request.GET.get('tipo', '')
    ano_seleccionado = request.GET.get('ano', '')
    mes_seleccionado = request.GET.get('mes', '')
    matricula_seleccionada = request.GET.get('matricula', '') # <--- NUEVO: Capturamos la matrícula

    gastos_qs = Gasto.objects.select_related('orden', 'orden__vehiculo').all()
    ingresos_qs = Ingreso.objects.select_related('orden', 'orden__vehiculo').all()

    # Filtros de fecha
    if ano_seleccionado and ano_seleccionado.isdigit():
        gastos_qs = gastos_qs.filter(fecha__year=int(ano_seleccionado))
        ingresos_qs = ingresos_qs.filter(fecha__year=int(ano_seleccionado))
        
    if mes_seleccionado and mes_seleccionado.isdigit():
        gastos_qs = gastos_qs.filter(fecha__month=int(mes_seleccionado))
        ingresos_qs = ingresos_qs.filter(fecha__month=int(mes_seleccionado))

    # --- NUEVO: Filtro por matrícula ---
    if matricula_seleccionada:
        # Busca si la matrícula contiene el texto (ignorando mayúsculas/minúsculas)
        gastos_qs = gastos_qs.filter(orden__vehiculo__matricula__icontains=matricula_seleccionada)
        ingresos_qs = ingresos_qs.filter(orden__vehiculo__matricula__icontains=matricula_seleccionada)

    # Etiquetar y combinar
    movimientos = []
    if tipo_seleccionado in ['', 'gasto']:
        for g in gastos_qs:
            g.tipo = 'gasto'
            movimientos.append(g)
            
    if tipo_seleccionado in ['', 'ingreso']:
        for i in ingresos_qs:
            i.tipo = 'ingreso'
            movimientos.append(i)

    # Ordenar
    movimientos.sort(key=lambda x: (x.fecha, x.id), reverse=True)

    # Extraer años
    anos_gastos = Gasto.objects.annotate(year=ExtractYear('fecha')).values_list('year', flat=True).distinct()
    anos_ingresos = Ingreso.objects.annotate(year=ExtractYear('fecha')).values_list('year', flat=True).distinct()
    anos_disponibles = sorted(list(set(list(anos_gastos) + list(anos_ingresos))), reverse=True)
    if not anos_disponibles:
        anos_disponibles = [timezone.now().year]

    context = {
        'movimientos': movimientos,
        'tipo_seleccionado': tipo_seleccionado,
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado.isdigit() else '',
        'mes_seleccionado': str(mes_seleccionado),
        'matricula_seleccionada': matricula_seleccionada, # <--- NUEVO: Lo pasamos a la web
        'anos_disponibles': anos_disponibles,
    }
    return render(request, 'taller/historial_movimientos.html', context)

# --- EDITAR MOVIMIENTO ---
@login_required
@bloquear_lectura # CANDADO
def editar_movimiento(request, tipo, movimiento_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para editar movimientos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if tipo not in ['gasto', 'ingreso']: return redirect('historial_movimientos')
    admin_url_name = f'admin:taller_{tipo}_change'
    try: admin_url = reverse(admin_url_name, args=[movimiento_id]); return redirect(admin_url)
    except Exception as e: return redirect(f'/admin/taller/{tipo}/{movimiento_id}/change/')

    # --- ELIMINAR MOVIMIENTOS DESDE EL HISTORIAL ---
@login_required
def eliminar_movimiento(request, tipo, movimiento_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden("🔒 Acceso denegado.")
        
    if request.method == 'POST':
        if tipo == 'gasto':
            movimiento = get_object_or_404(Gasto, id=movimiento_id)
            movimiento.delete() # Esto disparará la alarma de models.py automáticamente
        elif tipo == 'ingreso':
            movimiento = get_object_or_404(Ingreso, id=movimiento_id)
            movimiento.delete()
            
    return redirect('historial_movimientos')


# --- GENERAR FACTURA ---
@login_required
@bloquear_lectura # CANDADO
def generar_factura(request, orden_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Solo Administración puede generar facturas.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo'), id=orden_id)

    if request.method == 'POST':
        es_factura = 'aplicar_iva' in request.POST
        notas = request.POST.get('notas_cliente', '')

        with transaction.atomic():
            factura_anterior = Factura.objects.filter(orden=orden).first()
            numero_a_conservar = None; fecha_a_conservar = None
            if factura_anterior:
                if factura_anterior.es_factura and factura_anterior.numero_factura: numero_a_conservar = factura_anterior.numero_factura
                fecha_a_conservar = factura_anterior.fecha_emision

            Factura.objects.filter(orden=orden).delete(); UsoConsumible.objects.filter(orden=orden).delete()

            nuevo_numero_factura = None
            if es_factura:
                if numero_a_conservar: nuevo_numero_factura = numero_a_conservar
                else:
                    ultima_factura = Factura.objects.select_for_update().filter(numero_factura__isnull=False).order_by('-numero_factura').first()
                    if ultima_factura and ultima_factura.numero_factura: nuevo_numero_factura = ultima_factura.numero_factura + 1
                    else: nuevo_numero_factura = 1
            
            factura = Factura.objects.create(orden=orden, es_factura=es_factura, notas_cliente=notas, numero_factura=nuevo_numero_factura )
            
            if fecha_a_conservar:
                Factura.objects.filter(id=factura.id).update(fecha_emision=fecha_a_conservar)
                factura.fecha_emision = fecha_a_conservar
            
            subtotal = Decimal('0.00')
            repuestos_qs = Gasto.objects.filter(orden=orden, categoria='Repuestos'); gastos_otros_qs = Gasto.objects.filter(orden=orden, categoria='Otros')
            
            for repuesto in repuestos_qs:
                pvp_str = request.POST.get(f'pvp_repuesto_{repuesto.id}')
                if pvp_str:
                    try:
                        pvp = Decimal(pvp_str); coste_repuesto = repuesto.importe or Decimal('0.00')
                        if pvp < coste_repuesto: pvp = coste_repuesto
                        subtotal += pvp; LineaFactura.objects.create(factura=factura, tipo='Repuesto', descripcion=repuesto.descripcion, cantidad=1, precio_unitario=pvp)
                    except: pass
            
            for gasto_otro in gastos_otros_qs:
                pvp_str = request.POST.get(f'pvp_otro_{gasto_otro.id}')
                if pvp_str:
                    try:
                        pvp = Decimal(pvp_str); coste_gasto = gasto_otro.importe or Decimal('0.00')
                        if pvp < coste_gasto: pvp = coste_gasto
                        subtotal += pvp; LineaFactura.objects.create(factura=factura, tipo='Externo', descripcion=gasto_otro.descripcion, cantidad=1, precio_unitario=pvp)
                    except: pass
            
            tipos_consumible_id = request.POST.getlist('tipo_consumible'); cantidades_consumible = request.POST.getlist('consumible_cantidad'); pvps_consumible = request.POST.getlist('consumible_pvp_total')
            for i in range(len(tipos_consumible_id)):
                if tipos_consumible_id[i] and cantidades_consumible[i] and pvps_consumible[i]:
                    try:
                        tipo = TipoConsumible.objects.get(id=tipos_consumible_id[i]); cantidad = Decimal(cantidades_consumible[i]); pvp_total = Decimal(pvps_consumible[i])
                        if cantidad <= 0 or pvp_total < 0: continue
                        precio_unitario_calculado = (pvp_total / cantidad).quantize(Decimal('0.01')); subtotal += pvp_total
                        LineaFactura.objects.create(factura=factura, tipo='Consumible', descripcion=tipo.nombre, cantidad=cantidad, precio_unitario=precio_unitario_calculado)
                        UsoConsumible.objects.create(orden=orden, tipo=tipo, cantidad_usada=cantidad)
                    except: pass
            
            descripciones_mo = request.POST.getlist('mano_obra_desc'); importes_mo = request.POST.getlist('mano_obra_importe')
            for desc, importe_str in zip(descripciones_mo, importes_mo):
                if desc and importe_str:
                    try:
                        importe = Decimal(importe_str)
                        if importe <= 0: continue
                        subtotal += importe; LineaFactura.objects.create(factura=factura, tipo='Mano de Obra', descripcion=desc.upper(), cantidad=1, precio_unitario=importe)
                    except: pass
            
            iva_calculado = Decimal('0.00'); subtotal_positivo = max(subtotal, Decimal('0.00'))
            if es_factura: iva_calculado = (subtotal_positivo * Decimal('0.21')).quantize(Decimal('0.01'))
            total_final = subtotal_positivo + iva_calculado
            factura.subtotal = subtotal; factura.iva = iva_calculado; factura.total_final = total_final
            factura.save() 
            
            orden.estado = 'Listo para Recoger'; orden.save()
            return redirect('detalle_orden', orden_id=orden.id)

    return redirect('detalle_orden', orden_id=orden.id)


@login_required
def ver_factura_pdf(request, factura_id):
    factura = get_object_or_404(Factura.objects.select_related('orden__cliente', 'orden__vehiculo'), id=factura_id)
    return generar_pdf_response(factura)

def ver_factura_publica(request, signed_id):
    signer = Signer()
    try:
        original_id = signer.unsign(signed_id)
        factura = get_object_or_404(Factura.objects.select_related('orden__cliente', 'orden__vehiculo'), id=original_id)
        return generar_pdf_response(factura)
    except BadSignature: return HttpResponseForbidden("El enlace de la factura es inválido o ha sido modificado.")


@login_required
@bloquear_lectura # CANDADO
def editar_factura(request, factura_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Solo Administración puede editar facturas.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    factura = get_object_or_404(Factura.objects.prefetch_related('lineas'), id=factura_id)
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo__cliente'), id=factura.orden_id)

    if request.method == 'POST':
        with transaction.atomic():
            UsoConsumible.objects.filter(orden=orden).delete()
            factura.delete()
        try:
             original_request = getattr(request, '_request', request)
             return generar_factura(original_request, orden.id)
        except Exception as e:
             return redirect('detalle_orden', orden_id=orden.id)

    repuestos_qs = Gasto.objects.filter(orden=orden, categoria='Repuestos')
    gastos_otros_qs = Gasto.objects.filter(orden=orden, categoria='Otros')
    tipos_consumible = TipoConsumible.objects.all()
    lineas_existentes_list = []
    for linea in factura.lineas.all():
        linea_data = { 'tipo': linea.tipo, 'descripcion': linea.descripcion, 'cantidad': float(linea.cantidad), 'precio_unitario': float(linea.precio_unitario),
                       'tipo_consumible_id': None, 'repuesto_id': None, 'externo_id': None }
        if linea.tipo == 'Consumible':
            tipo_obj = TipoConsumible.objects.filter(nombre__iexact=linea.descripcion).first()
            linea_data['tipo_consumible_id'] = tipo_obj.id if tipo_obj else None
        elif linea.tipo == 'Repuesto':
            gasto_obj = repuestos_qs.filter(descripcion__iexact=linea.descripcion).first()
            linea_data['repuesto_id'] = gasto_obj.id if gasto_obj else None
        elif linea.tipo == 'Externo':
            gasto_obj = gastos_otros_qs.filter(descripcion__iexact=linea.descripcion).first()
            linea_data['externo_id'] = gasto_obj.id if gasto_obj else None
        lineas_existentes_list.append(linea_data)
    context = { 'orden': orden, 'factura_existente': factura, 'repuestos': repuestos_qs, 'gastos_otros': gastos_otros_qs, 'tipos_consumible': tipos_consumible, 'lineas_existentes_json': json.dumps(lineas_existentes_list) }
    return render(request, 'taller/editar_factura.html', context)


# --- INFORMES Y CONTABILIDAD (VISTAS DE LECTURA) ---
@login_required
def informe_rentabilidad(request):
    if not request.user.is_superuser:
        return redirect('home')

    hoy = timezone.now().date()
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    facturas_qs = Factura.objects.select_related('orden__vehiculo').prefetch_related('lineas', 'orden__vehiculo__gasto_set')
    ingresos_grua_qs = Ingreso.objects.filter(categoria='Grua')
    otras_ganancias_qs = Ingreso.objects.filter(categoria='Otras Ganancias')

    ano_sel_int = None
    if ano_seleccionado:
        try:
            ano_sel_int = int(ano_seleccionado)
            facturas_qs = facturas_qs.filter(fecha_emision__year=ano_sel_int)
            ingresos_grua_qs = ingresos_grua_qs.filter(fecha__year=ano_sel_int)
            otras_ganancias_qs = otras_ganancias_qs.filter(fecha__year=ano_sel_int)
        except (ValueError, TypeError): ano_seleccionado = None
            
    mes_sel_int = None
    if mes_seleccionado:
         try:
            mes_sel_int = int(mes_seleccionado)
            if 1 <= mes_sel_int <= 12:
                facturas_qs = facturas_qs.filter(fecha_emision__month=mes_sel_int)
                ingresos_grua_qs = ingresos_grua_qs.filter(fecha__month=mes_sel_int)
                otras_ganancias_qs = otras_ganancias_qs.filter(fecha__month=mes_sel_int)
            else: mes_seleccionado = None
         except (ValueError, TypeError): mes_seleccionado = None

    facturas = facturas_qs.order_by('-fecha_emision')
    ingresos_grua = ingresos_grua_qs.order_by('-fecha')
    otras_ganancias = otras_ganancias_qs.order_by('-fecha')
    
    ganancia_trabajos = Decimal('0.00')
    reporte = []
    
    compras_consumibles = CompraConsumible.objects.order_by('tipo_id', '-fecha_compra')
    ultimas_compras_por_tipo = {}
    for compra in compras_consumibles:
        if compra.tipo_id not in ultimas_compras_por_tipo:
            ultimas_compras_por_tipo[compra.tipo_id] = compra
    tipos_consumible_dict = {tipo.nombre.upper(): tipo for tipo in TipoConsumible.objects.all()}
    
    for factura in facturas:
        orden = factura.orden
        if not orden: continue 
        
        gastos_orden_qs = Gasto.objects.filter(orden=orden, categoria__in=['Repuestos', 'Otros'])
        coste_piezas_externos_factura = gastos_orden_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        coste_consumibles_factura = Decimal('0.00')
        
        for linea in factura.lineas.all():
            if linea.tipo == 'Consumible':
                tipo_obj = tipos_consumible_dict.get(linea.descripcion.upper())
                if tipo_obj and tipo_obj.id in ultimas_compras_por_tipo:
                        compra_relevante = ultimas_compras_por_tipo[tipo_obj.id]
                        if compra_relevante.fecha_compra <= factura.fecha_emision:
                            coste_linea = (compra_relevante.coste_por_unidad or Decimal('0.00')) * linea.cantidad
                            coste_consumibles_factura += coste_linea
        
        coste_total_directo = coste_piezas_externos_factura + coste_consumibles_factura
        base_cobrada = factura.subtotal if factura.es_factura else factura.total_final
        ganancia_total_orden = base_cobrada - coste_total_directo
        
        ganancia_trabajos += ganancia_total_orden
        reporte.append({ 'orden': orden, 'factura': factura, 'ganancia_total': ganancia_total_orden })
    
    ganancia_grua_total = ingresos_grua.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    ganancia_otras_total = otras_ganancias.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia_general = ganancia_trabajos + ganancia_grua_total + ganancia_otras_total
    ganancias_directas_desglose = sorted(list(ingresos_grua) + list(otras_ganancias), key=lambda x: x.fecha, reverse=True)
    
    context = { 
        'reporte': reporte, 'ganancia_trabajos': ganancia_trabajos, 'ganancia_grua': ganancia_grua_total, 
        'ganancia_otras': ganancia_otras_total, 'ganancias_directas_desglose': ganancias_directas_desglose, 
        'total_ganancia_general': total_ganancia_general, 'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/informe_rentabilidad.html', context)

@login_required
def detalle_ganancia_orden(request, orden_id):
    if not request.user.is_superuser:
        return redirect('home')

    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo', 'cliente'), id=orden_id)
    try: factura = Factura.objects.prefetch_related('lineas', 'orden__ingreso_set').get(orden=orden)
    except Factura.DoesNotExist: return redirect('detalle_orden', orden_id=orden.id)
    desglose_agrupado = {}; gastos_usados_ids = set()
    
    gastos_asociados = Gasto.objects.filter(orden=orden, categoria__in=['Repuestos', 'Otros']).order_by('id')
    compras_consumibles = CompraConsumible.objects.filter(fecha_compra__lte=factura.fecha_emision).order_by('tipo_id', '-fecha_compra')
    ultimas_compras_por_tipo = {};
    for compra in compras_consumibles:
        if compra.tipo_id not in ultimas_compras_por_tipo: ultimas_compras_por_tipo[compra.tipo_id] = compra
    tipos_consumible_dict = {tipo.nombre.upper(): tipo for tipo in TipoConsumible.objects.all()}
    
    for linea in factura.lineas.all():
        pvp_linea = linea.total_linea; coste_linea = Decimal('0.00'); descripcion_limpia = linea.descripcion.strip().upper(); key = (linea.tipo, descripcion_limpia)
        desglose_agrupado.setdefault(key, {'descripcion': f"{linea.get_tipo_display()}: {linea.descripcion}", 'coste': Decimal('0.00'), 'pvp': Decimal('0.00')})
        desglose_agrupado[key]['pvp'] += pvp_linea
        if linea.tipo in ['Repuesto', 'Externo']:
            categoria_gasto = 'Repuestos' if linea.tipo == 'Repuesto' else 'Otros'; gasto_encontrado = None
            for gasto in gastos_asociados:
                if (gasto.id not in gastos_usados_ids and gasto.categoria == categoria_gasto and gasto.descripcion.strip().upper() == descripcion_limpia): gasto_encontrado = gasto; break
            if gasto_encontrado: coste_linea = gasto_encontrado.importe or Decimal('0.00'); gastos_usados_ids.add(gasto_encontrado.id)
        elif linea.tipo == 'Consumible':
             tipo_obj = tipos_consumible_dict.get(descripcion_limpia)
             if tipo_obj and tipo_obj.id in ultimas_compras_por_tipo: coste_unitario = ultimas_compras_por_tipo[tipo_obj.id].coste_por_unidad or Decimal('0.00'); coste_linea = coste_unitario * linea.cantidad
        desglose_agrupado[key]['coste'] += coste_linea
        
    for gasto in gastos_asociados:
        if gasto.id not in gastos_usados_ids:
             descripcion_limpia = gasto.descripcion.strip().upper(); tipo_gasto_map = {'Repuestos': 'Repuesto', 'Otros': 'Externo'}; tipo_para_key = tipo_gasto_map.get(gasto.categoria, 'Externo'); key = (tipo_para_key, descripcion_limpia)
             desglose_agrupado.setdefault(key, {'descripcion': f"{gasto.get_categoria_display()}: {gasto.descripcion}", 'coste': Decimal('0.00'), 'pvp': Decimal('0.00')})
             desglose_agrupado[key]['coste'] += gasto.importe or Decimal('0.00')
             
    desglose_final_list = []; ganancia_total_calculada = Decimal('0.00')
    for item_agrupado in desglose_agrupado.values():
        ganancia = item_agrupado['pvp'] - item_agrupado['coste']; item_agrupado['ganancia'] = ganancia; desglose_final_list.append(item_agrupado); ganancia_total_calculada += ganancia
    desglose_final_list.sort(key=lambda x: x['descripcion'])
    
    abonos = sum(ing.importe for ing in factura.orden.ingreso_set.all()) if hasattr(factura.orden, 'ingreso_set') else Decimal('0.00')
    saldo_cliente = abonos - factura.total_final; saldo_cliente_abs = abs(saldo_cliente)
    context = { 'orden': orden, 'factura': factura, 'desglose': desglose_final_list, 'ganancia_total': ganancia_total_calculada, 'abonos_totales': abonos, 'saldo_cliente': saldo_cliente, 'saldo_cliente_abs': saldo_cliente_abs }
    return render(request, 'taller/detalle_ganancia_orden.html', context)

@login_required
def informe_gastos(request):
    if not request.user.is_superuser:
        return redirect('home')

    gastos_qs = Gasto.objects.select_related('empleado', 'vehiculo')
    anos_y_meses_data = get_anos_y_meses_con_datos(); anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano'); mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado:
        try: gastos_qs = gastos_qs.filter(fecha__year=int(ano_seleccionado))
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
        try:
            mes = int(mes_seleccionado)
            if 1 <= mes <= 12: gastos_qs = gastos_qs.filter(fecha__month=mes)
            else: mes_seleccionado = None
        except (ValueError, TypeError): mes_seleccionado = None
        
    totales_por_categoria_query = gastos_qs.values('categoria').annotate(total=Sum('importe')).order_by('categoria')
    categoria_display_map = dict(Gasto.CATEGORIA_CHOICES); resumen_categorias = {}
    for item in totales_por_categoria_query:
         clave_interna = item['categoria']; nombre_legible = categoria_display_map.get(clave_interna, clave_interna)
         total_categoria = item['total'] or Decimal('0.00'); resumen_categorias[clave_interna] = {'display_name': nombre_legible, 'total': total_categoria}
         
    desglose_sueldos_query = gastos_qs.filter(categoria='Sueldos', empleado__isnull=False).values('empleado__nombre').annotate(total=Sum('importe')).order_by('empleado__nombre')
    desglose_sueldos = {item['empleado__nombre']: item['total'] or Decimal('0.00') for item in desglose_sueldos_query if item['empleado__nombre']}
    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None; mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None
    
    context = { 'totales_por_categoria': resumen_categorias, 'desglose_sueldos': desglose_sueldos, 'anos_disponibles': anos_disponibles, 'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13) }
    return render(request, 'taller/informe_gastos.html', context)

@login_required
def informe_gastos_desglose(request, categoria, empleado_nombre=None):
    if not request.user.is_superuser:
        return redirect('home')

    gastos_qs = Gasto.objects.select_related('vehiculo__cliente', 'empleado')
    categoria_map = dict(Gasto.CATEGORIA_CHOICES); categoria_interna = categoria
    if empleado_nombre:
        empleado_nombre_limpio = empleado_nombre.replace('_', ' ')
        gastos_qs = gastos_qs.filter(categoria='Sueldos', empleado__nombre__iexact=empleado_nombre_limpio); titulo = f"Desglose de Sueldos: {empleado_nombre_limpio.upper()}"
    else:
        gastos_qs = gastos_qs.filter(categoria__iexact=categoria_interna)
        titulo_categoria = categoria_map.get(categoria_interna, categoria_interna); titulo = f"Desglose de Gastos: {titulo_categoria}"
    ano_seleccionado = request.GET.get('ano'); mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado:
        try: gastos_qs = gastos_qs.filter(fecha__year=int(ano_seleccionado))
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
        try:
            mes = int(mes_seleccionado)
            if 1 <= mes <= 12: gastos_qs = gastos_qs.filter(fecha__month=mes)
            else: mes_seleccionado = None
        except (ValueError, TypeError): mes_seleccionado = None
        
    total_desglose = gastos_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gastos_desglose = gastos_qs.order_by('-fecha', '-id')
    context = { 'titulo': titulo, 'gastos_desglose': gastos_desglose, 'total_desglose': total_desglose, 'ano_seleccionado': ano_seleccionado, 'mes_seleccionado': mes_seleccionado, 'categoria_original_url': categoria }
    return render(request, 'taller/informe_gastos_desglose.html', context)

@login_required
def informe_ingresos(request):
    if not request.user.is_superuser:
        return redirect('home')

    ingresos_qs = Ingreso.objects.all()
    anos_y_meses_data = get_anos_y_meses_con_datos(); anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano'); mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado:
        try: ingresos_qs = ingresos_qs.filter(fecha__year=int(ano_seleccionado))
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
        try:
            mes = int(mes_seleccionado)
            if 1 <= mes <= 12: ingresos_qs = ingresos_qs.filter(fecha__month=mes)
            else: mes_seleccionado = None
        except (ValueError, TypeError): mes_seleccionado = None
        
    totales_por_categoria_query = ingresos_qs.values('categoria').annotate(total=Sum('importe')).order_by('categoria')
    categoria_display_map = dict(Ingreso.CATEGORIA_CHOICES)
    resumen_categorias = { item['categoria']: {'display_name': categoria_display_map.get(item['categoria'], item['categoria']), 'total': item['total'] or Decimal('0.00')} for item in totales_por_categoria_query }
    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None; mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None
    
    context = { 'totales_por_categoria': resumen_categorias, 'anos_disponibles': anos_disponibles, 'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13) }
    return render(request, 'taller/informe_ingresos.html', context)

@login_required
def informe_ingresos_desglose(request, categoria):
    if not request.user.is_superuser:
        return redirect('home')

    ingresos_qs = Ingreso.objects.select_related('orden__vehiculo')
    categoria_display_map = dict(Ingreso.CATEGORIA_CHOICES); categoria_interna = categoria
    titulo = f"Desglose de Ingresos: {categoria_display_map.get(categoria_interna, categoria_interna)}"; ingresos_qs = ingresos_qs.filter(categoria__iexact=categoria_interna)
    ano_seleccionado = request.GET.get('ano'); mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado:
        try: ingresos_qs = ingresos_qs.filter(fecha__year=int(ano_seleccionado))
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
        try:
            mes = int(mes_seleccionado)
            if 1 <= mes <= 12: ingresos_qs = ingresos_qs.filter(fecha__month=mes)
            else: mes_seleccionado = None
        except (ValueError, TypeError): mes_seleccionado = None
        
    total_desglose = ingresos_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    ingresos_desglose = ingresos_qs.order_by('-fecha', '-id')
    context = { 'titulo': titulo, 'ingresos_desglose': ingresos_desglose, 'total_desglose': total_desglose, 'ano_seleccionado': ano_seleccionado, 'mes_seleccionado': mes_seleccionado, 'categoria_original_url': categoria }
    return render(request, 'taller/informe_ingresos_desglose.html', context)


@login_required
def contabilidad(request):
    if not request.user.is_superuser:
        return redirect('home')

    hoy = timezone.now().date()
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    ingresos_qs = Ingreso.objects.all()
    gastos_qs = Gasto.objects.all()

    ano_sel_int = None
    if ano_seleccionado:
        try:
            ano_sel_int = int(ano_seleccionado)
            ingresos_qs = ingresos_qs.filter(fecha__year=ano_sel_int)
            gastos_qs = gastos_qs.filter(fecha__year=ano_sel_int)
        except (ValueError, TypeError): ano_seleccionado = None
    
    mes_sel_int = None
    if mes_seleccionado:
         try:
            mes_sel_int = int(mes_seleccionado)
            if 1 <= mes_sel_int <= 12:
                ingresos_qs = ingresos_qs.filter(fecha__month=mes_sel_int)
                gastos_qs = gastos_qs.filter(fecha__month=mes_sel_int)
            else: mes_seleccionado = None
         except (ValueError, TypeError): mes_seleccionado = None
    
    total_ingresado = ingresos_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastado = gastos_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia = total_ingresado - total_gastado
    
    context = { 
        'total_ingresado': total_ingresado, 'total_gastado': total_gastado, 'total_ganancia': total_ganancia, 
        'anos_y_meses': anos_y_meses_data, 'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/contabilidad.html', context)

@login_required
def cuentas_por_cobrar(request):
    if not request.user.is_superuser:
        return redirect('home')

    anos_y_meses_data = get_anos_y_meses_con_datos(); anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano'); mes_seleccionado = request.GET.get('mes')
    facturas_qs = Factura.objects.select_related('orden__cliente', 'orden__vehiculo').prefetch_related('orden__ingreso_set')
    
    if ano_seleccionado:
        try: facturas_qs = facturas_qs.filter(fecha_emision__year=int(ano_seleccionado))
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
        try:
            mes = int(mes_seleccionado)
            if 1 <= mes <= 12: facturas_qs = facturas_qs.filter(fecha_emision__month=mes)
            else: mes_seleccionado = None
        except (ValueError, TypeError): mes_seleccionado = None
        
    facturas_pendientes = []; total_pendiente = Decimal('0.00')
    for factura in facturas_qs.order_by('fecha_emision', 'id'):
        abonos = sum(ing.importe for ing in factura.orden.ingreso_set.all()) if hasattr(factura.orden, 'ingreso_set') and factura.orden.ingreso_set.exists() else Decimal('0.00')
        pendiente = factura.total_final - abonos
        if pendiente > Decimal('0.01'):
            facturas_pendientes.append({'factura': factura, 'orden': factura.orden, 'cliente': factura.orden.cliente, 'vehiculo': factura.orden.vehiculo, 'pendiente': pendiente})
            total_pendiente += pendiente
            
    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None; mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None
    context = { 'facturas_pendientes': facturas_pendientes, 'total_pendiente': total_pendiente, 'anos_disponibles': anos_disponibles, 'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13) }
    return render(request, 'taller/cuentas_por_cobrar.html', context)


@login_required
def informe_tarjeta(request):
    if not request.user.is_superuser:
        return redirect('home')

    hoy = timezone.now().date()
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    ingresos_qs = Ingreso.objects.exclude(metodo_pago='EFECTIVO')
    gastos_qs = Gasto.objects.exclude(metodo_pago='EFECTIVO')

    ano_sel_int = None
    if ano_seleccionado:
        try:
            ano_sel_int = int(ano_seleccionado)
            ingresos_qs = ingresos_qs.filter(fecha__year=ano_sel_int)
            gastos_qs = gastos_qs.filter(fecha__year=ano_sel_int)
        except (ValueError, TypeError): ano_seleccionado = None
            
    mes_sel_int = None
    if mes_seleccionado:
         try:
            mes_sel_int = int(mes_seleccionado)
            if 1 <= mes_sel_int <= 12:
                ingresos_qs = ingresos_qs.filter(fecha__month=mes_sel_int)
                gastos_qs = gastos_qs.filter(fecha__month=mes_sel_int)
            else: mes_seleccionado = None
         except (ValueError, TypeError): mes_seleccionado = None
    
    def calcular_tarjeta(tag, limite):
        gastos = gastos_qs.filter(metodo_pago=tag).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        abonos = ingresos_qs.filter(metodo_pago=tag).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        dispuesto = gastos - abonos
        return {'limite': limite, 'dispuesto': dispuesto, 'disponible': limite - dispuesto}

    tarjeta_1 = calcular_tarjeta('TARJETA_1', Decimal('2000.00'))
    tarjeta_2 = calcular_tarjeta('TARJETA_2', Decimal('1000.00'))

    movimientos_bancarios = sorted(
        list(ingresos_qs) + list(gastos_qs), 
        key=lambda mov: (mov.fecha, -mov.id if hasattr(mov, 'id') else 0), 
        reverse=True
    )
    
    cierres = CierreTarjeta.objects.order_by('-fecha_cierre')
    
    context = { 
        'tarjeta_1': tarjeta_1, 'tarjeta_2': tarjeta_2, 'movimientos_bancarios': movimientos_bancarios, 
        'cierres': cierres, 'anos_y_meses': anos_y_meses_data, 'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/informe_tarjeta.html', context)

@login_required
def ver_presupuesto_pdf(request, presupuesto_id):
    presupuesto = get_object_or_404(Presupuesto.objects.select_related('cliente', 'vehiculo').prefetch_related('lineas'), id=presupuesto_id)
    
    # NUEVA LÓGICA DE SEGURIDAD: Solo Jefes pueden ver el PDF con los precios
    if not request.user.is_superuser:
         return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para ver los precios ni descargar el PDF del presupuesto.</p>")

    lineas = presupuesto.lineas.all()
    context = { 
        'presupuesto': presupuesto, 
        'lineas': lineas, 
        'STATIC_URL': settings.STATIC_URL, 
        'logo_path': os.path.join(settings.BASE_DIR, 'taller', 'static', 'taller', 'images', 'logo.jpg') 
    }
    
    template_path = 'taller/plantilla_presupuesto.html'; template = get_template(template_path); html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    matricula_filename = presupuesto.vehiculo.matricula if presupuesto.vehiculo else presupuesto.matricula_nueva if presupuesto.matricula_nueva else 'SIN_VEHICULO'
    cliente_filename = "".join(c if c.isalnum() else "_" for c in presupuesto.cliente.nombre); nombre_archivo = f"presupuesto_{presupuesto.id}_{cliente_filename}_{matricula_filename}.pdf"
    response['Content-Disposition'] = f'inline; filename="{nombre_archivo}"'
    
    def link_callback(uri, rel):
        logo_uri_abs = context.get('logo_path');
        if logo_uri_abs: logo_uri_abs = logo_uri_abs.replace("\\", "/")
        if uri == logo_uri_abs: return logo_uri_abs
        if uri.startswith(settings.STATIC_URL):
            path = uri.replace(settings.STATIC_URL, "", 1)
            for static_dir in settings.STATICFILES_DIRS:
                file_path = os.path.join(static_dir, path)
                if os.path.exists(file_path): return file_path
            if hasattr(settings, 'STATIC_ROOT') and settings.STATIC_ROOT:
                 file_path = os.path.join(settings.STATIC_ROOT, path)
                 if os.path.exists(file_path): return file_path
        if uri.startswith("http://") or uri.startswith("https://"): return uri
        return None
        
    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err: return HttpResponse('Error al generar PDF: <pre>' + html + '</pre>')
    return response

# --- VISTA PARA EL HISTORIAL DETALLADO POR CUENTA ---
@login_required
def historial_cuenta(request, cuenta_nombre):
    if not request.user.is_superuser:
        return redirect('home')

    mapeo_cuentas = {
        'efectivo': ('EFECTIVO', 'Caja (Efectivo)'),
        'banco': ('CUENTA_TALLER', 'Cuenta Taller (Banco)'),
        'tarjeta1': ('TARJETA_1', 'Tarjeta 1 (Visa 2000€)'),
        'tarjeta2': ('TARJETA_2', 'Tarjeta 2 (Visa 1000€)'),
        'erika': ('CUENTA_ERIKA', 'Cuenta Erika (Antigua)'),
    }

    if cuenta_nombre not in mapeo_cuentas: return redirect('home')
    metodo_db, nombre_legible = mapeo_cuentas[cuenta_nombre]

    hoy = timezone.now()
    mes_seleccionado = request.GET.get('mes', str(hoy.month))
    ano_seleccionado = request.GET.get('ano', str(hoy.year))
    concepto_buscado = request.GET.get('concepto', '').upper() 

    ingresos = Ingreso.objects.filter(metodo_pago=metodo_db)
    gastos = Gasto.objects.filter(metodo_pago=metodo_db)

    if mes_seleccionado != 'Todos':
        ingresos = ingresos.filter(fecha__month=int(mes_seleccionado))
        gastos = gastos.filter(fecha__month=int(mes_seleccionado))
    if ano_seleccionado != 'Todos':
        ingresos = ingresos.filter(fecha__year=int(ano_seleccionado))
        gastos = gastos.filter(fecha__year=int(ano_seleccionado))

    if concepto_buscado:
        ingresos = ingresos.filter(descripcion__icontains=concepto_buscado)
        gastos = gastos.filter(descripcion__icontains=concepto_buscado)

    lista_movimientos = []
    for i in ingresos: lista_movimientos.append({'fecha': i.fecha, 'descripcion': i.descripcion, 'importe': i.importe, 'tipo': 'Ingreso', 'categoria': i.get_categoria_display()})
    for g in gastos: lista_movimientos.append({'fecha': g.fecha, 'descripcion': g.descripcion, 'importe': -g.importe, 'tipo': 'Gasto', 'categoria': g.get_categoria_display()})

    movimientos_ordenados = sorted(lista_movimientos, key=lambda x: x['fecha'], reverse=True)

    total_ingresos = sum(m['importe'] for m in movimientos_ordenados if m['tipo'] == 'Ingreso')
    total_gastos = sum(abs(m['importe']) for m in movimientos_ordenados if m['tipo'] == 'Gasto')
    balance_periodo = total_ingresos - total_gastos

    context = {
        'nombre_legible': nombre_legible, 'cuenta_nombre': cuenta_nombre, 'movimientos': movimientos_ordenados,
        'mes_seleccionado': mes_seleccionado, 'ano_seleccionado': ano_seleccionado, 'concepto': request.GET.get('concepto', ''), 
        'total_ingresos': total_ingresos, 'total_gastos': total_gastos, 'balance_periodo': balance_periodo,
        'meses_del_ano': range(1, 13), 'anos_disponibles': range(hoy.year - 2, hoy.year + 2),
    }
    return render(request, 'taller/historial_cuenta.html', context)

# ==============================================================
# --- VISTAS PARA EL TABLÓN DE ANUNCIOS E HISTORIAL ---
# ==============================================================
@login_required
def agregar_nota(request):
    if request.method == 'POST':
        texto = request.POST.get('texto')
        if texto:
            NotaTablon.objects.create(autor=request.user, texto=texto)
    return redirect('home')

@login_required
def completar_nota(request, nota_id):
    nota = get_object_or_404(NotaTablon, id=nota_id)
    # Solo el autor o el jefe pueden marcarla como completada
    if request.user == nota.autor or request.user.is_superuser:
        nota.completada = True
        nota.save()
    return redirect('home')

@login_required
def historial_notas(request):
    # Muestra todas las notas que ya están completadas
    notas = NotaTablon.objects.filter(completada=True).order_by('-fecha_creacion')
    return render(request, 'taller/historial_notas.html', {'notas': notas})