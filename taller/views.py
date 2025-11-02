# taller/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import (
    Ingreso, Gasto, Cliente, Vehiculo, OrdenDeReparacion, Empleado,
    TipoConsumible, CompraConsumible, Factura, LineaFactura, FotoVehiculo,
    Presupuesto, LineaPresupuesto, UsoConsumible, AjusteStockConsumible # Importar AjusteStockConsumible
)
from django.db.models import Sum, F, Q
from django.db import transaction
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from django.http import HttpResponse, HttpResponseForbidden # <-- Importar HttpResponseForbidden
from django.template.loader import get_template
from xhtml2pdf import pisa
import os
from django.conf import settings
from django.utils import timezone
import json
from django.urls import reverse
from django.contrib.auth.decorators import login_required # <-- Importar login_required

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


# --- VISTA HOME (TOTALMENTE MODIFICADA) ---
@login_required
def home(request):
    hoy = timezone.now()

    # --- Parte 1: Obtener el mes y año a visualizar ---
    ano_seleccionado_str = request.GET.get('ano')
    mes_seleccionado_str = request.GET.get('mes')

    if ano_seleccionado_str:
        try:
            ano_actual = int(ano_seleccionado_str)
        except (ValueError, TypeError):
            ano_actual = hoy.year
    else:
        ano_actual = hoy.year

    if mes_seleccionado_str:
        try:
            mes_actual = int(mes_seleccionado_str)
            if not 1 <= mes_actual <= 12:
                mes_actual = hoy.month
        except (ValueError, TypeError):
            mes_actual = hoy.month
    else:
        mes_actual = hoy.month
    
    # --- Parte 2: Cálculo de Ingresos/Gastos MENSUALES (Para las 2 primeras tarjetas) ---
    ingresos_mes = Ingreso.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    gastos_mes = Gasto.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    
    total_ingresos = ingresos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos = gastos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

    # --- Parte 3: Cálculo de Balances HISTÓRICOS (Para las 2 últimas tarjetas) ---
    # ¡Esta es la corrección! Hacemos consultas nuevas sin filtro de fecha.

    # Total HISTÓRICO de ingresos en efectivo (No TPV)
    total_ingresos_efectivo_hist = Ingreso.objects.filter(es_tpv=False).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    # Total HISTÓRICO de gastos en efectivo (No Tarjeta)
    total_gastos_efectivo_hist = Gasto.objects.filter(pagado_con_tarjeta=False).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    # El balance de caja es el total histórico
    balance_caja = total_ingresos_efectivo_hist - total_gastos_efectivo_hist

    # Total HISTÓRICO de ingresos por TPV
    total_ingresos_tpv_hist = Ingreso.objects.filter(es_tpv=True).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    # Total HISTÓRICO de gastos con tarjeta
    total_gastos_tarjeta_hist = Gasto.objects.filter(pagado_con_tarjeta=True).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    # El balance de tarjeta es el total histórico
    balance_tarjeta = total_ingresos_tpv_hist - total_gastos_tarjeta_hist

    # --- Parte 4: Movimientos Recientes (Esto se queda igual) ---
    ultimos_gastos = Gasto.objects.order_by('-id')[:5]
    ultimos_ingresos = Ingreso.objects.order_by('-id')[:5]
    movimientos_combinados = sorted(
        list(ultimos_gastos) + list(ultimos_ingresos),
        key=lambda mov: mov.fecha if hasattr(mov, 'fecha') else timezone.now().date(),
        reverse=True
    )
    movimientos_recientes = movimientos_combinados[:5]

    # --- Parte 5: Cálculo de Stock (Esto se queda igual) ---
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
    
    # --- Parte 6: Contexto (Añadimos todo) ---
    is_read_only_user = request.user.groups.filter(name='Solo Ver').exists()
    
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)

    context = {
        'total_ingresos': total_ingresos,       # Mensual
        'total_gastos': total_gastos,         # Mensual
        'balance_caja': balance_caja,           # ¡Histórico!
        'balance_tarjeta': balance_tarjeta,     # ¡Histórico!
        'movimientos_recientes': movimientos_recientes,
        'alertas_stock': alertas_stock,
        'is_read_only_user': is_read_only_user,
        
        # Filtros de fecha para controlar los balances mensuales
        'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_actual,
        'mes_seleccionado': mes_actual,
        'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/home.html', context)
# --- FIN VISTA HOME ---


# --- VISTA INGRESAR VEHÍCULO ---
@login_required
def ingresar_vehiculo(request):
    if request.method == 'POST':
        if not request.user.has_perm('taller.add_ordendereparacion'):
            return HttpResponseForbidden("No tienes permiso para crear órdenes de reparación.")

        nombre_cliente = request.POST['cliente_nombre'].upper()
        telefono_cliente = request.POST['cliente_telefono']
        matricula_vehiculo = request.POST['vehiculo_matricula'].upper()
        marca_vehiculo = request.POST['vehiculo_marca'].upper()
        modelo_vehiculo = request.POST['vehiculo_modelo'].upper()
        kilometraje_vehiculo_str = request.POST.get('vehiculo_kilometraje')
        kilometraje_vehiculo = int(kilometraje_vehiculo_str) if kilometraje_vehiculo_str else 0
        problema_reportado = request.POST['problema'].upper()

        with transaction.atomic():
            cliente, created = Cliente.objects.get_or_create(
                telefono=telefono_cliente, defaults={'nombre': nombre_cliente}
            )
            if not created and nombre_cliente and cliente.nombre != nombre_cliente:
                cliente.nombre = nombre_cliente
                cliente.save()

            vehiculo, v_created = Vehiculo.objects.get_or_create(
                matricula=matricula_vehiculo,
                defaults={'marca': marca_vehiculo, 'modelo': modelo_vehiculo, 'kilometraje': kilometraje_vehiculo, 'cliente': cliente}
            )
            if not v_created:
                if kilometraje_vehiculo > vehiculo.kilometraje:
                    vehiculo.kilometraje = kilometraje_vehiculo
                if vehiculo.cliente != cliente:
                    vehiculo.cliente = cliente
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
                except Presupuesto.DoesNotExist:
                    presupuesto = None

            nueva_orden = OrdenDeReparacion.objects.create(
                cliente=cliente, vehiculo=vehiculo, problema=problema_reportado, presupuesto_origen=presupuesto
            )

            if presupuesto:
                presupuesto.estado = 'Convertido'
                presupuesto.save()

        descripciones = ['Frontal', 'Trasera', 'Lateral Izquierdo', 'Lateral Derecho', 'Cuadro/Km']
        for i in range(1, 6):
            foto_campo = f'foto{i}'
            if foto_campo in request.FILES:
                try:
                    FotoVehiculo.objects.create(
                        orden=nueva_orden, imagen=request.FILES[foto_campo], descripcion=descripciones[i-1]
                    )
                except Exception as e:
                    print(f"Error al guardar foto {i}: {e}")

        return redirect('detalle_orden', orden_id=nueva_orden.id)

    presupuestos_disponibles = Presupuesto.objects.filter(estado='Aceptado').select_related('cliente', 'vehiculo').order_by('-fecha_creacion')
    context = { 'presupuestos_disponibles': presupuestos_disponibles }
    return render(request, 'taller/ingresar_vehiculo.html', context)

# --- VISTA AÑADIR GASTO (MODIFICADA) ---
@login_required
def anadir_gasto(request):
    if request.method == 'POST':
        if not (request.user.has_perm('taller.add_gasto') or request.user.has_perm('taller.add_compraconsumible')):
             return HttpResponseForbidden("No tienes permiso para añadir gastos o compras.")

        categoria = request.POST['categoria']
        pagado_con_tarjeta = request.POST.get('pagado_con_tarjeta') == 'true'

        if categoria == 'Compra de Consumibles':
            if not request.user.has_perm('taller.add_compraconsumible'):
                return HttpResponseForbidden("No tienes permiso para añadir compras de consumibles.")

            tipo_id = request.POST.get('tipo_consumible')
            fecha_compra_str = request.POST.get('fecha_compra')
            cantidad_str = request.POST.get('cantidad')
            coste_total_str = request.POST.get('coste_total')

            if not all([tipo_id, fecha_compra_str, cantidad_str, coste_total_str]):
                 return redirect('anadir_gasto')
            try:
                with transaction.atomic():
                    cantidad = Decimal(cantidad_str); coste_total = Decimal(coste_total_str)
                    if cantidad <= 0 or coste_total < 0: return redirect('anadir_gasto')
                    tipo_consumible = get_object_or_404(TipoConsumible, id=tipo_id)
                    try: fecha_compra = datetime.strptime(fecha_compra_str, '%Y-%m-%d').date()
                    except ValueError: return redirect('anadir_gasto')

                    CompraConsumible.objects.create(tipo=tipo_consumible, fecha_compra=fecha_compra, cantidad=cantidad, coste_total=coste_total)
                    
                    # --- CORREGIDO --- (Se añade la fecha_compra al crear el Gasto)
                    Gasto.objects.create(fecha=fecha_compra, categoria=categoria, importe=coste_total,
                                        descripcion=f"Compra de {cantidad} {tipo_consumible.unidad_medida} de {tipo_consumible.nombre}",
                                        pagado_con_tarjeta=pagado_con_tarjeta)
                    # --- FIN CORRECCIÓN ---
            except (ValueError, TypeError, Decimal.InvalidOperation): return redirect('anadir_gasto')
        else:
            if not request.user.has_perm('taller.add_gasto'):
                 return HttpResponseForbidden("No tienes permiso para añadir gastos.")

            importe_str = request.POST.get('importe'); descripcion = request.POST.get('descripcion', '')
            
            # --- CORREGIDO --- (Se lee la fecha del formulario)
            fecha_gasto_str = request.POST.get('fecha_gasto')
            try: fecha_gasto = datetime.strptime(fecha_gasto_str, '%Y-%m-%d').date() if fecha_gasto_str else timezone.now().date()
            except ValueError: fecha_gasto = timezone.now().date()
            # --- FIN CORRECCIÓN ---

            try:
                importe = Decimal(importe_str) if importe_str else None
                if importe is not None and importe < 0: importe = None
            except (ValueError, TypeError, Decimal.InvalidOperation): importe = None

            # --- CORREGIDO --- (Se pasa la fecha_gasto al crear el Gasto)
            gasto = Gasto(fecha=fecha_gasto, categoria=categoria, importe=importe, descripcion=descripcion.upper(), pagado_con_tarjeta=pagado_con_tarjeta)
            # --- FIN CORRECCIÓN ---

            if categoria in ['Repuestos', 'Otros']:
                vehiculo_id = request.POST.get('vehiculo')
                if vehiculo_id:
                    try:
                        vehiculo = Vehiculo.objects.get(id=vehiculo_id)
                        ordenes_relevantes = obtener_ordenes_relevantes()
                        if ordenes_relevantes.filter(vehiculo=vehiculo).exists(): gasto.vehiculo = vehiculo
                    except Vehiculo.DoesNotExist: pass
            if categoria == 'Sueldos':
                empleado_id = request.POST.get('empleado')
                if empleado_id:
                     try: gasto.empleado = Empleado.objects.get(id=empleado_id)
                     except Empleado.DoesNotExist: pass
            gasto.save()

            if gasto.vehiculo and categoria in ['Repuestos', 'Otros']:
                try:
                    orden_a_actualizar = OrdenDeReparacion.objects.filter(vehiculo=gasto.vehiculo, estado__in=['Recibido', 'En Diagnostico']).latest('fecha_entrada')
                    orden_a_actualizar.estado = 'En Reparacion'
                    orden_a_actualizar.save()
                except OrdenDeReparacion.DoesNotExist: pass

        return redirect('home')

    # --- Lógica GET ---
    ordenes_relevantes = obtener_ordenes_relevantes()
    vehiculos_ids_relevantes = ordenes_relevantes.values_list('vehiculo_id', flat=True).distinct()
    vehiculos_filtrados = Vehiculo.objects.filter(id__in=vehiculos_ids_relevantes).select_related('cliente')
    empleados = Empleado.objects.all()
    tipos_consumible = TipoConsumible.objects.all()
    categorias_gasto_choices = [choice for choice in Gasto.CATEGORIA_CHOICES if choice[0] != 'Compra de Consumibles']
    context = {
        'vehiculos': vehiculos_filtrados, 'empleados': empleados, 'tipos_consumible': tipos_consumible,
        'categorias_gasto': Gasto.CATEGORIA_CHOICES, 'categorias_gasto_select': categorias_gasto_choices,
    }
    return render(request, 'taller/anadir_gasto.html', context)
# --- FIN VISTA AÑADIR GASTO ---


# --- VISTA REGISTRAR INGRESO (MODIFICADA) ---
@login_required
def registrar_ingreso(request):
    if request.method == 'POST':
        if not request.user.has_perm('taller.add_ingreso'):
            return HttpResponseForbidden("No tienes permiso para registrar ingresos.")

        categoria = request.POST['categoria']; importe_str = request.POST.get('importe')
        descripcion = request.POST.get('descripcion', ''); es_tpv = request.POST.get('es_tpv') == 'true'
        
        # --- CORREGIDO --- (Se lee la fecha del formulario)
        fecha_ingreso_str = request.POST.get('fecha_ingreso')
        try: fecha_ingreso = datetime.strptime(fecha_ingreso_str, '%Y-%m-%d').date() if fecha_ingreso_str else timezone.now().date()
        except ValueError: fecha_ingreso = timezone.now().date()
        # --- FIN CORRECCIÓN ---

        try:
            importe = Decimal(importe_str) if importe_str else Decimal('0.00')
            if importe <= 0: return redirect('registrar_ingreso')
        except (ValueError, TypeError, Decimal.InvalidOperation): return redirect('registrar_ingreso')

        # --- CORREGIDO --- (Se pasa la fecha_ingreso al crear el Ingreso)
        ingreso = Ingreso(fecha=fecha_ingreso, categoria=categoria, importe=importe, descripcion=descripcion.upper(), es_tpv=es_tpv)
        # --- FIN CORRECCIÓN ---

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

    # --- Lógica GET ---
    ordenes_filtradas = obtener_ordenes_relevantes().order_by('-fecha_entrada')
    categorias_ingreso = Ingreso.CATEGORIA_CHOICES
    context = { 'ordenes': ordenes_filtradas, 'categorias_ingreso': categorias_ingreso }
    return render(request, 'taller/registrar_ingreso.html', context)
# --- FIN VISTA REGISTRAR INGRESO ---


# --- VISTA STOCK INICIAL ---
@login_required
def stock_inicial_consumible(request):
    if not request.user.has_perm('taller.add_compraconsumible'):
         return HttpResponseForbidden("No tienes permiso para registrar compras.")

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

    # --- Lógica GET ---
    tipos_consumible = TipoConsumible.objects.all()
    context = { 'tipos_consumible': tipos_consumible }
    return render(request, 'taller/stock_inicial_consumible.html', context)

# --- VISTA CREAR PRESUPUESTO ---
@login_required
def crear_presupuesto(request):
    if request.method == 'POST':
        if not request.user.has_perm('taller.add_presupuesto'):
            return HttpResponseForbidden("No tienes permiso para crear presupuestos.")

        cliente_id = request.POST.get('cliente_existente'); nombre_cliente_form = request.POST.get('cliente_nombre', '').upper(); telefono_cliente_form = request.POST.get('cliente_telefono', '')
        cliente = None; created = False
        try: # Usar transacción para la creación completa
            with transaction.atomic():
                if cliente_id:
                    try: cliente = Cliente.objects.get(id=cliente_id)
                    except Cliente.DoesNotExist: pass
                elif nombre_cliente_form and telefono_cliente_form:
                    try:
                        cliente = Cliente.objects.get(telefono=telefono_cliente_form)
                        if nombre_cliente_form and cliente.nombre != nombre_cliente_form: cliente.nombre = nombre_cliente_form; cliente.save()
                    except Cliente.DoesNotExist: cliente = Cliente.objects.create(nombre=nombre_cliente_form, telefono=telefono_cliente_form); created = True
                if not cliente: return HttpResponse("Error: Cliente inválido o no proporcionado.", status=400)

                vehiculo_id = request.POST.get('vehiculo_existente'); matricula_nueva = request.POST.get('matricula_nueva', '').upper(); marca_nueva = request.POST.get('marca_nueva', '').upper(); modelo_nuevo = request.POST.get('modelo_nuevo', '').upper()
                vehiculo = None
                if vehiculo_id:
                    try:
                        vehiculo = Vehiculo.objects.get(id=vehiculo_id)
                        if vehiculo.cliente != cliente: vehiculo.cliente = cliente; vehiculo.save()
                    except Vehiculo.DoesNotExist: pass
                # Validar que si no hay vehiculo_id, se proporcionen datos nuevos (opcional, depende de si quieres permitir presupuestos sin vehículo)
                # elif not matricula_nueva:
                #    return HttpResponse("Error: Debes seleccionar un vehículo existente o introducir datos de uno nuevo.", status=400)

                problema = request.POST.get('problema_o_trabajo', '').upper()
                presupuesto = Presupuesto.objects.create(cliente=cliente, vehiculo=vehiculo,
                    matricula_nueva=matricula_nueva if not vehiculo and matricula_nueva else None,
                    marca_nueva=marca_nueva if not vehiculo and marca_nueva else None,
                    modelo_nuevo=modelo_nuevo if not vehiculo and modelo_nuevo else None,
                    problema_o_trabajo=problema, estado='Pendiente')

                tipos_linea = request.POST.getlist('linea_tipo'); descripciones_linea = request.POST.getlist('linea_descripcion'); cantidades_linea = request.POST.getlist('linea_cantidad'); precios_linea = request.POST.getlist('linea_precio_unitario')
                total_estimado_calculado = Decimal('0.00'); lineas_creadas = False
                for i in range(len(tipos_linea)):
                    if all([tipos_linea[i], descripciones_linea[i], cantidades_linea[i], precios_linea[i]]):
                        try:
                            cantidad = Decimal(cantidades_linea[i]); precio_unitario = Decimal(precios_linea[i])
                            if cantidad <= 0 or precio_unitario < 0: continue
                            linea_total = cantidad * precio_unitario; total_estimado_calculado += linea_total
                            # Asegurar permiso para añadir líneas dentro del bucle
                            if not request.user.has_perm('taller.add_lineapresupuesto'):
                                raise PermissionError("No tienes permiso para añadir líneas al presupuesto.")

                            LineaPresupuesto.objects.create(presupuesto=presupuesto, tipo=tipos_linea[i], descripcion=descripciones_linea[i].upper(), cantidad=cantidad, precio_unitario_estimado=precio_unitario)
                            lineas_creadas = True
                        except (ValueError, TypeError, Decimal.InvalidOperation):
                            # Podríamos añadir un mensaje aquí o simplemente ignorar la línea inválida
                            pass
                        except PermissionError as pe:
                            raise # Re-lanzar para que lo capture el bloque exterior

                presupuesto.total_estimado = total_estimado_calculado; presupuesto.save()
                return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)
        except PermissionError as pe: # Capturar error de permiso fuera del bucle
             return HttpResponseForbidden(str(pe))
        except Exception as e: # Capturar otros errores inesperados
             # messages.error(request, f"Error inesperado al crear presupuesto: {e}") # Si usas messages
             print(f"Error inesperado al crear presupuesto: {e}") # Log simple
             # Redirigir a la misma página para que el usuario vea los datos que introdujo
             clientes = Cliente.objects.all().order_by('nombre'); vehiculos = Vehiculo.objects.select_related('cliente').order_by('matricula'); tipos_linea = LineaFactura.TIPO_CHOICES
             context = { 'clientes': clientes, 'vehiculos': vehiculos, 'tipos_linea': tipos_linea, 'error_message': f"Error: {e}" }
             return render(request, 'taller/crear_presupuesto.html', context, status=500)


    # --- Lógica GET ---
    clientes = Cliente.objects.all().order_by('nombre'); vehiculos = Vehiculo.objects.select_related('cliente').order_by('matricula'); tipos_linea = LineaFactura.TIPO_CHOICES
    context = { 'clientes': clientes, 'vehiculos': vehiculos, 'tipos_linea': tipos_linea }
    return render(request, 'taller/crear_presupuesto.html', context)

# --- VISTA LISTA PRESUPUESTOS ---
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


# --- VISTA DETALLE PRESUPUESTO ---
@login_required
def detalle_presupuesto(request, presupuesto_id):
    presupuesto = get_object_or_404(Presupuesto.objects.select_related('cliente', 'vehiculo__cliente').prefetch_related('lineas'), id=presupuesto_id)

    if request.method == 'POST' and 'nuevo_estado' in request.POST:
        if not request.user.has_perm('taller.change_presupuesto'):
            return HttpResponseForbidden("No tienes permiso para modificar presupuestos.")

        nuevo_estado = request.POST['nuevo_estado']; estados_validos_cambio = ['Aceptado', 'Rechazado', 'Pendiente']
        if nuevo_estado in estados_validos_cambio and presupuesto.estado != 'Convertido':
            presupuesto.estado = nuevo_estado; presupuesto.save()
            return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)

    orden_generada = None
    try: orden_generada = presupuesto.orden_generada
    except OrdenDeReparacion.DoesNotExist: pass
    context = { 'presupuesto': presupuesto, 'lineas': presupuesto.lineas.all(), 'estados_posibles': Presupuesto.ESTADO_CHOICES, 'orden_generada': orden_generada }
    return render(request, 'taller/detalle_presupuesto.html', context)

# --- VISTA EDITAR PRESUPUESTO ---
@login_required
def editar_presupuesto(request, presupuesto_id):
    presupuesto = get_object_or_404(Presupuesto.objects.select_related('cliente', 'vehiculo').prefetch_related('lineas'), id=presupuesto_id)
    if presupuesto.estado == 'Convertido': return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)

    if request.method == 'POST':
        if not (request.user.has_perm('taller.delete_presupuesto') and \
                request.user.has_perm('taller.add_presupuesto') and \
                request.user.has_perm('taller.add_lineapresupuesto') and \
                request.user.has_perm('taller.delete_lineapresupuesto')):
            return HttpResponseForbidden("No tienes permiso para editar presupuestos.")

        try:
            with transaction.atomic():
                presupuesto_id_original = presupuesto.id
                LineaPresupuesto.objects.filter(presupuesto=presupuesto).delete()
                presupuesto.delete()

                # (Recreación del presupuesto y líneas...)
                cliente_id = request.POST.get('cliente_existente'); nombre_cliente_form = request.POST.get('cliente_nombre', '').upper(); telefono_cliente_form = request.POST.get('cliente_telefono', '')
                cliente = None
                if cliente_id:
                    try: cliente = Cliente.objects.get(id=cliente_id)
                    except Cliente.DoesNotExist: pass
                elif nombre_cliente_form and telefono_cliente_form:
                    try:
                        cliente = Cliente.objects.get(telefono=telefono_cliente_form)
                        if nombre_cliente_form and cliente.nombre != nombre_cliente_form: cliente.nombre = nombre_cliente_form; cliente.save()
                    except Cliente.DoesNotExist: cliente = Cliente.objects.create(nombre=nombre_cliente_form, telefono=telefono_cliente_form)
                if not cliente: raise ValueError("Error: Cliente inválido.")

                vehiculo_id = request.POST.get('vehiculo_existente'); matricula_nueva = request.POST.get('matricula_nueva', '').upper(); marca_nueva = request.POST.get('marca_nueva', '').upper(); modelo_nuevo = request.POST.get('modelo_nuevo', '').upper()
                vehiculo = None
                if vehiculo_id:
                    try:
                        vehiculo = Vehiculo.objects.get(id=vehiculo_id)
                        if vehiculo.cliente != cliente: vehiculo.cliente = cliente; vehiculo.save()
                    except Vehiculo.DoesNotExist: pass
                elif not matricula_nueva: pass

                problema = request.POST.get('problema_o_trabajo', '').upper()
                nuevo_presupuesto = Presupuesto.objects.create(cliente=cliente, vehiculo=vehiculo,
                    matricula_nueva=matricula_nueva if not vehiculo and matricula_nueva else None,
                    marca_nueva=marca_nueva if not vehiculo and marca_nueva else None,
                    modelo_nuevo=modelo_nuevo if not vehiculo and modelo_nuevo else None,
                    problema_o_trabajo=problema, estado='Pendiente')

                tipos_linea = request.POST.getlist('linea_tipo'); descripciones_linea = request.POST.getlist('linea_descripcion'); cantidades_linea = request.POST.getlist('linea_cantidad'); precios_linea = request.POST.getlist('linea_precio_unitario')
                total_estimado_calculado = Decimal('0.00')
                for i in range(len(tipos_linea)):
                     if all([tipos_linea[i], descripciones_linea[i], cantidades_linea[i], precios_linea[i]]):
                         try:
                             cantidad = Decimal(cantidades_linea[i]); precio_unitario = Decimal(precios_linea[i])
                             if cantidad <= 0 or precio_unitario < 0: continue
                             linea_total = cantidad * precio_unitario; total_estimado_calculado += linea_total
                             LineaPresupuesto.objects.create(presupuesto=nuevo_presupuesto, tipo=tipos_linea[i], descripcion=descripciones_linea[i].upper(), cantidad=cantidad, precio_unitario_estimado=precio_unitario)
                         except (ValueError, TypeError, Decimal.InvalidOperation): raise ValueError("Una de las líneas de presupuesto es inválida.")
                nuevo_presupuesto.total_estimado = total_estimado_calculado; nuevo_presupuesto.save()
                return redirect('detalle_presupuesto', presupuesto_id=nuevo_presupuesto.id)
        except Exception as e:
            return redirect('editar_presupuesto', presupuesto_id=presupuesto_id_original)

    # --- Lógica GET ---
    clientes = Cliente.objects.all().order_by('nombre'); vehiculos = Vehiculo.objects.select_related('cliente').order_by('matricula'); tipos_linea = LineaFactura.TIPO_CHOICES
    lineas_existentes_list = []
    for linea in presupuesto.lineas.all():
        linea_data = { 'tipo': linea.tipo, 'descripcion': linea.descripcion, 'cantidad': float(linea.cantidad), 'precio_unitario_estimado': float(linea.precio_unitario_estimado) }
        lineas_existentes_list.append(linea_data)
    context = { 'presupuesto_existente': presupuesto, 'clientes': clientes, 'vehiculos': vehiculos, 'tipos_linea': tipos_linea, 'lineas_existentes_json': json.dumps(lineas_existentes_list) }
    return render(request, 'taller/editar_presupuesto.html', context)


# --- VISTA LISTA ORDENES ---
@login_required
def lista_ordenes(request):
    ordenes_activas = OrdenDeReparacion.objects.exclude(estado='Entregado').select_related('cliente', 'vehiculo').order_by('-fecha_entrada')
    context = { 'ordenes': ordenes_activas }
    return render(request, 'taller/lista_ordenes.html', context)


# --- VISTA DETALLE ORDEN ---
@login_required
def detalle_orden(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('cliente', 'vehiculo', 'presupuesto_origen').prefetch_related('fotos', 'ingreso_set', 'factura'), id=orden_id)
    repuestos = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
    gastos_otros = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')
    abonos = sum(ing.importe for ing in orden.ingreso_set.all()) if hasattr(orden, 'ingreso_set') and orden.ingreso_set.exists() else Decimal('0.00')
    tipos_consumible = TipoConsumible.objects.all()
    factura = None; pendiente_pago = Decimal('0.00')
    try: factura = orden.factura; pendiente_pago = factura.total_final - abonos
    except Factura.DoesNotExist: pass

    if request.method == 'POST' and 'nuevo_estado' in request.POST:
        if not request.user.has_perm('taller.change_ordendereparacion'):
            return HttpResponseForbidden("No tienes permiso para modificar órdenes.")

        nuevo_estado = request.POST['nuevo_estado']
        if nuevo_estado in [choice[0] for choice in OrdenDeReparacion.ESTADO_CHOICES]:
            orden.estado = nuevo_estado; orden.save()
        return redirect('detalle_orden', orden_id=orden.id)

    context = {
        'orden': orden, 'repuestos': repuestos, 'gastos_otros': gastos_otros, 'factura': factura,
        'abonos': abonos, 'pendiente_pago': pendiente_pago, 'tipos_consumible': tipos_consumible,
        'fotos': orden.fotos.all(), 'estados_orden': OrdenDeReparacion.ESTADO_CHOICES,
    }
    return render(request, 'taller/detalle_orden.html', context)


# --- VISTA HISTORIAL ORDENES ---
@login_required
def historial_ordenes(request):
    ordenes_qs = OrdenDeReparacion.objects.filter(estado='Entregado').select_related('cliente', 'vehiculo', 'factura')
    anos_y_meses_data = get_anos_y_meses_con_datos(); anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano'); mes_seleccionado = request.GET.get('mes')
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
    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None; mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None
    context = {
        'ordenes': ordenes, 'anos_y_meses': anos_y_meses_data, 'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/historial_ordenes.html', context)


# --- VISTA HISTORIAL MOVIMIENTOS ---
@login_required
def historial_movimientos(request):
    periodo = request.GET.get('periodo', 'semana'); hoy = timezone.now().date()
    gastos_qs = Gasto.objects.all(); ingresos_qs = Ingreso.objects.all()
    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        gastos_qs = gastos_qs.filter(fecha__gte=inicio_semana); ingresos_qs = ingresos_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        gastos_qs = gastos_qs.filter(fecha__year=hoy.year, fecha__month=hoy.month)
        ingresos_qs = ingresos_qs.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    movimientos = sorted(list(gastos_qs) + list(ingresos_qs), key=lambda x: (x.fecha, -x.id if hasattr(x, 'id') else 0), reverse=True)
    context = { 'movimientos': movimientos, 'periodo_seleccionado': periodo }
    return render(request, 'taller/historial_movimientos.html', context)


# --- VISTA EDITAR MOVIMIENTO ---
@login_required
def editar_movimiento(request, tipo, movimiento_id):
    permiso_necesario = f'taller.change_{tipo}'
    if not request.user.has_perm(permiso_necesario):
         return HttpResponseForbidden("No tienes permiso para editar este tipo de movimiento.")

    if tipo not in ['gasto', 'ingreso']: return redirect('historial_movimientos')
    admin_url_name = f'admin:taller_{tipo}_change'
    try: admin_url = reverse(admin_url_name, args=[movimiento_id]); return redirect(admin_url)
    except Exception as e:
        print(f"Error reversing admin URL: {e}")
        return redirect(f'/admin/taller/{tipo}/{movimiento_id}/change/')



# --- VISTA GENERAR FACTURA ---
@login_required
def generar_factura(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo'), id=orden_id)

    if request.method == 'POST':
        if not (request.user.has_perm('taller.add_factura') and \
                request.user.has_perm('taller.add_lineafactura') and \
                request.user.has_perm('taller.add_usoconsumible') and \
                request.user.has_perm('taller.delete_factura') and \
                request.user.has_perm('taller.delete_usoconsumible') and \
                request.user.has_perm('taller.change_ordendereparacion')):
            return HttpResponseForbidden("No tienes permiso para generar o reemplazar facturas.")

        es_factura = 'aplicar_iva' in request.POST
        with transaction.atomic():
            Factura.objects.filter(orden=orden).delete()
            UsoConsumible.objects.filter(orden=orden).delete()

            factura = Factura.objects.create(orden=orden, es_factura=es_factura); subtotal = Decimal('0.00')
            repuestos_qs = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
            gastos_otros_qs = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')
            for repuesto in repuestos_qs:
                pvp_str = request.POST.get(f'pvp_repuesto_{repuesto.id}')
                if pvp_str:
                    try:
                        pvp = Decimal(pvp_str); coste_repuesto = repuesto.importe or Decimal('0.00')
                        if pvp < coste_repuesto: pvp = coste_repuesto
                        subtotal += pvp
                        LineaFactura.objects.create(factura=factura, tipo='Repuesto', descripcion=repuesto.descripcion, cantidad=1, precio_unitario=pvp)
                    except (ValueError, TypeError, Decimal.InvalidOperation): pass
            for gasto_otro in gastos_otros_qs:
                pvp_str = request.POST.get(f'pvp_otro_{gasto_otro.id}')
                if pvp_str:
                    try:
                        pvp = Decimal(pvp_str); coste_gasto = gasto_otro.importe or Decimal('0.00')
                        if pvp < coste_gasto: pvp = coste_gasto
                        subtotal += pvp
                        LineaFactura.objects.create(factura=factura, tipo='Externo', descripcion=gasto_otro.descripcion, cantidad=1, precio_unitario=pvp)
                    except (ValueError, TypeError, Decimal.InvalidOperation): pass
            tipos_consumible_id = request.POST.getlist('tipo_consumible'); cantidades_consumible = request.POST.getlist('consumible_cantidad'); pvps_consumible = request.POST.getlist('consumible_pvp_total')
            for i in range(len(tipos_consumible_id)):
                if tipos_consumible_id[i] and cantidades_consumible[i] and pvps_consumible[i]:
                    try:
                        tipo = TipoConsumible.objects.get(id=tipos_consumible_id[i]); cantidad = Decimal(cantidades_consumible[i]); pvp_total = Decimal(pvps_consumible[i])
                        if cantidad <= 0 or pvp_total < 0: continue
                        precio_unitario_calculado = (pvp_total / cantidad).quantize(Decimal('0.01')); subtotal += pvp_total
                        LineaFactura.objects.create(factura=factura, tipo='Consumible', descripcion=tipo.nombre, cantidad=cantidad, precio_unitario=precio_unitario_calculado)
                        UsoConsumible.objects.create(orden=orden, tipo=tipo, cantidad_usada=cantidad)
                    except (TipoConsumible.DoesNotExist, ValueError, TypeError, Decimal.InvalidOperation, ZeroDivisionError): pass
            descripciones_mo = request.POST.getlist('mano_obra_desc'); importes_mo = request.POST.getlist('mano_obra_importe')
            for desc, importe_str in zip(descripciones_mo, importes_mo):
                if desc and importe_str:
                    try:
                        importe = Decimal(importe_str)
                        if importe <= 0: continue
                        subtotal += importe
                        LineaFactura.objects.create(factura=factura, tipo='Mano de Obra', descripcion=desc.upper(), cantidad=1, precio_unitario=importe)
                    except (ValueError, TypeError, Decimal.InvalidOperation): pass
            iva_calculado = Decimal('0.00'); subtotal_positivo = max(subtotal, Decimal('0.00'))
            if es_factura: iva_calculado = (subtotal_positivo * Decimal('0.21')).quantize(Decimal('0.01'))
            total_final = subtotal_positivo + iva_calculado
            factura.subtotal = subtotal; factura.iva = iva_calculado; factura.total_final = total_final; factura.save()
            orden.estado = 'Listo para Recoger'; orden.save()
            return redirect('detalle_orden', orden_id=orden.id)

    return redirect('detalle_orden', orden_id=orden.id)


# --- VISTA VER FACTURA PDF ---
@login_required
def ver_factura_pdf(request, factura_id):
    factura = get_object_or_404(Factura.objects.select_related('orden__cliente', 'orden__vehiculo'), id=factura_id)
    if not request.user.has_perm('taller.view_factura'):
         return HttpResponseForbidden("No tienes permiso para ver facturas.")

    cliente = factura.orden.cliente; vehiculo = factura.orden.vehiculo
    abonos = factura.orden.ingreso_set.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    pendiente = factura.total_final - abonos; lineas = factura.lineas.all()
    orden_tipos = ['Mano de Obra', 'Repuesto', 'Consumible', 'Externo']; lineas_agrupadas = {tipo: [] for tipo in orden_tipos}; otros_tipos = []
    for linea in lineas:
        if linea.tipo in lineas_agrupadas: lineas_agrupadas[linea.tipo].append(linea)
        else: otros_tipos.append(linea)
    lineas_ordenadas_agrupadas = []
    for tipo in orden_tipos: lineas_ordenadas_agrupadas.extend(lineas_agrupadas[tipo])
    lineas_ordenadas_agrupadas.extend(otros_tipos)
    context = { 'factura': factura, 'cliente': cliente, 'vehiculo': vehiculo, 'lineas': lineas_ordenadas_agrupadas, 'abonos': abonos, 'pendiente': pendiente, 'STATIC_URL': settings.STATIC_URL, 'logo_path': os.path.join(settings.BASE_DIR, 'taller', 'static', 'taller', 'images', 'logo.jpg') }
    template_path = 'taller/plantilla_factura.html'; template = get_template(template_path); html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    matricula_filename = factura.orden.vehiculo.matricula if factura.orden.vehiculo else 'SIN_MATRICULA'
    response['Content-Disposition'] = f'inline; filename="fact_{matricula_filename}_{factura.id}.pdf"'
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
        print(f"WARN: Could not resolve URI '{uri}' in PDF generation."); return None
    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err: return HttpResponse('Error al generar PDF: <pre>' + html + '</pre>')
    return response


# --- VISTA EDITAR FACTURA ---
@login_required
def editar_factura(request, factura_id):
    factura = get_object_or_404(Factura.objects.prefetch_related('lineas'), id=factura_id)
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo__cliente'), id=factura.orden_id)

    if request.method == 'POST':
        if not (request.user.has_perm('taller.delete_factura') and \
                request.user.has_perm('taller.add_factura') and \
                request.user.has_perm('taller.add_lineafactura') and \
                request.user.has_perm('taller.delete_usoconsumible') and \
                request.user.has_perm('taller.add_usoconsumible') and \
                request.user.has_perm('taller.change_ordendereparacion')):
             return HttpResponseForbidden("No tienes permiso para editar facturas.")

        with transaction.atomic():
            UsoConsumible.objects.filter(orden=orden).delete()
            factura.delete()
        # Pasar la request original a generar_factura
        # No podemos pasar request directamente porque es un WSGIRequest en editar_factura
        # y generar_factura espera un HttpRequest. Usaremos request._request si está disponible
        # o crearemos una nueva si no (menos ideal). Lo más seguro es redirigir a una URL GET
        # que llame a generar_factura, pero eso complica el flujo.
        # Por simplicidad, intentaremos llamar directamente, aunque podría fallar
        # si generar_factura depende mucho del tipo exacto de request.
        # ¡OJO! Lo ideal sería refactorizar generar_factura para que acepte datos
        # en lugar de depender directamente de request.POST
        try:
             # Pasamos el request original (HttpRequest) si está disponible
             original_request = getattr(request, '_request', request)
             return generar_factura(original_request, orden.id)
        except Exception as e:
             # Manejar posible error si generar_factura falla
             print(f"Error al llamar a generar_factura desde editar_factura: {e}")
             # Redirigir de vuelta al detalle de la orden como fallback
             return redirect('detalle_orden', orden_id=orden.id)


    # --- Lógica GET ---
    repuestos_qs = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
    gastos_otros_qs = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')
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


# --- INFORMES (Solo lectura, @login_required por consistencia) ---
@login_required
def informe_rentabilidad(request):
    # ... (Lógica existente) ...
    periodo = request.GET.get('periodo', 'mes'); hoy = timezone.now().date()
    facturas_qs = Factura.objects.select_related('orden__vehiculo').prefetch_related('lineas', 'orden__vehiculo__gasto_set')
    ingresos_grua_qs = Ingreso.objects.filter(categoria='Grua'); otras_ganancias_qs = Ingreso.objects.filter(categoria='Otras Ganancias')
    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        facturas_qs = facturas_qs.filter(fecha_emision__gte=inicio_semana); ingresos_grua_qs = ingresos_grua_qs.filter(fecha__gte=inicio_semana); otras_ganancias_qs = otras_ganancias_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        facturas_qs = facturas_qs.filter(fecha_emision__month=hoy.month, fecha_emision__year=hoy.year); ingresos_grua_qs = ingresos_grua_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year); otras_ganancias_qs = otras_ganancias_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)
    facturas = facturas_qs.order_by('-fecha_emision'); ingresos_grua = ingresos_grua_qs.order_by('-fecha'); otras_ganancias = otras_ganancias_qs.order_by('-fecha')
    ganancia_trabajos = Decimal('0.00'); reporte = []
    compras_consumibles = CompraConsumible.objects.order_by('tipo_id', '-fecha_compra'); ultimas_compras_por_tipo = {};
    for compra in compras_consumibles:
        if compra.tipo_id not in ultimas_compras_por_tipo: ultimas_compras_por_tipo[compra.tipo_id] = compra
    tipos_consumible_dict = {tipo.nombre.upper(): tipo for tipo in TipoConsumible.objects.all()}
    for factura in facturas:
        orden = factura.orden;
        if not orden or not orden.vehiculo: continue
        gastos_orden_qs = orden.vehiculo.gasto_set.filter(categoria__in=['Repuestos', 'Otros']) if hasattr(orden.vehiculo, 'gasto_set') else Gasto.objects.none()
        coste_piezas_externos_factura = gastos_orden_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        total_cobrado_piezas_externos = Decimal('0.00'); ganancia_servicios = Decimal('0.00'); coste_consumibles_factura = Decimal('0.00')
        for linea in factura.lineas.all():
            if linea.tipo in ['Repuesto', 'Externo']: total_cobrado_piezas_externos += linea.total_linea
            elif linea.tipo in ['Mano de Obra', 'Consumible']:
                coste_linea = Decimal('0.00')
                if linea.tipo == 'Consumible':
                    tipo_obj = tipos_consumible_dict.get(linea.descripcion.upper())
                    if tipo_obj and tipo_obj.id in ultimas_compras_por_tipo:
                         compra_relevante = ultimas_compras_por_tipo[tipo_obj.id]
                         if compra_relevante.fecha_compra <= factura.fecha_emision:
                             coste_linea = (compra_relevante.coste_por_unidad or Decimal('0.00')) * linea.cantidad; coste_consumibles_factura += coste_linea
                ganancia_servicios += (linea.total_linea - coste_linea)
        coste_total_directo = coste_piezas_externos_factura + coste_consumibles_factura
        base_cobrada = factura.subtotal if factura.es_factura else factura.total_final; ganancia_total_orden = base_cobrada - coste_total_directo
        ganancia_trabajos += ganancia_total_orden; reporte.append({'orden': orden, 'factura': factura, 'ganancia_total': ganancia_total_orden})
    ganancia_grua_total = ingresos_grua.aggregate(total=Sum('importe'))['total'] or Decimal('0.00'); ganancia_otras_total = otras_ganancias.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia_general = ganancia_trabajos + ganancia_grua_total + ganancia_otras_total
    ganancias_directas_desglose = sorted(list(ingresos_grua) + list(otras_ganancias), key=lambda x: x.fecha, reverse=True)
    context = { 'reporte': reporte, 'ganancia_trabajos': ganancia_trabajos, 'ganancia_grua': ganancia_grua_total, 'ganancia_otras': ganancia_otras_total, 'ganancias_directas_desglose': ganancias_directas_desglose, 'total_ganancia_general': total_ganancia_general, 'periodo_seleccionado': periodo }
    return render(request, 'taller/informe_rentabilidad.html', context)

@login_required
def detalle_ganancia_orden(request, orden_id):
    # ... (Lógica GET existente) ...
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo', 'cliente'), id=orden_id)
    try: factura = Factura.objects.prefetch_related('lineas', 'orden__ingreso_set').get(orden=orden)
    except Factura.DoesNotExist: return redirect('detalle_orden', orden_id=orden.id)
    desglose_agrupado = {}; gastos_usados_ids = set()
    gastos_asociados = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria__in=['Repuestos', 'Otros']).order_by('id')
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
    # ... (Lógica GET existente) ...
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
    # ... (Lógica GET existente) ...
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
    # ... (Lógica GET existente) ...
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
    # ... (Lógica GET existente) ...
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
    # ... (Lógica GET existente) ...
    periodo = request.GET.get('periodo', 'mes'); hoy = timezone.now().date()
    ingresos_qs = Ingreso.objects.all(); gastos_qs = Gasto.objects.all()
    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        ingresos_qs = ingresos_qs.filter(fecha__gte=inicio_semana); gastos_qs = gastos_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        ingresos_qs = ingresos_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year); gastos_qs = gastos_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)
    total_ingresado = ingresos_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00'); total_gastado = gastos_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia = total_ingresado - total_gastado
    context = { 'total_ingresado': total_ingresado, 'total_gastado': total_gastado, 'total_ganancia': total_ganancia, 'periodo_seleccionado': periodo }
    return render(request, 'taller/contabilidad.html', context)

@login_required
def cuentas_por_cobrar(request):
    # ... (Lógica GET existente) ...
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
    # ... (Lógica GET existente) ...
    periodo = request.GET.get('periodo', 'mes'); hoy = timezone.now().date()
    ingresos_tpv_qs = Ingreso.objects.filter(es_tpv=True); gastos_tarjeta_qs = Gasto.objects.filter(pagado_con_tarjeta=True)
    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        ingresos_tpv_qs = ingresos_tpv_qs.filter(fecha__gte=inicio_semana); gastos_tarjeta_qs = gastos_tarjeta_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        ingresos_tpv_qs = ingresos_tpv_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year); gastos_tarjeta_qs = gastos_tarjeta_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)
    total_ingresos_tpv = ingresos_tpv_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00'); total_gastos_tarjeta = gastos_tarjeta_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_tarjeta = total_ingresos_tpv - total_gastos_tarjeta
    movimientos_tarjeta = sorted(list(ingresos_tpv_qs) + list(gastos_tarjeta_qs), key=lambda mov: (mov.fecha, -mov.id if hasattr(mov, 'id') else 0), reverse=True)
    context = { 'total_ingresos_tpv': total_ingresos_tpv, 'total_gastos_tarjeta': total_gastos_tarjeta, 'balance_tarjeta': balance_tarjeta, 'movimientos_tarjeta': movimientos_tarjeta, 'periodo_seleccionado': periodo }
    return render(request, 'taller/informe_tarjeta.html', context)

@login_required
def ver_presupuesto_pdf(request, presupuesto_id):
    presupuesto = get_object_or_404(Presupuesto.objects.select_related('cliente', 'vehiculo').prefetch_related('lineas'), id=presupuesto_id)
    if not request.user.has_perm('taller.view_presupuesto'):
         return HttpResponseForbidden("No tienes permiso para ver presupuestos.")

    lineas = presupuesto.lineas.all()
    context = { 'presupuesto': presupuesto, 'lineas': lineas, 'STATIC_URL': settings.STATIC_URL, 'logo_path': os.path.join(settings.BASE_DIR, 'taller', 'static', 'taller', 'images', 'logo.jpg') }
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
        print(f"WARN: Could not resolve URI '{uri}' in PDF generation."); return None
    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err: return HttpResponse('Error al generar PDF: <pre>' + html + '</pre>')
    return response