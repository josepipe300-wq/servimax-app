# taller/views.py
# --- LIBRERÍAS ESTÁNDAR DE PYTHON ---
import os
import json
import calendar
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from collections import defaultdict
from urllib.parse import quote
from functools import wraps

# --- LIBRERÍAS DE TERCEROS ---
from xhtml2pdf import pisa
import google.generativeai as genai

# --- CORE DE DJANGO ---
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.template.loader import get_template
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, F, Q
from django.db import transaction
from django.core.signing import Signer, BadSignature

# --- ARCHIVOS LOCALES DE LA APP ---
from . import ai_tools
from .models import (
    Ingreso, Gasto, Cliente, Vehiculo, OrdenDeReparacion, Empleado,
    TipoConsumible, CompraConsumible, Factura, LineaFactura, FotoVehiculo,
    Presupuesto, LineaPresupuesto, UsoConsumible, AjusteStockConsumible,
    CierreTarjeta, NotaTablon, NotaInternaOrden, DeudaTaller, AmpliacionDeuda, 
    HistorialEstadoOrden, Cita, HistorialIA, ReporteEscaner,
    Asistencia, AdelantoSueldo # <- Los nuevos de Recursos Humanos
)


def obtener_dias_laborables_mes(fecha):
    """Calcula cuántos días de Lunes a Viernes tiene el mes de la fecha dada"""
    dias_en_mes = calendar.monthrange(fecha.year, fecha.month)[1]
    dias_laborables = 0
    for dia in range(1, dias_en_mes + 1):
        # weekday() devuelve 0 para Lunes, 1 Martes... 4 Viernes.
        if calendar.weekday(fecha.year, fecha.month, dia) < 5:
            dias_laborables += 1
    return Decimal(str(dias_laborables))

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


@login_required
def home(request):
    hoy = timezone.now()
    hoy_date = hoy.date()

    # --- Lógica de Filtros por Fecha ---
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
    
    # --- Datos de Ingresos y Gastos ---
    ingresos_mes = Ingreso.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    gastos_mes = Gasto.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    
    total_ingresos = ingresos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos = gastos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

    # --- Balances de Cuentas ---
    ing_efectivo = Ingreso.objects.filter(metodo_pago='EFECTIVO').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gas_efectivo = Gasto.objects.filter(metodo_pago='EFECTIVO').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_efectivo = ing_efectivo - gas_efectivo

    ing_taller = Ingreso.objects.filter(metodo_pago='CUENTA_TALLER').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gas_taller = Gasto.objects.filter(metodo_pago='CUENTA_TALLER').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_taller = ing_taller - gas_taller

    # --- Balances de Tarjetas ---
    def obtener_disponible_tarjeta(nombre_metodo, limite):
        ing = Ingreso.objects.filter(metodo_pago=nombre_metodo).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        gas = Gasto.objects.filter(metodo_pago=nombre_metodo).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        return limite + (ing - gas)

    tarjeta_1 = {'disponible': obtener_disponible_tarjeta('TARJETA_1', Decimal('2000.00'))}
    tarjeta_2 = {'disponible': obtener_disponible_tarjeta('TARJETA_2', Decimal('1000.00'))}

    # --- CITAS PARA EL RECORDATORIO DE HOY ---
    citas_hoy = Cita.objects.filter(
        fecha_hora__date=hoy_date,
        estado='Pendiente'
    ).order_by('fecha_hora')

    # --- Alertas de Stock ---
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

    # --- DEUDA DE NÓMINAS PENDIENTES ---
    total_deuda_nominas = Decimal('0.00')
    empleados_taller = Empleado.objects.all()
    for emp in empleados_taller:
        dias_pendientes = Asistencia.objects.filter(
            empleado=emp, pagado=False, hora_salida__isnull=False
        ).values('fecha').distinct().count()
        
        # --- CÁLCULO INTELIGENTE ---
        if emp.es_sueldo_fijo:
            dias_laborables_mes = obtener_dias_laborables_mes(hoy_date)
            sueldo_bruto = Decimal(dias_pendientes) * (emp.sueldo_fijo_mensual / dias_laborables_mes)
        else:
            sueldo_bruto = dias_pendientes * emp.sueldo_por_dia
        
        adelantos_pendientes = AdelantoSueldo.objects.filter(empleado=emp, liquidado=False)
        total_adelantos = sum(a.importe for a in adelantos_pendientes)
        
        neto_a_pagar = sueldo_bruto - total_adelantos
        if neto_a_pagar > 0:
            total_deuda_nominas += neto_a_pagar

    # --- Otros Datos Generales ---
    notas_tablon = NotaTablon.objects.filter(completada=False).order_by('-fecha_creacion')[:20]
    is_read_only_user = request.user.groups.filter(name='Solo Ver').exists()
    
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)

    ultimos_gastos = Gasto.objects.order_by('-id')[:5]
    ultimos_ingresos = Ingreso.objects.order_by('-id')[:5]
    movimientos_combinados = sorted(
        list(ultimos_gastos) + list(ultimos_ingresos),
        key=lambda mov: mov.fecha if hasattr(mov, 'fecha') else hoy_date,
        reverse=True
    )
    movimientos_recientes = movimientos_combinados[:5]

    context = {
        'total_ingresos': total_ingresos,
        'total_gastos': total_gastos,
        'balance_efectivo': balance_efectivo,
        'balance_taller': balance_taller,
        'tarjeta_1': tarjeta_1,
        'tarjeta_2': tarjeta_2,
        'citas_hoy_recordatorio': citas_hoy,
        'movimientos_recientes': movimientos_recientes,
        'alertas_stock': alertas_stock,
        'total_deuda_nominas': total_deuda_nominas,
        'is_read_only_user': is_read_only_user,
        'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_actual,
        'mes_seleccionado': mes_actual,
        'meses_del_ano': range(1, 13),
        'notas_tablon': notas_tablon,
        'taller_cerrado': HistorialEstadoOrden.objects.filter(es_pausa_jornada=True, fecha_fin__isnull=True).exists()
    }
    
    return render(request, 'taller/home.html', context)


@login_required
@bloquear_lectura 
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

@login_required
@bloquear_lectura 
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

@login_required
@bloquear_lectura 
def ingresar_vehiculo(request):
    if not (request.user.is_superuser or request.user.has_perm('taller.add_ordendereparacion')):
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para ingresar vehículos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if request.method == 'POST':
        cliente_id = request.POST.get('cliente_existente')
        
        nombre_cliente = request.POST.get('cliente_nombre', '').upper()
        telefono_cliente = request.POST.get('cliente_telefono', '')
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
        
        danos_previos = request.POST.get('danos_previos', '').upper()

        with transaction.atomic():
            if cliente_id:
                try:
                    cliente = Cliente.objects.get(id=cliente_id)
                    cliente.nombre = nombre_cliente
                    if telefono_cliente: cliente.telefono = telefono_cliente
                    cliente.tipo_documento = tipo_documento
                    cliente.documento_fiscal = documento_fiscal
                    cliente.direccion_fiscal = direccion_fiscal
                    cliente.codigo_postal_fiscal = codigo_postal_fiscal
                    cliente.ciudad_fiscal = ciudad_fiscal
                    cliente.provincia_fiscal = provincia_fiscal
                    cliente.save()
                except Cliente.DoesNotExist:
                    cliente, created = Cliente.objects.get_or_create(telefono=telefono_cliente, defaults={'nombre': nombre_cliente})
            else:
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

            nueva_orden = OrdenDeReparacion.objects.create(
                cliente=cliente, vehiculo=vehiculo, problema=problema_reportado, 
                presupuesto_origen=presupuesto, danos_previos=danos_previos
            )
            if presupuesto:
                presupuesto.estado = 'Convertido'; presupuesto.save()

            descripciones = ['Frontal', 'Trasera', 'Lateral Izquierdo', 'Lateral Derecho', 'Cuadro/Km']
            for i in range(1, 6):
                foto_campo = f'foto{i}'
                if foto_campo in request.FILES:
                    FotoVehiculo.objects.create(orden=nueva_orden, imagen=request.FILES[foto_campo], descripcion=descripciones[i-1])
            
            fotos_danos = request.FILES.getlist('fotos_danos')
            for index, foto in enumerate(fotos_danos):
                FotoVehiculo.objects.create(
                    orden=nueva_orden, 
                    imagen=foto, 
                    descripcion=f"DAÑO PREVIO {index + 1}"
                )

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
        
    clientes = Cliente.objects.all().order_by('nombre')
    clientes_con_datos = []
    for cliente in clientes:
        clientes_con_datos.append({
            'cliente': cliente,
            'cliente_data_json': json.dumps({
                'nombre': cliente.nombre or '',
                'telefono': cliente.telefono or '',
                'tipo_documento': cliente.tipo_documento or 'DNI', 
                'documento_fiscal': cliente.documento_fiscal or '',
                'direccion_fiscal': cliente.direccion_fiscal or '', 
                'codigo_postal_fiscal': cliente.codigo_postal_fiscal or '',
                'ciudad_fiscal': cliente.ciudad_fiscal or '', 
                'provincia_fiscal': cliente.provincia_fiscal or ''
            })
        })
        
    context = { 
        'presupuestos_disponibles_data': presupuestos_con_datos_fiscales,
        'clientes_data': clientes_con_datos
    }
    return render(request, 'taller/ingresar_vehiculo.html', context)

@login_required
def anadir_gasto(request):
    if request.user.groups.filter(name='Solo Ver').exists():
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Tu cuenta está en 'Modo Lectura'.</p><br><a href='/'>← Volver</a>")

    if request.method == 'POST':
        metodo_pago = request.POST.get('metodo_pago')
        categoria = request.POST.get('categoria')

        if categoria == 'Compra de Consumibles':
            tipo_id = request.POST.get('tipo_consumible')
            fecha_str = request.POST.get('fecha_compra')
            cantidad = request.POST.get('cantidad')
            coste_total = request.POST.get('coste_total')

            if not all([tipo_id, fecha_str, cantidad, coste_total]):
                return HttpResponse("Todos los campos de consumible son obligatorios.")

            try:
                tipo = TipoConsumible.objects.get(id=tipo_id)
                cantidad_decimal = Decimal(cantidad.replace(',', '.'))
                coste_total_decimal = Decimal(coste_total.replace(',', '.'))
                fecha_compra = datetime.strptime(fecha_str, '%Y-%m-%d').date()

                CompraConsumible.objects.create(
                    tipo=tipo, fecha_compra=fecha_compra,
                    cantidad=cantidad_decimal, coste_total=coste_total_decimal
                )
                
                Gasto.objects.create(
                    fecha=fecha_compra, categoria=categoria,
                    importe=coste_total_decimal, descripcion=f"Compra de {cantidad_decimal} {tipo.unidad_medida} de {tipo.nombre}",
                    metodo_pago=metodo_pago
                )
            except (ValueError, TypeError, TipoConsumible.DoesNotExist):
                return HttpResponse("Error en los datos de la compra de consumible.")
            
            return redirect('home') 

        else:
            fecha_str = request.POST.get('fecha_gasto')
            importe = request.POST.get('importe')
            descripcion = request.POST.get('descripcion')
            orden_id = request.POST.get('orden')
            empleado_id = request.POST.get('empleado')
            deuda_id = request.POST.get('deuda')

            if not importe or not descripcion:
                return HttpResponse("Faltan campos obligatorios para el gasto.")

            fecha_gasto = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else timezone.now().date()
            importe_decimal = Decimal(importe.replace(',', '.'))
            
            orden = None
            vehiculo = None
            if (categoria in ['Repuestos', 'Otros', 'Pago de Deuda']) and orden_id:
                try:
                    orden = OrdenDeReparacion.objects.get(id=orden_id)
                    vehiculo = orden.vehiculo
                except OrdenDeReparacion.DoesNotExist:
                    pass

            empleado = None
            if categoria == 'Sueldos' and empleado_id:
                try:
                    empleado = Empleado.objects.get(id=empleado_id)
                except Empleado.DoesNotExist:
                    pass
            
            if categoria == 'PAGO_TARJETA':
                tarjeta_destino = request.POST.get('tarjeta_destino')
                saldo_real_str = request.POST.get('saldo_real_banco')
                
                if tarjeta_destino and saldo_real_str:
                    saldo_real_banco = Decimal(saldo_real_str.replace(',', '.'))
                    
                    gastos_tarjeta = Gasto.objects.filter(metodo_pago=tarjeta_destino).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
                    abonos_tarjeta = Ingreso.objects.filter(metodo_pago=tarjeta_destino).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
                    deuda_app_antes = gastos_tarjeta - abonos_tarjeta
                    deuda_app_despues = deuda_app_antes - importe_decimal
                    intereses = saldo_real_banco - deuda_app_despues
                    
                    with transaction.atomic():
                        Gasto.objects.create(
                            metodo_pago=metodo_pago, fecha=fecha_gasto, categoria='PAGO_TARJETA',
                            importe=importe_decimal, descripcion=descripcion, empleado=empleado
                        )
                        Ingreso.objects.create(
                            metodo_pago=tarjeta_destino, fecha=fecha_gasto, categoria='ABONO_TARJETA',
                            importe=importe_decimal, descripcion=f"ABONO DESDE {metodo_pago} - {descripcion}",
                            es_tpv=False
                        )
                        if intereses > 0:
                            Gasto.objects.create(
                                metodo_pago=tarjeta_destino, fecha=fecha_gasto, categoria='COMISIONES_INTERESES',
                                importe=intereses, descripcion=f"INTERESES/COMISIONES - {descripcion}", empleado=empleado
                            )
                        CierreTarjeta.objects.create(
                            fecha_cierre=fecha_gasto, tarjeta=tarjeta_destino, 
                            pago_cuota=importe_decimal, saldo_deuda_banco=saldo_real_banco, 
                            intereses_calculados=intereses if intereses > 0 else Decimal('0.00')
                        )
                    return redirect('home')

            deuda_taller = None
            if categoria == 'Pago de Deuda' and deuda_id:
                try:
                    deuda_taller = DeudaTaller.objects.get(id=deuda_id)
                    if deuda_taller.es_credito_bancario:
                        saldo_real_str = request.POST.get('saldo_real_banco')
                        if saldo_real_str:
                            saldo_real_banco = Decimal(saldo_real_str.replace(',', '.'))
                            amortizacion = deuda_taller.importe_pendiente - saldo_real_banco
                            intereses = importe_decimal - amortizacion
                            
                            if intereses >= 0 and amortizacion >= 0:
                                with transaction.atomic():
                                    Gasto.objects.create(
                                        metodo_pago=metodo_pago, fecha=fecha_gasto, categoria='Pago de Deuda',
                                        importe=amortizacion, descripcion=f"AMORTIZACIÓN DE PRINCIPAL - {descripcion}",
                                        orden=orden, vehiculo=vehiculo, empleado=empleado, deuda_asociada=deuda_taller
                                    )
                                    Gasto.objects.create(
                                        metodo_pago=metodo_pago, fecha=fecha_gasto, categoria='COMISIONES_INTERESES',
                                        importe=intereses, descripcion=f"INTERESES BANCARIOS ({deuda_taller.acreedor}) - {descripcion}",
                                        orden=orden, vehiculo=vehiculo, empleado=empleado, deuda_asociada=None
                                    )
                                return redirect('home')
                except DeudaTaller.DoesNotExist:
                    pass

            Gasto.objects.create(
                metodo_pago=metodo_pago, fecha=fecha_gasto, categoria=categoria,
                importe=importe_decimal, descripcion=descripcion,
                orden=orden, vehiculo=vehiculo, empleado=empleado, deuda_asociada=deuda_taller
            )
            
            return redirect('home')

    ordenes_activas = OrdenDeReparacion.objects.exclude(estado='Entregado')
    empleados = Empleado.objects.all()
    tipos_consumible = TipoConsumible.objects.all()
    deudas_pendientes = [d for d in DeudaTaller.objects.all() if d.estado == 'Pendiente']

    context = {
        'metodos_pago': Gasto.METODO_PAGO_CHOICES,
        'categorias_gasto': Gasto.CATEGORIA_CHOICES,
        'ordenes_activas': ordenes_activas,
        'empleados': empleados,
        'tipos_consumible': tipos_consumible,
        'deudas_pendientes': deudas_pendientes
    }
    return render(request, 'taller/anadir_gasto.html', context)


@login_required
@bloquear_lectura 
def registrar_ingreso(request):
    if not (request.user.is_superuser or request.user.has_perm('taller.add_ingreso')):
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para acceder a la gestión de ingresos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if request.method == 'POST':
        categoria = request.POST['categoria']
        importe_str = request.POST.get('importe')
        descripcion = request.POST.get('descripcion', '')
        metodo_pago = request.POST.get('metodo_pago', 'EFECTIVO')
        es_tpv_bool = (metodo_pago != 'EFECTIVO')

        fecha_ingreso_str = request.POST.get('fecha_ingreso')
        try: 
            fecha_ingreso = datetime.strptime(fecha_ingreso_str, '%Y-%m-%d').date() if fecha_ingreso_str else timezone.now().date()
        except ValueError: 
            fecha_ingreso = timezone.now().date()
            
        try:
            importe = Decimal(importe_str) if importe_str else Decimal('0.00')
            if importe <= 0: return redirect('registrar_ingreso')
        except (ValueError, TypeError, Decimal.InvalidOperation): 
            return redirect('registrar_ingreso')

        ingreso = Ingreso(
            fecha=fecha_ingreso, 
            categoria=categoria, 
            importe=importe, 
            descripcion=descripcion.upper(), 
            es_tpv=es_tpv_bool, 
            metodo_pago=metodo_pago
        )

        if categoria == 'Taller':
            orden_id = request.POST.get('orden')
            if orden_id:
                ordenes_relevantes = obtener_ordenes_relevantes()
                try:
                    orden_seleccionada = ordenes_relevantes.get(id=orden_id)
                    ingreso.orden = orden_seleccionada
                except OrdenDeReparacion.DoesNotExist: 
                    pass
        
        es_prestamo = (categoria == 'PRESTAMO')
        if es_prestamo:
            deuda_existente_id = request.POST.get('deuda_existente')
            
            if deuda_existente_id == 'NUEVA':
                nuevo_acreedor = request.POST.get('nueva_deuda_acreedor', '').upper()
                if nuevo_acreedor:
                    nueva_deuda = DeudaTaller.objects.create(
                        acreedor=nuevo_acreedor,
                        motivo=f"PRÉSTAMO INICIAL: {descripcion.upper()}",
                        importe_inicial=importe,
                        fecha_creacion=fecha_ingreso
                    )
                    ingreso.deuda_asociada = nueva_deuda

            elif deuda_existente_id:
                try:
                    deuda_guardada = DeudaTaller.objects.get(id=deuda_existente_id)
                    AmpliacionDeuda.objects.create(
                        deuda=deuda_guardada,
                        importe=importe,
                        motivo=f"NUEVO PRÉSTAMO REGISTRADO: {descripcion.upper()}"
                    )
                    deuda_guardada.importe_inicial += importe
                    deuda_guardada.save()
                    ingreso.deuda_asociada = deuda_guardada
                except DeudaTaller.DoesNotExist:
                    pass

        ingreso.save()
        return redirect('home')

    ordenes_filtradas = obtener_ordenes_relevantes().order_by('-fecha_entrada')
    categorias_ingreso = Ingreso.CATEGORIA_CHOICES
    metodos_pago = Ingreso.METODO_PAGO_CHOICES 
    deudas_taller = DeudaTaller.objects.all().order_by('acreedor')

    context = { 
        'ordenes': ordenes_filtradas, 
        'categorias_ingreso': categorias_ingreso, 
        'metodos_pago': metodos_pago,
        'deudas_taller': deudas_taller 
    }
    return render(request, 'taller/registrar_ingreso.html', context)


@login_required
@bloquear_lectura 
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

@login_required
@bloquear_lectura 
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

@login_required
def lista_presupuestos(request):
    if request.method == 'POST' and 'borrar_presupuesto' in request.POST:
        if request.user.groups.filter(name='Solo Ver').exists() or not request.user.is_superuser:
            return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para borrar presupuestos.</p>")
        
        presupuesto_id = request.POST.get('presupuesto_id')
        try:
            presupuesto_a_borrar = Presupuesto.objects.get(id=presupuesto_id)
            presupuesto_a_borrar.delete()
        except Presupuesto.DoesNotExist:
            pass
        return redirect('lista_presupuestos')

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

@login_required
def detalle_presupuesto(request, presupuesto_id):
    presupuesto = get_object_or_404(Presupuesto.objects.select_related('cliente', 'vehiculo').prefetch_related('lineas'), id=presupuesto_id)

    if request.method == 'POST' and 'nuevo_estado' in request.POST:
        if request.user.groups.filter(name='Solo Ver').exists():
            return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Tu cuenta está en 'Modo Lectura'. No tienes permiso para modificar datos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

        nuevo_estado = request.POST['nuevo_estado']
        estados_validos_cambio = ['Aceptado', 'Rechazado', 'Pendiente']
        if nuevo_estado in estados_validos_cambio and presupuesto.estado != 'Convertido':
            presupuesto.estado = nuevo_estado
            presupuesto.save()
            return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)

    orden_generada = OrdenDeReparacion.objects.filter(presupuesto_origen=presupuesto).first()
    
    try:
        estados_posibles = Presupuesto.ESTADO_CHOICES
    except AttributeError:
        estados_posibles = [('Pendiente', 'Pendiente'), ('Aceptado', 'Aceptado'), ('Rechazado', 'Rechazado'), ('Convertido', 'Convertido')]

    context = { 
        'presupuesto': presupuesto, 
        'lineas': presupuesto.lineas.all(), 
        'estados_posibles': estados_posibles, 
        'orden_generada': orden_generada 
    }
    return render(request, 'taller/detalle_presupuesto.html', context)

@login_required
@bloquear_lectura 
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
                
                if cliente:
                    if nombre_cliente_form: cliente.nombre = nombre_cliente_form
                    if telefono_cliente_form: cliente.telefono = telefono_cliente_form
                    cliente.tipo_documento = tipo_documento
                    cliente.documento_fiscal = documento_fiscal
                    cliente.direccion_fiscal = direccion_fiscal
                    cliente.codigo_postal_fiscal = codigo_postal_fiscal
                    cliente.ciudad_fiscal = ciudad_fiscal
                    cliente.provincia_fiscal = provincia_fiscal
                    cliente.save()
                else:
                    raise ValueError("Cliente inválido")

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


# ==========================================
# --- NUEVA LÓGICA DE LISTA DE ÓRDENES ---
# ==========================================
@login_required
def lista_ordenes(request):
    if request.method == 'POST':
        if not request.user.is_superuser:
            return HttpResponseForbidden("🔒 Acceso denegado. Solo Administración puede cambiar el tipo de vehículo.")
            
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

    ordenes_activas = OrdenDeReparacion.objects.exclude(estado='Entregado').select_related('vehiculo', 'cliente')
    
    ordenes_clientes = ordenes_activas.filter(trabajo_interno=False)
    flota_interna = ordenes_activas.filter(trabajo_interno=True).order_by('id')
    
    ordenes_taller = ordenes_clientes.filter(estado__in=['Recibido', 'En Diagnostico', 'Esperando Piezas', 'En Reparacion', 'En Pruebas']).order_by('id')
    ordenes_pausadas = ordenes_clientes.filter(estado='Esperando Autorizacion').order_by('id')
    ordenes_listas = ordenes_clientes.filter(estado='Listo para Recoger').order_by('id')

    return render(request, 'taller/lista_ordenes.html', {
        'ordenes_taller': ordenes_taller,
        'ordenes_pausadas': ordenes_pausadas,
        'ordenes_listas': ordenes_listas,
        'flota_interna': flota_interna,
        'taller_cerrado': HistorialEstadoOrden.objects.filter(es_pausa_jornada=True, fecha_fin__isnull=True).exists()
    })

@login_required
def detalle_orden(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('cliente', 'vehiculo', 'presupuesto_origen').prefetch_related('fotos', 'ingreso_set', 'gastos', 'factura', 'notas_internas'), id=orden_id)
    repuestos = orden.gastos.filter(categoria='Repuestos')
    gastos_otros = orden.gastos.filter(categoria='Otros')
    
    abonos_ingresos = sum(ing.importe for ing in orden.ingreso_set.all()) if hasattr(orden, 'ingreso_set') and orden.ingreso_set.exists() else Decimal('0.00')
    abonos_deuda = sum(g.importe for g in orden.gastos.all() if g.categoria == 'Pago de Deuda')
    abonos = abonos_ingresos + abonos_deuda
    
    tipos_consumible = TipoConsumible.objects.all()
    
    factura = None; pendiente_pago = Decimal('0.00'); whatsapp_url = None 
    
    # ==============================================================
    # --- NUEVO: ENLACE MÁGICO DEL ESTADO DEL COCHE PARA WHATSAPP ---
    # ==============================================================
    signer = Signer()
    signed_orden_id = signer.sign(orden.id)
    url_estado_publico = request.build_absolute_uri(reverse('estado_vehiculo_publico', args=[signed_orden_id]))
    
    whatsapp_estado_url = None
    if orden.cliente.telefono:
        telefono_limpio_estado = "".join(filter(str.isdigit, orden.cliente.telefono))
        if not telefono_limpio_estado.startswith('34') and len(telefono_limpio_estado) == 9: 
            telefono_limpio_estado = '34' + telefono_limpio_estado
        mensaje_estado = f"Hola {orden.cliente.nombre}, somos el taller ServiMax 🔧.\n\nAquí tienes un enlace seguro para consultar el estado de tu {orden.vehiculo.marca} y ver las fotos de la reparación en tiempo real:\n\n{url_estado_publico}\n\n¡Gracias por confiar en nosotros!"
        whatsapp_estado_url = f"https://wa.me/{telefono_limpio_estado}?text={quote(mensaje_estado)}"
    # ==============================================================

    if request.user.is_superuser:
        try: 
            factura = orden.factura
            pendiente_pago = factura.total_final - abonos
            
            if orden.cliente.telefono:
                signer_fac = Signer(); signed_id = signer_fac.sign(factura.id) 
                public_url = request.build_absolute_uri(reverse('ver_factura_publica', args=[signed_id]))
                telefono_limpio = "".join(filter(str.isdigit, orden.cliente.telefono))
                if not telefono_limpio.startswith('34') and len(telefono_limpio) == 9: telefono_limpio = '34' + telefono_limpio
                tipo_doc = "factura" if factura.es_factura else "recibo"
                mensaje = f"Hola {orden.cliente.nombre}, aquí tienes el enlace para descargar tu {tipo_doc} del taller:\n\n{public_url}\n\n¡Gracias por confiar en ServiMax!"
                mensaje_encoded = quote(mensaje); whatsapp_url = f"https://wa.me/{telefono_limpio}?text={mensaje_encoded}"
        except Factura.DoesNotExist: pass

    if request.method == 'POST':
        if request.user.groups.filter(name='Solo Ver').exists():
            return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2>")

        form_type = request.POST.get('form_type')

        if form_type == 'estado':
            nuevo_estado = request.POST.get('nuevo_estado')
            if nuevo_estado in [choice[0] for choice in OrdenDeReparacion.ESTADO_CHOICES]:
                orden._usuario_actual = request.user
                orden.estado = nuevo_estado
                orden.save()
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
            
        elif form_type == 'nota_interna':
            texto_nota = request.POST.get('texto_nota')
            imagen_nota = request.FILES.get('imagen_nota') 
            
            if texto_nota:
                NotaInternaOrden.objects.create(
                    orden=orden, 
                    autor=request.user, 
                    texto=texto_nota,
                    imagen=imagen_nota 
                )
            return redirect('detalle_orden', orden_id=orden.id)

        # --- AÑADIDO: BOTÓN MÁGICO PARA MOSTRAR LA NOTA AL CLIENTE ---
        elif form_type == 'toggle_visibilidad_nota':
            nota_id = request.POST.get('nota_id')
            try:
                nota = NotaInternaOrden.objects.get(id=nota_id, orden=orden)
                nota.visible_cliente = not nota.visible_cliente
                nota.save()
            except NotaInternaOrden.DoesNotExist:
                pass
            return redirect('detalle_orden', orden_id=orden.id)
        
        elif form_type == 'registrar_pago':
            importe = Decimal(request.POST.get('importe_pago', '0'))
            metodo = request.POST.get('metodo_pago')
            deuda_id = request.POST.get('deuda_id')
            empleado_id = request.POST.get('empleado_id') # NUEVO CAMPO PARA NÓMINAS
            
            if importe > 0:
                with transaction.atomic():
                    # 1. Ingreso de la orden (queda pagada)
                    Ingreso.objects.create(
                        fecha=timezone.now().date(), categoria='Taller', importe=importe,
                        descripcion=f"COBRO FACTURA {orden.vehiculo.matricula}", metodo_pago=metodo,
                        orden=orden, es_tpv=(metodo not in ['EFECTIVO', 'COMPENSACION'])
                    )
                    
                    # 2. Lógica mágica de Compensación Doble
                    if metodo == 'COMPENSACION':
                        if deuda_id: # Opción 1: Compensar deuda del taller
                            try:
                                deuda_taller = DeudaTaller.objects.get(id=deuda_id)
                                Gasto.objects.create(
                                    fecha=timezone.now().date(), categoria='Pago de Deuda', importe=importe,
                                    descripcion=f"COMPENSACIÓN POR REPARACIÓN {orden.vehiculo.matricula}",
                                    metodo_pago='COMPENSACION', orden=orden, deuda_asociada=deuda_taller
                                )
                            except DeudaTaller.DoesNotExist: pass
                            
                        elif empleado_id: # Opción 2: Descontar de nómina
                            try:
                                empleado_comp = Empleado.objects.get(id=empleado_id)
                                # Le inyectamos el adelanto
                                AdelantoSueldo.objects.create(
                                    empleado=empleado_comp, importe=importe,
                                    motivo=f"REPARACIÓN PROPIA: {orden.vehiculo.matricula} (Ord. #{orden.id})"
                                )
                                # Compensamos el gasto en caja
                                Gasto.objects.create(
                                    fecha=timezone.now().date(), categoria='Sueldos', importe=importe,
                                    descripcion=f"ADELANTO NÓMINA (REPARACIÓN {orden.vehiculo.matricula})",
                                    metodo_pago='COMPENSACION', orden=orden, empleado=empleado_comp
                                )
                            except Empleado.DoesNotExist: pass

            return redirect('detalle_orden', orden_id=orden.id)

    metodos_pago = Ingreso.METODO_PAGO_CHOICES
    deudas_pendientes = [d for d in DeudaTaller.objects.all() if d.estado == 'Pendiente']

    context = {
        'orden': orden, 'repuestos': repuestos, 'gastos_otros': gastos_otros, 'factura': factura,
        'abonos': abonos, 'pendiente_pago': pendiente_pago, 'tipos_consumible': tipos_consumible,
        'fotos': orden.fotos.all(), 'estados_orden': OrdenDeReparacion.ESTADO_CHOICES, 
        'whatsapp_url': whatsapp_url,
        'whatsapp_estado_url': whatsapp_estado_url,
        'notas_internas': orden.notas_internas.all().order_by('-fecha_creacion'),
        'metodos_pago': metodos_pago, 'deudas_pendientes': deudas_pendientes,
        'empleados_taller': Empleado.objects.all()
    }
    return render(request, 'taller/detalle_orden.html', context)
    
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


@login_required
def historial_movimientos(request):
    from django.utils import timezone
    from django.db.models.functions import ExtractYear
    from django.db.models import Q  
    from decimal import Decimal     

    tipo_seleccionado = request.GET.get('tipo', '')
    ano_seleccionado = request.GET.get('ano', '')
    mes_seleccionado = request.GET.get('mes', '')
    matricula_seleccionada = request.GET.get('matricula', '')
    
    buscar_seleccionado = request.GET.get('buscar', '').strip() 

    gastos_qs = Gasto.objects.select_related('orden', 'orden__vehiculo', 'deuda_asociada').all()
    ingresos_qs = Ingreso.objects.select_related('orden', 'orden__vehiculo').all()

    if ano_seleccionado and ano_seleccionado.isdigit():
        gastos_qs = gastos_qs.filter(fecha__year=int(ano_seleccionado))
        ingresos_qs = ingresos_qs.filter(fecha__year=int(ano_seleccionado))
        
    if mes_seleccionado and mes_seleccionado.isdigit():
        gastos_qs = gastos_qs.filter(fecha__month=int(mes_seleccionado))
        ingresos_qs = ingresos_qs.filter(fecha__month=int(mes_seleccionado))

    if matricula_seleccionada:
        gastos_qs = gastos_qs.filter(orden__vehiculo__matricula__icontains=matricula_seleccionada)
        ingresos_qs = ingresos_qs.filter(orden__vehiculo__matricula__icontains=matricula_seleccionada)

    # =========================================================
    # EL MOTOR DE BÚSQUEDA DE J.A.R.V.I.S.
    # =========================================================
    if buscar_seleccionado:
        es_numero = False
        try:
            cantidad = Decimal(buscar_seleccionado.replace(',', '.').replace('€', '').replace('euros', '').strip())
            es_numero = True
        except:
            pass
            
        if es_numero:
            gastos_qs = gastos_qs.filter(Q(importe=cantidad) | Q(descripcion__icontains=buscar_seleccionado))
            ingresos_qs = ingresos_qs.filter(Q(importe=cantidad) | Q(descripcion__icontains=buscar_seleccionado))
        else:
            gastos_qs = gastos_qs.filter(descripcion__icontains=buscar_seleccionado)
            ingresos_qs = ingresos_qs.filter(descripcion__icontains=buscar_seleccionado)
    # =========================================================

    movimientos = []
    if tipo_seleccionado in ['', 'gasto']:
        for g in gastos_qs:
            g.tipo = 'gasto'
            movimientos.append(g)
            
    if tipo_seleccionado in ['', 'ingreso']:
        for i in ingresos_qs:
            i.tipo = 'ingreso'
            movimientos.append(i)

    movimientos.sort(key=lambda x: (x.fecha, x.id), reverse=True)

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
        'matricula_seleccionada': matricula_seleccionada,
        'buscar_seleccionado': buscar_seleccionado, 
        'anos_disponibles': anos_disponibles,
    }
    return render(request, 'taller/historial_movimientos.html', context)

@login_required
@bloquear_lectura 
def editar_movimiento(request, tipo, movimiento_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>No tienes permiso para editar movimientos.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    if tipo not in ['gasto', 'ingreso']: return redirect('historial_movimientos')
    admin_url_name = f'admin:taller_{tipo}_change'
    try: admin_url = reverse(admin_url_name, args=[movimiento_id]); return redirect(admin_url)
    except Exception as e: return redirect(f'/admin/taller/{tipo}/{movimiento_id}/change/')

@login_required
@bloquear_lectura
def eliminar_movimiento(request, tipo, movimiento_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden("🔒 Acceso denegado.")
        
    if request.method == 'POST':
        if tipo == 'gasto':
            movimiento = get_object_or_404(Gasto, id=movimiento_id)
            movimiento.delete() 
        elif tipo == 'ingreso':
            movimiento = get_object_or_404(Ingreso, id=movimiento_id)
            movimiento.delete()
            
    return redirect('historial_movimientos')


@login_required
@bloquear_lectura 
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

            descripciones_grua = request.POST.getlist('grua_desc')
            importes_grua = request.POST.getlist('grua_importe')
            for desc, importe_str in zip(descripciones_grua, importes_grua):
                if desc and importe_str:
                    try:
                        importe = Decimal(importe_str)
                        if importe <= 0: continue
                        subtotal += importe
                        LineaFactura.objects.create(factura=factura, tipo='Grúa', descripcion=desc.upper(), cantidad=1, precio_unitario=importe)
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
@bloquear_lectura 
def editar_factura(request, factura_id):
    if not request.user.is_superuser:
        return HttpResponseForbidden("<h2>🔒 ACCESO DENEGADO</h2><p>Solo Administración puede editar facturas.</p><br><a href='/' style='padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;'>← Volver al Inicio</a>")

    import json
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
        linea_data = { 
            'tipo': linea.tipo, 
            'descripcion': linea.descripcion, 
            'cantidad': float(linea.cantidad), 
            'precio_unitario': float(linea.precio_unitario),
            'tipo_consumible_id': None, 
            'repuesto_id': None, 
            'externo_id': None 
        }
        
        if linea.tipo == 'Consumible':
            tipo_obj = TipoConsumible.objects.filter(nombre__iexact=linea.descripcion).first()
            linea_data['tipo_consumible_id'] = tipo_obj.id if tipo_obj else None
        elif linea.tipo == 'Repuesto':
            gasto_obj = repuestos_qs.filter(descripcion__iexact=linea.descripcion).first()
            linea_data['repuesto_id'] = gasto_obj.id if gasto_obj else None
        elif linea.tipo == 'Externo':
            gasto_obj = gastos_otros_qs.filter(descripcion__iexact=linea.descripcion).first()
            linea_data['externo_id'] = gasto_obj.id if gasto_obj else None
            
        elif linea.tipo == 'Grúa':
            linea_data['tipo'] = 'Grúa'
            
        lineas_existentes_list.append(linea_data)
        
    context = { 
        'orden': orden, 
        'factura_existente': factura, 
        'repuestos': repuestos_qs, 
        'gastos_otros': gastos_otros_qs, 
        'tipos_consumible': tipos_consumible, 
        'lineas_existentes_json': json.dumps(lineas_existentes_list) 
    }
    return render(request, 'taller/editar_factura.html', context)


@login_required
def informe_rentabilidad(request):
    if not request.user.is_superuser:
        return redirect('home')

    from django.db.models import Sum
    from decimal import Decimal
    from django.utils import timezone

    hoy = timezone.now().date()
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    facturas_qs = Factura.objects.select_related('orden__vehiculo').prefetch_related('lineas')
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
    
    total_ganancia_mo = Decimal('0.00')
    total_ganancia_piezas = Decimal('0.00')
    ganancia_grua_facturada = Decimal('0.00')
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
        
        gastos_orden_qs = Gasto.objects.filter(orden=orden)
        coste_repuestos = gastos_orden_qs.filter(categoria='Repuestos').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        coste_externos = gastos_orden_qs.filter(categoria='Otros').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        coste_consumibles_factura = Decimal('0.00')
        
        pvp_mo = Decimal('0.00')
        pvp_piezas = Decimal('0.00')
        grua_en_esta_factura = Decimal('0.00')
        
        for linea in factura.lineas.all():
            if linea.tipo == 'Mano de Obra':
                pvp_mo += linea.total_linea
            elif linea.tipo == 'Grúa':
                grua_en_esta_factura += linea.total_linea
                ganancia_grua_facturada += linea.total_linea
            elif linea.tipo in ['Repuesto', 'Consumible', 'Externo']:
                pvp_piezas += linea.total_linea
                if linea.tipo == 'Consumible':
                    tipo_obj = tipos_consumible_dict.get(linea.descripcion.upper())
                    if tipo_obj and tipo_obj.id in ultimas_compras_por_tipo:
                        compra_relevante = ultimas_compras_por_tipo[tipo_obj.id]
                        if compra_relevante.fecha_compra <= factura.fecha_emision:
                            coste_consumibles_factura += (compra_relevante.coste_por_unidad or Decimal('0.00')) * linea.cantidad
        
        coste_total_piezas = coste_repuestos + coste_externos + coste_consumibles_factura
        ganancia_piezas_orden = pvp_piezas - coste_total_piezas
        ganancia_total_taller = pvp_mo + ganancia_piezas_orden
        
        total_ganancia_mo += pvp_mo
        total_ganancia_piezas += ganancia_piezas_orden
        
        metodos = list(orden.ingreso_set.values_list('metodo_pago', flat=True))
        es_compensado = 'COMPENSACION' in metodos

        reporte.append({ 
            'orden': orden, 
            'factura': factura, 
            'ganancia_mo': pvp_mo,
            'ganancia_piezas': ganancia_piezas_orden,
            'grua_facturada': grua_en_esta_factura,
            'ganancia_total_taller': ganancia_total_taller,
            'es_compensado': es_compensado 
        })
    
    ganancia_grua_directa = ingresos_grua.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    ganancia_otras_total = otras_ganancias.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    
    ganancia_grua_total = ganancia_grua_directa + ganancia_grua_facturada
    total_ganancia_general = total_ganancia_mo + total_ganancia_piezas + ganancia_grua_total + ganancia_otras_total
    
    ganancias_directas_desglose = sorted(list(ingresos_grua) + list(otras_ganancias), key=lambda x: x.fecha, reverse=True)
    
    context = { 
        'reporte': reporte, 
        'ganancia_mo': total_ganancia_mo,
        'ganancia_piezas': total_ganancia_piezas,
        'ganancia_grua': ganancia_grua_total, 
        'ganancia_otras': ganancia_otras_total, 
        'ganancias_directas_desglose': ganancias_directas_desglose, 
        'total_ganancia_general': total_ganancia_general, 
        'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_sel_int, 
        'mes_seleccionado': mes_sel_int, 
        'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/informe_rentabilidad.html', context)


@login_required
def detalle_ganancia_orden(request, orden_id):
    if not request.user.is_superuser:
        return redirect('home')

    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo', 'cliente'), id=orden_id)
    try: 
        factura = Factura.objects.prefetch_related('lineas', 'orden__ingreso_set').get(orden=orden)
    except Factura.DoesNotExist: 
        return redirect('detalle_orden', orden_id=orden.id)
    
    desglose_agrupado = {}
    gastos_usados_ids = set()
    
    gastos_asociados = Gasto.objects.filter(orden=orden, categoria__in=['Repuestos', 'Otros']).order_by('id')
    compras_consumibles = CompraConsumible.objects.filter(fecha_compra__lte=factura.fecha_emision).order_by('tipo_id', '-fecha_compra')
    
    ultimas_compras_por_tipo = {}
    for compra in compras_consumibles:
        if compra.tipo_id not in ultimas_compras_por_tipo: 
            ultimas_compras_por_tipo[compra.tipo_id] = compra
            
    tipos_consumible_dict = {tipo.nombre.upper(): tipo for tipo in TipoConsumible.objects.all()}
    
    for linea in factura.lineas.all():
        pvp_linea = linea.total_linea
        coste_linea = Decimal('0.00')
        descripcion_limpia = linea.descripcion.strip().upper()
        key = (linea.tipo, descripcion_limpia)
        
        try:
            tipo_nombre = linea.get_tipo_display()
        except:
            tipo_nombre = linea.tipo
            
        if linea.tipo == 'Grúa':
            tipo_nombre = '🚛 Servicio de Grúa'

        desglose_agrupado.setdefault(key, {'descripcion': f"{tipo_nombre}: {linea.descripcion}", 'coste': Decimal('0.00'), 'pvp': Decimal('0.00')})
        desglose_agrupado[key]['pvp'] += pvp_linea
        
        if linea.tipo in ['Repuesto', 'Externo']:
            categoria_gasto = 'Repuestos' if linea.tipo == 'Repuesto' else 'Otros'
            gasto_encontrado = None
            for gasto in gastos_asociados:
                if (gasto.id not in gastos_usados_ids and gasto.categoria == categoria_gasto and gasto.descripcion.strip().upper() == descripcion_limpia): 
                    gasto_encontrado = gasto
                    break
            if gasto_encontrado: 
                coste_linea = gasto_encontrado.importe or Decimal('0.00')
                gastos_usados_ids.add(gasto_encontrado.id)
                
        elif linea.tipo == 'Consumible':
            tipo_obj = tipos_consumible_dict.get(descripcion_limpia)
            if tipo_obj and tipo_obj.id in ultimas_compras_por_tipo: 
                coste_unitario = ultimas_compras_por_tipo[tipo_obj.id].coste_por_unidad or Decimal('0.00')
                coste_linea = coste_unitario * linea.cantidad
                
        desglose_agrupado[key]['coste'] += coste_linea
        
    for gasto in gastos_asociados:
        if gasto.id not in gastos_usados_ids:
            descripcion_limpia = gasto.descripcion.strip().upper()
            tipo_gasto_map = {'Repuestos': 'Repuesto', 'Otros': 'Externo'}
            tipo_para_key = tipo_gasto_map.get(gasto.categoria, 'Externo')
            key = (tipo_para_key, descripcion_limpia)
            
            try: tipo_nombre = gasto.get_categoria_display()
            except: tipo_nombre = gasto.categoria

            desglose_agrupado.setdefault(key, {'descripcion': f"{tipo_nombre} (No facturado): {gasto.descripcion}", 'coste': Decimal('0.00'), 'pvp': Decimal('0.00')})
            desglose_agrupado[key]['coste'] += gasto.importe or Decimal('0.00')
             
    desglose_final_list = []
    ganancia_total_calculada = Decimal('0.00')
    
    for item_agrupado in desglose_agrupado.values():
        ganancia = item_agrupado['pvp'] - item_agrupado['coste']
        item_agrupado['ganancia'] = ganancia
        desglose_final_list.append(item_agrupado)
        ganancia_total_calculada += ganancia
        
    desglose_final_list.sort(key=lambda x: x['descripcion'])
    
    abonos = sum(ing.importe for ing in factura.orden.ingreso_set.all()) if hasattr(factura.orden, 'ingreso_set') else Decimal('0.00')
    
    saldo_cliente = abonos - factura.total_final
    saldo_cliente_abs = abs(saldo_cliente)
    
    context = { 
        'orden': orden, 
        'factura': factura, 
        'desglose': desglose_final_list, 
        'ganancia_total': ganancia_total_calculada, 
        'abonos_totales': abonos, 
        'saldo_cliente': saldo_cliente, 
        'saldo_cliente_abs': saldo_cliente_abs 
    }
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
    
    gastos_totales_t1 = Gasto.objects.filter(metodo_pago='TARJETA_1').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    abonos_totales_t1 = Ingreso.objects.filter(metodo_pago='TARJETA_1').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    deuda_t1 = gastos_totales_t1 - abonos_totales_t1
    disponible_t1 = Decimal('2000.00') - deuda_t1

    gastos_totales_t2 = Gasto.objects.filter(metodo_pago='TARJETA_2').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    abonos_totales_t2 = Ingreso.objects.filter(metodo_pago='TARJETA_2').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    deuda_t2 = gastos_totales_t2 - abonos_totales_t2
    disponible_t2 = Decimal('1000.00') - deuda_t2

    context = { 
        'total_ingresado': total_ingresado, 'total_gastado': total_gastado, 'total_ganancia': total_ganancia, 
        'anos_y_meses': anos_y_meses_data, 'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13),
        'disponible_t1': disponible_t1,
        'disponible_t2': disponible_t2 
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

@login_required
def historial_cuenta(request, cuenta_nombre):
    if not request.user.is_superuser:
        return redirect('home')

    mapeo_cuentas = {
        'efectivo': ('EFECTIVO', 'Caja (Efectivo)'),
        'banco': ('CUENTA_TALLER', 'Cuenta Taller (Banco)'),
        'tarjeta1': ('TARJETA_1', 'Tarjeta 1 (Visa 2000€)'),
        'tarjeta2': ('TARJETA_2', 'Tarjeta 2 (Visa 1000€)'),
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
    if request.user == nota.autor or request.user.is_superuser:
        nota.completada = True
        nota.save()
    return redirect('home')

@login_required
def historial_notas(request):
    notas = NotaTablon.objects.filter(completada=True).order_by('-fecha_creacion')
    return render(request, 'taller/historial_notas.html', {'notas': notas})

@login_required
def lista_deudas(request):
    if request.method == 'POST':
        if request.user.groups.filter(name='Solo Ver').exists():
            return HttpResponseForbidden("No tienes permiso para crear deudas.")
            
        acreedor = request.POST.get('acreedor')
        motivo = request.POST.get('motivo')
        importe_inicial = request.POST.get('importe_inicial')
        
        es_banco = request.POST.get('es_credito_bancario') == 'True'
        
        if acreedor and motivo and importe_inicial:
            DeudaTaller.objects.create(
                acreedor=acreedor,
                motivo=motivo,
                importe_inicial=importe_inicial,
                es_credito_bancario=es_banco 
            )
            return redirect('lista_deudas')
            
    todas_las_deudas = DeudaTaller.objects.all().order_by('-fecha_creacion', '-id')
    deudas_pendientes = [d for d in todas_las_deudas if d.estado == 'Pendiente']
    deudas_pagadas = [d for d in todas_las_deudas if d.estado == 'Pagada']
    
    total_deudas_normales = sum(d.importe_pendiente for d in deudas_pendientes)
    
    gastos_t1 = Gasto.objects.filter(metodo_pago='TARJETA_1').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    abonos_t1 = Ingreso.objects.filter(metodo_pago='TARJETA_1').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    deuda_t1 = gastos_t1 - abonos_t1
    
    gastos_t2 = Gasto.objects.filter(metodo_pago='TARJETA_2').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    abonos_t2 = Ingreso.objects.filter(metodo_pago='TARJETA_2').aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    deuda_t2 = gastos_t2 - abonos_t2
    
    total_tarjetas = deuda_t1 + deuda_t2

    # --- NUEVO: CÁLCULO DE DEUDA DE NÓMINAS ---
    total_deuda_nominas = Decimal('0.00')
    empleados_taller = Empleado.objects.all()
    hoy_date = timezone.now().date()
    
    for emp in empleados_taller:
        dias_pendientes = Asistencia.objects.filter(
            empleado=emp, pagado=False, hora_salida__isnull=False
        ).values('fecha').distinct().count()
        
        # --- CÁLCULO INTELIGENTE ---
        if emp.es_sueldo_fijo:
            dias_laborables_mes = obtener_dias_laborables_mes(hoy_date)
            sueldo_bruto = Decimal(dias_pendientes) * (emp.sueldo_fijo_mensual / dias_laborables_mes)
        else:
            sueldo_bruto = dias_pendientes * emp.sueldo_por_dia
            
        adelantos_pendientes = AdelantoSueldo.objects.filter(empleado=emp, liquidado=False)
        total_adelantos = sum(a.importe for a in adelantos_pendientes)
        
        neto_a_pagar = sueldo_bruto - total_adelantos
        if neto_a_pagar > 0:
            total_deuda_nominas += neto_a_pagar

    # Actualizamos el GRAN TOTAL sumando las nóminas
    gran_total_deuda = total_deudas_normales + total_tarjetas + total_deuda_nominas
    
    context = {
        'deudas_pendientes': deudas_pendientes,
        'deudas_pagadas': deudas_pagadas,
        'gran_total_deuda': gran_total_deuda,
        'total_deudas_normales': total_deudas_normales,
        'total_tarjetas': total_tarjetas,
        'total_deuda_nominas': total_deuda_nominas # Pasamos la nueva variable al HTML
    }
    return render(request, 'taller/lista_deudas.html', context)

    
@login_required
def detalle_deuda(request, deuda_id):
    deuda = get_object_or_404(DeudaTaller, id=deuda_id)
    
    if request.method == 'POST':
        if request.user.groups.filter(name='Solo Ver').exists():
            return HttpResponseForbidden("No tienes permiso para modificar deudas.")
            
        form_type = request.POST.get('form_type')
        
        if form_type == 'pago_inteligente_banco':
            importe_pago_str = request.POST.get('importe_pago')
            saldo_real_str = request.POST.get('saldo_real_banco')
            fecha_str = request.POST.get('fecha_pago')
            
            if importe_pago_str and saldo_real_str:
                try:
                    importe_pago = Decimal(importe_pago_str.replace(',', '.'))
                    saldo_real_banco = Decimal(saldo_real_str.replace(',', '.'))
                    fecha_pago = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else timezone.now().date()
                    
                    amortizacion = deuda.importe_pendiente - saldo_real_banco
                    intereses = importe_pago - amortizacion
                    
                    if intereses >= 0 and amortizacion >= 0:
                        with transaction.atomic():
                            Gasto.objects.create(
                                fecha=fecha_pago, categoria='Pago de Deuda', importe=amortizacion,
                                descripcion=f"AMORTIZACIÓN CUOTA PRÉSTAMO: {deuda.acreedor}",
                                metodo_pago='CUENTA_TALLER', deuda_asociada=deuda
                            )
                            Gasto.objects.create(
                                fecha=fecha_pago, categoria='COMISIONES_INTERESES', importe=intereses,
                                descripcion=f"INTERESES BANCARIOS ({deuda.acreedor})",
                                metodo_pago='CUENTA_TALLER', deuda_asociada=None
                            )
                except (ValueError, TypeError, Decimal.InvalidOperation):
                    pass

        elif form_type == 'ampliar':
            importe_extra = request.POST.get('importe_extra')
            concepto_extra = request.POST.get('concepto_extra')
            
            if importe_extra and concepto_extra:
                try:
                    extra_decimal = Decimal(importe_extra.replace(',', '.'))
                    if extra_decimal > 0:
                        deuda.importe_inicial += extra_decimal
                        deuda.save()
                        AmpliacionDeuda.objects.create(deuda=deuda, importe=extra_decimal, motivo=concepto_extra)
                except (ValueError, TypeError, Decimal.InvalidOperation):
                    pass
                    
        elif form_type == 'editar':
            nuevo_acreedor = request.POST.get('acreedor')
            nuevo_motivo = request.POST.get('motivo')
            nuevo_importe_str = request.POST.get('importe_inicial')
            
            if nuevo_acreedor and nuevo_motivo and nuevo_importe_str:
                try:
                    nuevo_importe = Decimal(nuevo_importe_str.replace(',', '.'))
                    deuda.acreedor = nuevo_acreedor; deuda.motivo = nuevo_motivo; deuda.importe_inicial = nuevo_importe; deuda.save() 
                except (ValueError, TypeError, Decimal.InvalidOperation):
                    pass
                    
        elif form_type == 'editar_movimiento':
            mov_id = request.POST.get('mov_id'); mov_tipo = request.POST.get('mov_tipo')
            nueva_fecha_str = request.POST.get('fecha'); nuevo_importe_str = request.POST.get('importe')
            nueva_descripcion = request.POST.get('descripcion')
            
            try:
                nueva_fecha = datetime.strptime(nueva_fecha_str, '%Y-%m-%d').date()
                nuevo_importe = Decimal(nuevo_importe_str.replace(',', '.'))
                
                if mov_tipo == 'pago':
                    gasto = Gasto.objects.get(id=mov_id, deuda_asociada=deuda)
                    gasto.fecha = nueva_fecha; gasto.importe = nuevo_importe; gasto.descripcion = nueva_descripcion.upper(); gasto.save()
                
                elif mov_tipo == 'ampliacion':
                    ampliacion = AmpliacionDeuda.objects.get(id=mov_id, deuda=deuda)
                    diferencia = nuevo_importe - ampliacion.importe
                    deuda.importe_inicial += diferencia; deuda.save()
                    ampliacion.fecha = nueva_fecha; ampliacion.importe = nuevo_importe; ampliacion.motivo = nueva_descripcion.upper(); ampliacion.save()
                    
                elif mov_tipo == 'interes':
                    gasto = Gasto.objects.get(id=mov_id, categoria='COMISIONES_INTERESES')
                    gasto.fecha = nueva_fecha; gasto.importe = nuevo_importe; gasto.descripcion = nueva_descripcion.upper(); gasto.save()
                    
            except (ValueError, TypeError, Decimal.InvalidOperation, Gasto.DoesNotExist, AmpliacionDeuda.DoesNotExist):
                pass

        elif form_type == 'borrar_movimiento':
            mov_id = request.POST.get('mov_id'); mov_tipo = request.POST.get('mov_tipo')
            
            try:
                if mov_tipo == 'pago':
                    gasto = Gasto.objects.get(id=mov_id, deuda_asociada=deuda)
                    if deuda.es_credito_bancario:
                        Gasto.objects.filter(fecha=gasto.fecha, categoria='COMISIONES_INTERESES').filter(Q(descripcion__icontains=deuda.acreedor) | Q(descripcion__icontains="INTERESES BANCARIOS")).delete()
                    gasto.delete()
                    
                elif mov_tipo == 'ampliacion':
                    ampliacion = AmpliacionDeuda.objects.get(id=mov_id, deuda=deuda)
                    deuda.importe_inicial -= ampliacion.importe; deuda.save(); ampliacion.delete()
                    
                elif mov_tipo == 'interes':
                    gasto_int = Gasto.objects.get(id=mov_id, categoria='COMISIONES_INTERESES')
                    gasto_int.delete()
                
            except (Gasto.DoesNotExist, AmpliacionDeuda.DoesNotExist):
                pass

        return redirect('detalle_deuda', deuda_id=deuda.id)

    pagos = deuda.gastos_pagados.all()
    ampliaciones = deuda.ampliaciones.all()
    
    historial_combinado = []
    
    for p in pagos:
        historial_combinado.append({
            'id_real': p.id,            
            'fecha': p.fecha,
            'descripcion': p.descripcion or "Pago de deuda",
            'metodo': p.get_metodo_pago_display(),
            'importe': p.importe,
            'tipo': 'pago',
            'orden': p.orden
        })
        
    for a in ampliaciones:
        historial_combinado.append({
            'id_real': a.id,            
            'fecha': a.fecha,
            'descripcion': a.motivo,
            'metodo': 'Ampliación / Nuevo Cargo',
            'importe': a.importe,
            'tipo': 'ampliacion',
            'orden': None
        })
        
    total_intereses = Decimal('0.00')
    if deuda.es_credito_bancario:
        fechas_pagos = [p.fecha for p in pagos]
        
        intereses = Gasto.objects.filter(categoria='COMISIONES_INTERESES').filter(
            Q(fecha__in=fechas_pagos) | Q(descripcion__icontains=deuda.acreedor) | Q(descripcion__icontains="INTERESES BANCARIOS")
        ).distinct()
        
        for i in intereses:
            historial_combinado.append({
                'id_real': i.id,            
                'fecha': i.fecha,
                'descripcion': i.descripcion,
                'metodo': i.get_metodo_pago_display(),
                'importe': i.importe,
                'tipo': 'interes', 
                'orden': None
            })
            total_intereses += (i.importe or Decimal('0.00'))
        
    historial_combinado.sort(key=lambda x: x['fecha'], reverse=True)
    
    porcentaje = 0
    if deuda.importe_inicial > 0:
        porcentaje = (deuda.importe_pagado / deuda.importe_inicial) * 100
        if porcentaje > 100: porcentaje = 100
            
    context = {
        'deuda': deuda,
        'historial': historial_combinado,
        'porcentaje_pagado': porcentaje,
        'total_intereses': total_intereses
    }
    return render(request, 'taller/detalle_deuda.html', context)

@login_required
def inventario_lista(request):
    tipos = TipoConsumible.objects.all().order_by('nombre')
    context = {'tipos': tipos}
    return render(request, 'taller/inventario.html', context)

@login_required
def crear_tipo_consumible(request):
    if request.user.groups.filter(name='Solo Ver').exists():
        return HttpResponseForbidden("No tienes permiso para modificar el inventario.")
        
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        unidad = request.POST.get('unidad_medida')
        minimo = request.POST.get('nivel_minimo_stock')
        
        if nombre and unidad:
            minimo_val = Decimal(minimo.replace(',', '.')) if minimo else None
            TipoConsumible.objects.create(
                nombre=nombre,
                unidad_medida=unidad,
                nivel_minimo_stock=minimo_val
            )
            return redirect('inventario')
            
    return render(request, 'taller/crear_tipo_consumible.html')

@login_required
def ajustar_stock(request, tipo_id):
    if request.user.groups.filter(name='Solo Ver').exists():
        return HttpResponseForbidden("No tienes permiso para modificar el inventario.")
        
    tipo = get_object_or_404(TipoConsumible, id=tipo_id)
    
    if request.method == 'POST':
        cantidad = request.POST.get('cantidad')
        motivo = request.POST.get('motivo')
        
        if cantidad and motivo:
            cantidad_val = Decimal(cantidad.replace(',', '.'))
            AjusteStockConsumible.objects.create(
                tipo=tipo,
                cantidad_ajustada=cantidad_val,
                motivo=motivo
            )
            return redirect('inventario')
            
    context = {'tipo': tipo}
    return render(request, 'taller/ajustar_stock.html', context)

@login_required
def detalle_consumible(request, tipo_id):
    tipo = get_object_or_404(TipoConsumible, id=tipo_id)
    movimientos = []
    
    for compra in CompraConsumible.objects.filter(tipo=tipo):
        movimientos.append({
            'fecha': compra.fecha_compra,
            'accion': 'COMPRA',
            'cantidad': compra.cantidad,
            'descripcion': f"Compra de stock. Coste: {compra.coste_total}€",
            'color': '#10b981', 
            'signo': '+'
        })
        
    for uso in UsoConsumible.objects.filter(tipo=tipo):
        movimientos.append({
            'fecha': uso.fecha_uso,
            'accion': 'USO EN TALLER',
            'cantidad': uso.cantidad_usada,
            'descripcion': f"Vehículo: {uso.orden.vehiculo.matricula} (Orden #{uso.orden.id})",
            'url_orden': reverse('detalle_orden', args=[uso.orden.id]),
            'color': '#ef4444', 
            'signo': '-'
        })
        
    for ajuste in AjusteStockConsumible.objects.filter(tipo=tipo):
        movimientos.append({
            'fecha': ajuste.fecha_ajuste,
            'accion': 'AJUSTE MANUAL',
            'cantidad': abs(ajuste.cantidad_ajustada),
            'descripcion': f"Motivo: {ajuste.motivo}",
            'color': '#f59e0b', 
            'signo': '+' if ajuste.cantidad_ajustada > 0 else '-'
        })
        
    movimientos.sort(key=lambda x: x['fecha'], reverse=True)
    
    context = {
        'tipo': tipo,
        'movimientos': movimientos
    }
    return render(request, 'taller/detalle_consumible.html', context)

@login_required
def editar_consumible(request, tipo_id):
    if request.user.groups.filter(name='Solo Ver').exists():
        return HttpResponseForbidden("No tienes permiso para modificar el inventario.")
        
    tipo = get_object_or_404(TipoConsumible, id=tipo_id)
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        unidad = request.POST.get('unidad_medida')
        minimo = request.POST.get('nivel_minimo_stock')
        precio = request.POST.get('precio_coste_medio')
        
        if nombre and unidad:
            tipo.nombre = nombre
            tipo.unidad_medida = unidad
            tipo.nivel_minimo_stock = Decimal(minimo.replace(',', '.')) if minimo else None
            if precio:
                tipo.precio_coste_medio = Decimal(precio.replace(',', '.'))
                
            tipo.save()
            return redirect('inventario')
            
    context = {'tipo': tipo}
    return render(request, 'taller/editar_consumible.html', context)

# --- VISTA PARA EL ENLACE MÁGICO DEL PRESUPUESTO ---
def ver_presupuesto_publico(request, signed_id):
    signer = Signer()
    try:
        presupuesto_id = signer.unsign(signed_id)
        presupuesto = get_object_or_404(Presupuesto, id=presupuesto_id)
    except BadSignature:
        return HttpResponseForbidden("El enlace de este presupuesto es inválido o ha caducado.")

    template_path = 'taller/presupuesto_pdf.html' 
    context = {'presupuesto': presupuesto}
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Presupuesto_{presupuesto.id}.pdf"'
    
    template = get_template(template_path)
    html = template.render(context)
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('Tuvimos algunos errores al crear el PDF <pre>' + html + '</pre>')
    return response

# --- CONEXIÓN CON INTELIGENCIA ARTIFICIAL (GEMINI) ---
import json
import os
import google.generativeai as genai
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from . import ai_tools

api_key = os.environ.get("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
else:
    print("⚠️ ADVERTENCIA: No se ha encontrado GOOGLE_API_KEY. J.A.R.V.I.S. estará apagado.")

@login_required
def asistente_ia(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            mensaje_usuario = data.get('mensaje', '')

            if 'memoria_ia' not in request.session:
                request.session['memoria_ia'] = []
            
            memoria = request.session['memoria_ia']
            
            contexto_conversacion = "HISTORIAL RECIENTE DE LA CONVERSACIÓN:\n"
            for linea in memoria:
                contexto_conversacion += f"{linea}\n"
            contexto_conversacion += f"\nEL USUARIO AHORA DICE: {mensaje_usuario}"

            from django.utils import timezone
            fecha_hoy = timezone.now().strftime("%Y-%m-%d")
            instruccion = f"""
            Eres J.A.R.V.I.S., el asistente ejecutivo de Inteligencia Artificial del taller ServiMax.
            Tu trabajo es leer lo que pide el usuario y devolver UNICAMENTE un archivo JSON con la orden de lo que hay que hacer.
            
            IMPORTANTE: HOY ES {fecha_hoy}. Usa esta fecha exacta como referencia obligatoria para calcular los días (mañana, el próximo jueves, etc).
            
            REGLAS ESTRICTAS DE RESPUESTA:
            --- REGLAS DE LA AGENDA Y CITAS ---
            - Si te piden agendar, apuntar o crear una cita: {{"accion": "crear_cita", "cliente": "Carlos", "vehiculo": "BMW", "motivo": "Cambiar pastillas", "fecha": "2026-03-12", "hora": "10:00"}}
            (Calcula SIEMPRE la 'fecha' en formato YYYY-MM-DD y la 'hora' en formato HH:MM. Si no te dicen el vehículo, déjalo vacío).
            """ + """
            - Si te piden modificar, cambiar de día, cambiar la hora, o CORREGIR EL NOMBRE de una cita: {"accion": "modificar_cita", "cliente": "Carlos", "fecha": "2026-03-15", "hora": "12:00", "motivo": "Revisión general", "vehiculo": "BMW", "nuevo_nombre": "Marcos"} (Extrae el 'cliente' original para buscarlo, y pon en 'nuevo_nombre', 'fecha', etc., SOLO lo que haya que cambiar).
            - Si te dicen que un cliente ha llegado, que ya está aquí, o que canceles su cita: {"accion": "actualizar_cita", "cliente": "Maria", "hora": "17:00", "estado": "En taller"} (Extrae el nombre, la hora si la dicen, y pon estado 'En taller' si ha llegado o 'Cancelada' si no viene).
            - Si piden "ver", "mostrar" o "dame" la factura de un coche...
            
            --- REGLAS DE TIEMPOS Y ENTREGAS ---
            - Si preguntan cuánto tiempo lleva, cuánto ha tardado o días en el taller de una ORDEN concreta: {"accion": "tiempo_taller", "id_orden": 15}
            - Si el usuario responde "sí" al desglose de fases: {"accion": "desglose", "id_orden": 15}
            - Si preguntan qué vehículos han sido entregados o el historial de entregas: {"accion": "vehiculos_entregados"}
            
            --- REGLAS DE FINANZAS INTELIGENTES ---
            - Si te piden buscar un gasto, ingreso, factura, recibo o movimiento por su concepto, nombre o precio: {"accion": "buscar_movimiento", "termino": "aceite"} (Extrae el nombre, concepto o la cantidad exacta de dinero que buscan en número).
            - Si preguntan cuánto dinero ha dejado o la ganancia de una ORDEN concreta: {"accion": "rentabilidad_orden", "id_orden": 15}
            - Si preguntan por el dinero/ganancia de un COCHE entero, o si responden "SÍ" a ver el historial de ganancias: {"accion": "rentabilidad_historial", "id_orden": 15, "matricula": "1234ABC"} (Extrae el id_orden o la matricula del historial reciente).
            
            --- REGLAS DE PRESUPUESTOS Y BORRADORES ---
            - Si preguntan cuánto solemos cobrar, cuál es el precio medio o piden un presupuesto a ojo para una reparación: {"accion": "presupuesto_predictivo", "reparacion": "embrague", "modelo": "Seat Ibiza"} (Extrae la reparación y el modelo si lo dicen, si no hay modelo déjalo vacío).
            - Si te piden "crear un presupuesto", "generar borrador", "hazle un presupuesto": {"accion": "crear_borrador", "matricula": "1234ABC", "cliente": "Andrés", "descripcion": "Cambio de embrague", "precio": 450} (Extrae la matrícula o el nombre del cliente. Puedes dejar matrícula o cliente vacío si solo te dan uno de los dos).
            
            --- REGLA DE MARKETING AUTOMÁTICO ---
            - Si te preguntan a qué clientes les toca revisión, cambio de aceite, o te piden hacer una campaña de marketing/recordatorio: {"accion": "marketing_revision", "reparacion": "aceite"} (Extrae la palabra clave de lo que buscan, por defecto usa "aceite" o "revisión").
            
            --- REGLAS DEL TABLÓN Y TAREAS ---
            - Si preguntan por tareas pendientes, avisos o el tablón: {"accion": "tareas"}
            - Si te piden apuntar, anotar, recordar algo en el tablón o crear una tarea: {"accion": "crear_nota", "texto": "Llamar al proveedor de ruedas mañana"} (Extrae exactamente la tarea o recordatorio que el usuario quiere guardar).
            -------------------------------------------
            
            - Si preguntan qué coches llevan mucho tiempo, están atascados o retrasados: {"accion": "coches_atascados"}
            - Si preguntan por stock o piezas: {"accion": "stock", "articulo": "nombre_del_articulo"}
            - Si preguntan por ingresos, caja o balance de hoy: {"accion": "caja_hoy"}
            - Si preguntan quién debe dinero, morosos o cuentas por cobrar: {"accion": "deudores"}
            - Si preguntan cuántos coches hay en el taller o resumen del taller: {"accion": "resumen_taller"}
            - Si preguntan por el historial, qué se le hizo o cuántas veces ha venido un coche: {"accion": "historial_coche", "matricula": "1234ABC"}
            - Si preguntan qué coches están listos, terminados o para entregar: {"accion": "coches_listos"}
            - Si piden el teléfono, contacto o dueño de una matrícula: {"accion": "contacto_cliente", "matricula": "1234ABC"}
            - Si saludan o dicen algo fuera de esto: {"accion": "hablar", "texto": "tu respuesta amistosa"}
            
            No uses markdown, devuelve SOLO el JSON puro.
            """

            model = genai.GenerativeModel(
                'gemini-2.5-flash', 
                system_instruction=instruccion,
                generation_config={"response_mime_type": "application/json"}
            )
            
            response = model.generate_content(contexto_conversacion)
            decision_ia = json.loads(response.text)
            
            accion = decision_ia.get('accion')
            
            if accion == 'ver_factura':
                resultado = ai_tools.obtener_factura_por_matricula(decision_ia.get('matricula'), enviar_whatsapp=False)
            elif accion == 'enviar_factura':
                resultado = ai_tools.obtener_factura_por_matricula(decision_ia.get('matricula'), enviar_whatsapp=True)
            elif accion == 'presupuesto':
                resultado = ai_tools.enviar_presupuesto_whatsapp(decision_ia.get('id'))
            elif accion == 'estado':
                resultado = ai_tools.consultar_estado_vehiculo(decision_ia.get('matricula'))
            elif accion == 'tiempo_taller':
                resultado = ai_tools.tiempo_en_taller(decision_ia.get('id_orden'))
            elif accion == 'desglose':
                resultado = ai_tools.desglose_fases_vehiculo(decision_ia.get('id_orden'))
            elif accion == 'vehiculos_entregados':
                resultado = ai_tools.vehiculos_entregados_reporte()
            elif accion == 'coches_atascados':
                resultado = ai_tools.coches_atascados()
            elif accion == 'rentabilidad_orden':
                resultado = ai_tools.rentabilidad_vehiculo(id_orden=decision_ia.get('id_orden'), solo_orden=True)
            elif accion == 'rentabilidad_historial':
                resultado = ai_tools.rentabilidad_vehiculo(matricula=decision_ia.get('matricula'), id_orden=decision_ia.get('id_orden'), solo_orden=False)
            
            elif accion == 'crear_borrador':
                resultado = ai_tools.crear_borrador_presupuesto(
                    matricula=decision_ia.get('matricula'), 
                    nombre_cliente=decision_ia.get('cliente'),
                    descripcion=decision_ia.get('descripcion'), 
                    precio=decision_ia.get('precio')
                )
            
            elif accion == 'crear_cita':
                resultado = ai_tools.crear_cita_agenda(
                    cliente=decision_ia.get('cliente'),
                    motivo=decision_ia.get('motivo'),
                    vehiculo=decision_ia.get('vehiculo'),
                    fecha=decision_ia.get('fecha'),
                    hora=decision_ia.get('hora')
                )

            elif accion == 'modificar_cita':
                resultado = ai_tools.modificar_cita_agenda(
                    cliente=decision_ia.get('cliente'),
                    fecha=decision_ia.get('fecha'),
                    hora=decision_ia.get('hora'),
                    motivo=decision_ia.get('motivo'),
                    vehiculo=decision_ia.get('vehiculo'),
                    nuevo_nombre=decision_ia.get('nuevo_nombre')
                )   

            elif accion == 'actualizar_cita':
                resultado = ai_tools.actualizar_estado_cita(
                    cliente=decision_ia.get('cliente'),
                    hora=decision_ia.get('hora'),
                    estado=decision_ia.get('estado', 'En taller')
                )   
            
            elif accion == 'presupuesto_predictivo':
                reparacion_pedida = decision_ia.get('reparacion')
                datos_historial = ai_tools.extraer_datos_presupuesto(reparacion_pedida, decision_ia.get('modelo', ''))
                
                if datos_historial == "NO_HAY_DATOS" or datos_historial == "No se especificó reparación.":
                    resultado = {"status": "success", "mensaje": f"He revisado el historial, pero no encuentro ninguna reparación pasada que encaje con '{reparacion_pedida}'. Tendremos que calcular este presupuesto desde cero."}
                else:
                    prompt_analisis = f"""
                    Eres J.A.R.V.I.S. El jefe del taller quiere dar un presupuesto estimado a ojo para: '{reparacion_pedida}'.
                    He extraído estas facturas recientes del historial de tu base de datos:
                    
                    {datos_historial}
                    
                    TU TAREA DE ANÁLISIS:
                    1. Lee el 'Problema escrito por el mecánico' de cada orden.
                    2. Si ves que una factura tiene un precio muy alto porque incluye OTRAS averías además de '{reparacion_pedida}' (por ejemplo: cambio de caja Y además alternador), IGNORA esa factura en tu cálculo mental porque inflará el precio de la reparación pedida.
                    3. Quédate solo con las facturas que parezcan estar aislando el problema principal ('{reparacion_pedida}').
                    4. Redacta una respuesta directa y profesional diciéndole al jefe cuál suele ser el precio real estimado basándote en las facturas más "puras". Explícale brevemente qué facturas has descartado y por qué.
                    
                    Responde directamente con tu análisis.
                    """
                    
                    respuesta_razonada = model.generate_content(prompt_analisis)
                    resultado = {"status": "success", "mensaje": respuesta_razonada.text}
            
            elif accion == 'marketing_revision':
                resultado = ai_tools.clientes_para_revision(reparacion=decision_ia.get('reparacion', 'aceite'))
            
            elif accion == 'crear_nota':
                resultado = ai_tools.crear_nota_tablon(
                    texto=decision_ia.get('texto'), 
                    usuario=request.user
                )
                
            elif accion == 'stock':
                resultado = ai_tools.consultar_stock(decision_ia.get('articulo'))
            elif accion == 'buscar_movimiento':
                resultado = ai_tools.buscar_movimiento(decision_ia.get('termino'))   
            elif accion == 'caja_hoy':
                resultado = ai_tools.resumen_caja_hoy()
            elif accion == 'deudores':
                resultado = ai_tools.clientes_deudores()
            elif accion == 'resumen_taller':
                resultado = ai_tools.coches_en_taller()
            elif accion == 'historial_coche':
                resultado = ai_tools.historial_vehiculo(decision_ia.get('matricula'))
            elif accion == 'coches_listos':
                resultado = ai_tools.coches_listos_para_entregar()
            elif accion == 'contacto_cliente':
                resultado = ai_tools.contacto_cliente(decision_ia.get('matricula'))
            elif accion == 'tareas':
                resultado = ai_tools.tareas_pendientes()
            elif accion == 'hablar':
                resultado = {"status": "success", "mensaje": decision_ia.get('texto')}
            else:
                resultado = {"status": "error", "mensaje": "No tengo una herramienta para hacer eso todavía."}

            memoria.append(f"Usuario: {mensaje_usuario}")
            memoria.append(f"J.A.R.V.I.S.: {resultado.get('mensaje', '')}")
            
            request.session['memoria_ia'] = memoria[-4:] 
            request.session.modified = True

            try:
                from .models import HistorialIA
                HistorialIA.objects.create(
                    usuario=request.user if request.user.is_authenticated else None,
                    peticion=mensaje_usuario,
                    respuesta=resultado.get('mensaje', 'Sin respuesta textual'), 
                    accion_ejecutada=accion 
                )
            except Exception as e:
                print(f"Error guardando la memoria de J.A.R.V.I.S.: {e}")

            return JsonResponse(resultado)

        except Exception as e:
            return JsonResponse({"status": "error", "mensaje": f"Hubo un fallo en mi sistema: {str(e)}"})
            
    return render(request, 'taller/asistente_ia.html')


@login_required
def agenda_taller(request):
    from django.utils import timezone
    from django.db.models.functions import ExtractYear
    from datetime import timedelta, datetime
    
    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        
        if form_type == 'nueva_cita_manual':
            nombre = request.POST.get('nombre_cliente')
            vehiculo = request.POST.get('vehiculo_info')
            motivo = request.POST.get('motivo')
            notas = request.POST.get('notas_adicionales')
            fecha_str = request.POST.get('fecha')
            hora_str = request.POST.get('hora')

            if nombre and motivo and fecha_str and hora_str:
                try:
                    fecha_completa = f"{fecha_str} {hora_str}"
                    fecha_obj = datetime.strptime(fecha_completa, "%Y-%m-%d %H:%M")
                    fecha_aware = timezone.make_aware(fecha_obj)
                    Cita.objects.create(
                        nombre_cliente=nombre.upper(),
                        vehiculo_info=vehiculo.upper() if vehiculo else '',
                        motivo=motivo.upper(),
                        notas_adicionales=notas,
                        fecha_hora=fecha_aware,
                        estado='Pendiente'
                    )
                except Exception:
                    pass
                    
        elif form_type == 'marcar_llegada':
            cita_id = request.POST.get('cita_id')
            if cita_id:
                try:
                    cita = Cita.objects.get(id=cita_id)
                    cita.estado = 'En taller'
                    cita.save()
                except Cita.DoesNotExist:
                    pass
                    
        return redirect('agenda')

    hoy = timezone.now().date()
    
    filtro = request.GET.get('filtro', 'pendientes')
    ano_seleccionado = request.GET.get('ano', '')
    mes_seleccionado = request.GET.get('mes', '')
    
    if filtro == 'historial':
        citas_historial = Cita.objects.filter(estado__in=['En taller', 'Cancelada'])
        
        if ano_seleccionado and ano_seleccionado.isdigit():
            citas_historial = citas_historial.filter(fecha_hora__year=int(ano_seleccionado))
        if mes_seleccionado and mes_seleccionado.isdigit():
            citas_historial = citas_historial.filter(fecha_hora__month=int(mes_seleccionado))
            
        if not ano_seleccionado and not mes_seleccionado:
            inicio_semana = hoy - timedelta(days=hoy.weekday()) 
            fin_semana = inicio_semana + timedelta(days=6)      
            citas_historial = citas_historial.filter(fecha_hora__date__gte=inicio_semana, fecha_hora__date__lte=fin_semana)
            
        citas_hoy = citas_historial.order_by('-fecha_hora')
        citas_proximas = []
    else:
        citas_hoy = Cita.objects.filter(fecha_hora__date=hoy, estado='Pendiente').order_by('fecha_hora')
        citas_proximas = Cita.objects.filter(fecha_hora__date__gt=hoy, estado='Pendiente').order_by('fecha_hora')[:15]
    
    anos_crudos = Cita.objects.filter(estado__in=['En taller', 'Cancelada']).annotate(year=ExtractYear('fecha_hora')).values_list('year', flat=True)
    anos_disponibles = sorted(list(set(filter(None, anos_crudos))), reverse=True)
    if not anos_disponibles:
        anos_disponibles = [hoy.year]
        
    context = {
        'citas_hoy': citas_hoy,
        'citas_proximas': citas_proximas,
        'filtro': filtro,
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado.isdigit() else '',
        'mes_seleccionado': str(mes_seleccionado),
        'anos_disponibles': anos_disponibles,
    }
    return render(request, 'taller/agenda.html', context)


@login_required
def editar_cita(request, cita_id):
    from django.shortcuts import get_object_or_404, redirect
    from .models import Cita
    from datetime import datetime
    from django.utils import timezone

    cita = get_object_or_404(Cita, id=cita_id)

    if request.method == 'POST':
        cita.nombre_cliente = request.POST.get('nombre_cliente')
        cita.vehiculo_info = request.POST.get('vehiculo_info')
        cita.motivo = request.POST.get('motivo')
        cita.estado = request.POST.get('estado')
        cita.notas_adicionales = request.POST.get('notas_adicionales')

        fecha_str = request.POST.get('fecha')
        hora_str = request.POST.get('hora')
        if fecha_str and hora_str:
            try:
                fecha_completa = f"{fecha_str} {hora_str}"
                fecha_obj = datetime.strptime(fecha_completa, "%Y-%m-%d %H:%M")
                cita.fecha_hora = timezone.make_aware(fecha_obj)
            except Exception:
                pass 

        cita.save()
        return redirect('agenda') 

    context = {
        'cita': cita,
        'fecha_formato': cita.fecha_hora.strftime('%Y-%m-%d') if cita.fecha_hora else '',
        'hora_formato': cita.fecha_hora.strftime('%H:%M') if cita.fecha_hora else '',
    }
    return render(request, 'taller/editar_cita.html', context)  

@login_required
def ver_historial_ia(request):
    from .models import HistorialIA
    conversaciones = HistorialIA.objects.all()[:50]
    
    return render(request, 'taller/historial_ia.html', {'conversaciones': conversaciones})

@login_required
@bloquear_lectura
def sincronizar_escaner(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("🔒 Acceso denegado. Solo Administración puede sincronizar el escáner.")
        
    from .lector_correos import descargar_y_asignar_reportes
    
    resultado = descargar_y_asignar_reportes()
    
    if resultado['status'] == 'success':
        messages.success(request, resultado['mensaje'])
    elif resultado['status'] == 'warning':
        messages.warning(request, resultado['mensaje'])
    elif resultado['status'] == 'info':
        messages.info(request, resultado['mensaje'])
    else:
        messages.error(request, resultado['mensaje'])
        
    return redirect('lista_ordenes')

@login_required
def alternar_estado_taller(request):
    """Cierra o abre el taller globalmente pausando/reanudando tiempos"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("🔒 Acceso denegado. Solo Administración puede abrir/cerrar el taller.")

    estados_activos = ['En Diagnostico', 'En Reparacion', 'En Pruebas']
    ahora = timezone.now()
    
    pausas_activas = HistorialEstadoOrden.objects.filter(es_pausa_jornada=True, fecha_fin__isnull=True)

    if not pausas_activas.exists():
        ordenes_a_pausar = OrdenDeReparacion.objects.filter(estado__in=estados_activos)
        count = 0

        for orden in ordenes_a_pausar:
            ultimo = orden.historial_estados.filter(fecha_fin__isnull=True).first()
            if ultimo:
                ultimo.fecha_fin = ahora
                ultimo.save()
            
            HistorialEstadoOrden.objects.create(
                orden=orden,
                estado=f"PAUSA: {orden.estado}",
                fecha_inicio=ahora,
                es_pausa_jornada=True,
                usuario=request.user
            )
            count += 1
        
        messages.success(request, f"🌙 Taller cerrado. Se han pausado {count} coches activos.")
    
    else:
        count = 0

        for pausa in pausas_activas:
            pausa.fecha_fin = ahora
            pausa.save()

            estado_original = pausa.estado.replace("PAUSA: ", "")
            HistorialEstadoOrden.objects.create(
                orden=pausa.orden,
                estado=estado_original,
                fecha_inicio=ahora,
                usuario=request.user
            )
            count += 1
            
        messages.success(request, f"☀️ Taller abierto. Se han reanudado {count} coches.")

    return redirect(request.META.get('HTTP_REFERER', 'home'))


def estado_vehiculo_publico(request, signed_id):
    """Vista pública y segura para que el cliente vea su coche sin precios"""
    signer = Signer()
    try:
        original_id = signer.unsign(signed_id)
        orden = get_object_or_404(OrdenDeReparacion.objects.select_related('cliente', 'vehiculo').prefetch_related('fotos'), id=original_id)
    except BadSignature:
        return HttpResponseForbidden("<h2>🔒 ENLACE INVÁLIDO</h2><p>Este enlace de seguimiento es incorrecto o ha caducado.</p>")
    
    # Seleccionamos solo las notas que el mecánico haya marcado como visibles
    notas_publicas = orden.notas_internas.filter(visible_cliente=True).order_by('-fecha_creacion')
    
    context = {
        'orden': orden,
        'fotos': orden.fotos.all(),
        'notas_publicas': notas_publicas, # PASAMOS LAS NOTAS AL HTML
    }
    return render(request, 'taller/estado_cliente.html', context)

def fichador_mecanicos(request):
    mensaje = ""
    # Usamos localtime() para asegurarnos de que coge el día exacto de España
    hoy = timezone.localtime().date()
    
    if request.method == 'POST':
        empleado_id = request.POST.get('empleado_id')
        accion = request.POST.get('accion')
        empleado = Empleado.objects.get(id=empleado_id)
        
        if accion == 'entrar':
            # Evitamos que fichen entrada dos veces seguidas por error
            turno_abierto = Asistencia.objects.filter(empleado=empleado, fecha=hoy, hora_salida__isnull=True).exists()
            if not turno_abierto:
                # FORZAMOS LA HORA LOCAL DE ESPAÑA AL ENTRAR
                hora_exacta = timezone.localtime().time()
                Asistencia.objects.create(empleado=empleado, fecha=hoy, hora_entrada=hora_exacta)
                mensaje = f"¡Hola {empleado.nombre}! Entrada registrada a las {hora_exacta.strftime('%H:%M')}."
            else:
                mensaje = f"¡Oye {empleado.nombre}, ya estabas trabajando!"
                
        elif accion == 'salir':
            asistencia = Asistencia.objects.filter(empleado=empleado, fecha=hoy, hora_salida__isnull=True).first()
            if asistencia:
                # FORZAMOS LA HORA LOCAL DE ESPAÑA AL SALIR
                hora_exacta = timezone.localtime().time()
                asistencia.hora_salida = hora_exacta
                asistencia.save()
                mensaje = f"¡Hasta luego {empleado.nombre}! Salida registrada a las {hora_exacta.strftime('%H:%M')}."

    empleados_data = []
    empleados_db = Empleado.objects.all()
    for emp in empleados_db:
        turno_abierto = Asistencia.objects.filter(empleado=emp, fecha=hoy, hora_salida__isnull=True).exists()
        empleados_data.append({
            'id': emp.id,
            'nombre': emp.nombre,
            'trabajando_ahora': turno_abierto
        })
        
    return render(request, 'taller/fichador.html', {
        'empleados': empleados_data,
        'mensaje': mensaje
    })


@login_required
def panel_nominas(request):
    if request.method == 'POST':
        empleado_id = request.POST.get('empleado_id')
        metodo_pago = request.POST.get('metodo_pago', 'EFECTIVO') 
        empleado = Empleado.objects.get(id=empleado_id)
        
        asistencias_pendientes = Asistencia.objects.filter(empleado=empleado, pagado=False, hora_salida__isnull=False)
        dias_trabajados = asistencias_pendientes.values('fecha').distinct().count()
        
        # --- CÁLCULO INTELIGENTE FIJO VS DIARIO ---
        if empleado.es_sueldo_fijo:
            dias_mes = obtener_dias_laborables_mes(timezone.now().date())
            valor_dia = empleado.sueldo_fijo_mensual / dias_mes
            sueldo_bruto = Decimal(dias_trabajados) * valor_dia
        else:
            sueldo_bruto = dias_trabajados * empleado.sueldo_por_dia
        
        adelantos_pendientes = AdelantoSueldo.objects.filter(empleado=empleado, liquidado=False)
        total_adelantos = sum(a.importe for a in adelantos_pendientes)
        
        total_a_pagar = sueldo_bruto - total_adelantos

        if total_a_pagar > 0:
            # Crea el gasto con el método que hayamos elegido (Banco o Efectivo)
            Gasto.objects.create(
                fecha=timezone.now().date(),
                categoria='Sueldos',
                importe=total_a_pagar,
                descripcion=f"NÓMINA {empleado.nombre} ({dias_trabajados} días). Descontados {total_adelantos}€.",
                metodo_pago=metodo_pago, 
                empleado=empleado
            )
            asistencias_pendientes.update(pagado=True)
            adelantos_pendientes.update(liquidado=True)
            messages.success(request, f"¡Nómina de {empleado.nombre} liquidada correctamente mediante {metodo_pago}!")
            
        elif total_a_pagar <= 0 and sueldo_bruto > 0:
            # Si lo que se le debe es exactamente 0 porque los adelantos cubren todo el mes
            asistencias_pendientes.update(pagado=True)
            adelantos_pendientes.update(liquidado=True)
            messages.success(request, f"Nómina de {empleado.nombre} liquidada a cero (los adelantos cubrían todo el sueldo).")
        else:
            messages.warning(request, f"No hay saldo a favor para {empleado.nombre} o los adelantos superan lo que ha trabajado.")
            
        return redirect('panel_nominas')

    # --- LÓGICA DE MOSTRAR PANTALLA ---
    empleados = Empleado.objects.all()
    datos_nominas = []
    
    for emp in empleados:
        asistencias_pendientes = Asistencia.objects.filter(empleado=emp, pagado=False, hora_salida__isnull=False)
        dias_pendientes = asistencias_pendientes.values('fecha').distinct().count()
        
        fechas_exactas = asistencias_pendientes.values_list('fecha', flat=True).distinct()
        fechas_str = ", ".join([f.strftime('%d/%m') for f in fechas_exactas])
        
        # --- CÁLCULO INTELIGENTE FIJO VS DIARIO ---
        if emp.es_sueldo_fijo:
            dias_mes = obtener_dias_laborables_mes(timezone.now().date())
            valor_dia = emp.sueldo_fijo_mensual / dias_mes
            sueldo_bruto = Decimal(dias_pendientes) * valor_dia
        else:
            valor_dia = emp.sueldo_por_dia
            sueldo_bruto = dias_pendientes * valor_dia
            dias_mes = 0 # No aplica para diarios
            
        adelantos_pendientes = AdelantoSueldo.objects.filter(empleado=emp, liquidado=False)
        total_adelantos = sum(a.importe for a in adelantos_pendientes)
        total_neto = sueldo_bruto - total_adelantos
        
        datos_nominas.append({
            'empleado': emp,
            'dias': dias_pendientes,
            'fechas_str': fechas_str,
            'bruto': sueldo_bruto,
            'adelantos': total_adelantos,
            'neto': total_neto,
            'valor_dia': valor_dia,
            'dias_mes': dias_mes
        })

    return render(request, 'taller/panel_nominas.html', {'datos_nominas': datos_nominas})

# --- NUEVA FUNCIÓN MÁGICA PARA DAR ADELANTOS ---
def dar_adelanto(request):
    if request.method == 'POST':
        empleado_id = request.POST.get('empleado_id')
        importe = request.POST.get('importe')
        motivo = request.POST.get('motivo', 'Adelanto de nómina')
        metodo_pago = request.POST.get('metodo_pago', 'EFECTIVO')
        fecha_str = request.POST.get('fecha_adelanto') # Atrapamos la fecha del formulario
        
        empleado = Empleado.objects.get(id=empleado_id)
        
        # Convertimos la fecha (si el usuario la dejó en blanco por error, usamos hoy)
        try:
            fecha_adelanto = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            fecha_adelanto = timezone.now().date()
        
        # 1. Anotamos que nos debe este dinero de su sueldo con la fecha correcta
        AdelantoSueldo.objects.create(
            empleado=empleado,
            importe=importe,
            motivo=motivo,
            fecha=fecha_adelanto # Usamos la fecha elegida
        )
        
        # 2. Registramos la salida real del dinero de la caja/banco en ese día
        Gasto.objects.create(
            fecha=fecha_adelanto, # Usamos la fecha elegida
            categoria='Sueldos',
            importe=importe,
            descripcion=f"ADELANTO NÓMINA: {empleado.nombre} - {motivo}",
            metodo_pago=metodo_pago,
            empleado=empleado
        )
        
        messages.success(request, f"¡Adelanto de {importe}€ registrado para el día {fecha_adelanto.strftime('%d/%m/%Y')}!")
        
    return redirect('panel_nominas')

def detalle_nomina(request, empleado_id):
    empleado = get_object_or_404(Empleado, id=empleado_id)
    hoy = timezone.now().date()
    
    # --- FILTRO DE MES Y AÑO ---
    mes_seleccionado = int(request.GET.get('mes', hoy.month))
    ano_seleccionado = int(request.GET.get('ano', hoy.year))
    
    asistencias_db = Asistencia.objects.filter(
        empleado=empleado, 
        hora_salida__isnull=False,
        fecha__year=ano_seleccionado,
        fecha__month=mes_seleccionado
    ).order_by('-fecha', '-hora_entrada')
    
    adelantos = AdelantoSueldo.objects.filter(
        empleado=empleado,
        fecha__year=ano_seleccionado,
        fecha__month=mes_seleccionado
    ).order_by('-fecha')
    
    pagos = Gasto.objects.filter(
        empleado=empleado, 
        categoria='Sueldos',
        fecha__year=ano_seleccionado,
        fecha__month=mes_seleccionado
    ).order_by('-fecha')

    # --- LÓGICA DE CÁLCULO ESTRICTO DE HORAS ---
    def formatear_segundos(segs):
        horas = int(segs // 3600)
        minutos = int((segs % 3600) // 60)
        return f"{horas}h {minutos}m"

    # Agrupamos todos los fichajes por día
    agrupado_por_dia = defaultdict(list)
    for a in asistencias_db:
        agrupado_por_dia[a.fecha].append(a)

    dias_procesados = []
    semanas_dict = defaultdict(lambda: {'segundos': 0, 'dias': set()})
    total_mes_segundos = 0

    for fecha, registros in agrupado_por_dia.items():
        total_dia_segundos = 0
        fichajes_str = []
        pagado_dia = True
        
        # Sacamos a qué semana del año pertenece este día
        semana_iso = fecha.isocalendar()[1]
        
        for r in registros:
            if not r.pagado: pagado_dia = False
            
            # Calculamos duración exacta del turno
            t1 = datetime.combine(fecha, r.hora_entrada)
            t2 = datetime.combine(fecha, r.hora_salida)
            
            # ESCUDO ANTIBALAS: Control de clics rápidos vs turnos de noche
            if t2 < t1: 
                if (t1 - t2).total_seconds() < 300: # Menos de 5 min de diferencia (clic de prueba)
                    t2 = t1 
                else:
                    t2 += timedelta(days=1) # Turno de noche real (salió al día siguiente)
                    
            segundos_turno = (t2 - t1).total_seconds()
            total_dia_segundos += segundos_turno
            total_mes_segundos += segundos_turno
            
            # Sumamos a la semana correspondiente
            semanas_dict[semana_iso]['segundos'] += segundos_turno
            semanas_dict[semana_iso]['dias'].add(fecha)
            
            # Guardamos los tramos de horas para enseñarlos (Ej: 08:00-14:00)
            fichajes_str.append(f"{r.hora_entrada.strftime('%H:%M')}-{r.hora_salida.strftime('%H:%M')}")

        dias_procesados.append({
            'fecha': fecha,
            'fichajes': " | ".join(fichajes_str),
            'total_horas': formatear_segundos(total_dia_segundos),
            'pagado': pagado_dia
        })

    # Ordenamos de más reciente a más antiguo
    dias_procesados = sorted(dias_procesados, key=lambda x: x['fecha'], reverse=True)

    # Procesamos el resumen semanal para la pantalla
    semanas_list = []
    for sem, data in semanas_dict.items():
        dias_ordenados = sorted(list(data['dias']))
        inicio = dias_ordenados[0].strftime('%d/%m')
        fin = dias_ordenados[-1].strftime('%d/%m')
        rango = f"{inicio} al {fin}" if inicio != fin else f"{inicio}"
        
        semanas_list.append({
            'semana': sem,
            'rango': rango,
            'total_horas': formatear_segundos(data['segundos'])
        })
    semanas_list = sorted(semanas_list, key=lambda x: x['semana'], reverse=True)

    # Listas para el filtro HTML
    meses_del_ano = list(range(1, 13))
    anos_disponibles = list(range(2024, hoy.year + 2))
    
    return render(request, 'taller/detalle_nomina.html', {
        'empleado': empleado,
        'dias_procesados': dias_procesados,
        'semanas_list': semanas_list,
        'total_mes_horas': formatear_segundos(total_mes_segundos),
        'adelantos': adelantos,
        'pagos': pagos,
        'mes_seleccionado': mes_seleccionado,
        'ano_seleccionado': ano_seleccionado,
        'meses_del_ano': meses_del_ano,
        'anos_disponibles': anos_disponibles,
    })