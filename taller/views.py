# taller/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import Ingreso, Gasto, Cliente, Vehiculo, OrdenDeReparacion, Empleado, TipoConsumible, CompraConsumible, Factura, LineaFactura, FotoVehiculo
from django.db.models import Sum, F
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
import os
from django.conf import settings

# --- FUNCIÓN AUXILIAR PARA LOS FILTROS DE FECHA ---
def get_anos_y_meses_con_datos():
    fechas_gastos = Gasto.objects.values_list('fecha', flat=True)
    fechas_ingresos = Ingreso.objects.values_list('fecha', flat=True)
    fechas_facturas = Factura.objects.values_list('fecha_emision', flat=True)

    fechas = sorted(list(set(fechas_gastos) | set(fechas_ingresos) | set(fechas_facturas)), reverse=True)

    anos_y_meses = {}
    for fecha in fechas:
        ano = fecha.year
        mes = fecha.month
        if ano not in anos_y_meses:
            anos_y_meses[ano] = []
        if mes not in anos_y_meses[ano]:
            anos_y_meses[ano].append(mes)

    return anos_y_meses

# taller/views.py
# ... (importaciones y otras funciones) ...

def home(request):
    hoy = datetime.now()
    mes_actual = hoy.month
    ano_actual = hoy.year

    # Filtrar ingresos y gastos del mes actual
    ingresos_mes = Ingreso.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    gastos_mes = Gasto.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)

    # Calcular totales generales (pueden seguir siendo útiles)
    total_ingresos = ingresos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos = gastos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

    # --- Calcular Balance de Caja (Efectivo) ---
    ingresos_efectivo = ingresos_mes.filter(es_tpv=False).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gastos_efectivo = gastos_mes.filter(pagado_con_tarjeta=False).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_caja = ingresos_efectivo - gastos_efectivo

    # --- Calcular Balance de Tarjeta ---
    ingresos_tpv = ingresos_mes.filter(es_tpv=True).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gastos_tarjeta = gastos_mes.filter(pagado_con_tarjeta=True).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_tarjeta = ingresos_tpv - gastos_tarjeta

    # --- Movimientos recientes (sin cambios) ---
    ultimos_gastos = Gasto.objects.order_by('-id')[:5]
    ultimos_ingresos = Ingreso.objects.order_by('-id')[:5]
    # Aseguramos que solo tomamos 5 en total, priorizando los más recientes
    movimientos_combinados = sorted(list(ultimos_gastos) + list(ultimos_ingresos), key=lambda mov: mov.fecha if hasattr(mov, 'fecha') else datetime.min.date(), reverse=True)
    # Si quieres que la ID sea el criterio principal de ordenación reciente, usa:
    # movimientos_combinados = sorted(list(ultimos_gastos) + list(ultimos_ingresos), key=lambda mov: mov.id, reverse=True)
    movimientos_recientes = movimientos_combinados[:5]


    context = {
        'total_ingresos': total_ingresos, # Total general del mes
        'total_gastos': total_gastos,     # Total general del mes
        'balance_caja': balance_caja,       # Nuevo balance de caja
        'balance_tarjeta': balance_tarjeta, # Nuevo balance de tarjeta
        'movimientos_recientes': movimientos_recientes,
    }
    return render(request, 'taller/home.html', context)

# ... (resto de las vistas) ...

def ingresar_vehiculo(request):
    if request.method == 'POST':
        nombre_cliente = request.POST['cliente_nombre'].upper()
        telefono_cliente = request.POST['cliente_telefono']
        matricula_vehiculo = request.POST['vehiculo_matricula'].upper()
        marca_vehiculo = request.POST['vehiculo_marca'].upper()
        modelo_vehiculo = request.POST['vehiculo_modelo'].upper()
        kilometraje_vehiculo = request.POST.get('vehiculo_kilometraje', 0)
        problema_reportado = request.POST['problema'].upper()

        cliente, created = Cliente.objects.get_or_create(
            telefono=telefono_cliente,
            defaults={'nombre': nombre_cliente}
        )

        vehiculo, created = Vehiculo.objects.get_or_create(
            matricula=matricula_vehiculo,
            defaults={
                'marca': marca_vehiculo,
                'modelo': modelo_vehiculo,
                'kilometraje': kilometraje_vehiculo,
                'cliente': cliente
            }
        )
        if not created and kilometraje_vehiculo and int(kilometraje_vehiculo) > vehiculo.kilometraje:
            vehiculo.kilometraje = kilometraje_vehiculo
            vehiculo.save()

        nueva_orden = OrdenDeReparacion.objects.create(
            cliente=cliente,
            vehiculo=vehiculo,
            problema=problema_reportado
        )

        descripciones = ['Frontal', 'Trasera', 'Lateral Izquierdo', 'Lateral Derecho', 'Cuadro/Km']
        for i in range(1, 6):
            foto_campo = f'foto{i}'
            if foto_campo in request.FILES:
                FotoVehiculo.objects.create(
                    orden=nueva_orden,
                    imagen=request.FILES[foto_campo],
                    descripcion=descripciones[i-1]
                )

        return redirect('home')

    return render(request, 'taller/ingresar_vehiculo.html')

def anadir_gasto(request):
    if request.method == 'POST':
        categoria = request.POST['categoria']
        # --- NUEVA LÍNEA ---
        pagado_con_tarjeta = request.POST.get('pagado_con_tarjeta') == 'true'
        # --------------------

        if categoria == 'Compra de Consumibles':
            tipo_id = request.POST['tipo_consumible']
            fecha_compra = request.POST['fecha_compra']
            cantidad = Decimal(request.POST['cantidad'])
            coste_total = Decimal(request.POST['coste_total'])
            tipo_consumible = TipoConsumible.objects.get(id=tipo_id)
            CompraConsumible.objects.create(
                tipo=tipo_consumible,
                fecha_compra=fecha_compra,
                cantidad=cantidad,
                coste_total=coste_total
            )
            # Al crear el gasto asociado a la compra, también marcamos si se pagó con tarjeta
            Gasto.objects.create(
                categoria=categoria,
                importe=coste_total,
                descripcion=f"Compra de {cantidad} {tipo_consumible.unidad_medida} de {tipo_consumible.nombre}",
                pagado_con_tarjeta=pagado_con_tarjeta # <- Añadir aquí también
            )
        else:
            importe = request.POST['importe']
            descripcion = request.POST['descripcion']
            # --- MODIFICADO: Añadir pagado_con_tarjeta al crear ---
            gasto = Gasto(
                categoria=categoria,
                importe=importe,
                descripcion=descripcion,
                pagado_con_tarjeta=pagado_con_tarjeta # <- Añadir aquí
            )
            # ----------------------------------------------------
            if categoria in ['Repuestos', 'Otros']:
                vehiculo_id = request.POST.get('vehiculo')
                if vehiculo_id:
                    gasto.vehiculo = Vehiculo.objects.get(id=vehiculo_id)
            if categoria == 'Sueldos':
                empleado_id = request.POST.get('empleado')
                if empleado_id:
                    gasto.empleado = Empleado.objects.get(id=empleado_id)
            gasto.save()
            if gasto.vehiculo and categoria in ['Repuestos', 'Otros']:
                try:
                    orden_a_actualizar = OrdenDeReparacion.objects.filter(
                        vehiculo=gasto.vehiculo,
                        estado__in=['Recibido', 'En Diagnostico']
                    ).latest('fecha_entrada')
                    orden_a_actualizar.estado = 'En Reparacion'
                    orden_a_actualizar.save()
                except OrdenDeReparacion.DoesNotExist:
                    pass
        return redirect('home')
    context = {
        'vehiculos': Vehiculo.objects.all(),
        'empleados': Empleado.objects.all(),
        'tipos_consumible': TipoConsumible.objects.all(),
        'categorias_gasto': Gasto.CATEGORIA_CHOICES,
    }
    return render(request, 'taller/anadir_gasto.html', context)

def registrar_ingreso(request):
    if request.method == 'POST':
        categoria = request.POST['categoria']
        importe = request.POST['importe']
        descripcion = request.POST['descripcion']
        # --- AÑADIR ESTA LÍNEA ---
        es_tpv = request.POST.get('es_tpv') == 'true'
        # -------------------------
        # --- MODIFICADO: Añadir es_tpv al crear ---
        ingreso = Ingreso(
            categoria=categoria,
            importe=importe,
            descripcion=descripcion,
            es_tpv=es_tpv # <- Añadir aquí
        )
        # -----------------------------------------
        if categoria == 'Taller':
            orden_id = request.POST.get('orden')
            if orden_id:
                ingreso.orden = OrdenDeReparacion.objects.get(id=orden_id)
        ingreso.save()
        return redirect('home')
    ordenes = OrdenDeReparacion.objects.all()
    context = {
        'ordenes': ordenes,
        'categorias_ingreso': Ingreso.CATEGORIA_CHOICES,
    }
    return render(request, 'taller/registrar_ingreso.html', context)

def stock_inicial_consumible(request):
    if request.method == 'POST':
        tipo_id = request.POST['tipo_consumible']
        cantidad = Decimal(request.POST['cantidad'])
        coste_total = Decimal(request.POST['coste_total'])
        fecha_compra = datetime.now().date()
        tipo_consumible = TipoConsumible.objects.get(id=tipo_id)
        CompraConsumible.objects.create(
            tipo=tipo_consumible,
            fecha_compra=fecha_compra,
            cantidad=cantidad,
            coste_total=coste_total
        )
        # Opcional: Podrías añadir un gasto asociado aquí si consideras el stock inicial como gasto,
        # pero normalmente no se hace. Si lo hicieras, recuerda añadir pagado_con_tarjeta=False por defecto.
        # Gasto.objects.create(categoria='Compra de Consumibles', importe=coste_total, descripcion=f"STOCK INICIAL: {cantidad} {tipo_consumible.unidad_medida} de {tipo_consumible.nombre}", pagado_con_tarjeta=False)
        return redirect('home')
    context = {
        'tipos_consumible': TipoConsumible.objects.all()
    }
    return render(request, 'taller/stock_inicial_consumible.html', context)


# --- El resto de las funciones (lista_ordenes, detalle_orden, etc.) permanecen igual ---
# --- No es necesario copiar y pegar todo si solo has modificado anadir_gasto y registrar_ingreso ---

def lista_ordenes(request):
    ordenes_activas = OrdenDeReparacion.objects.exclude(estado='Entregado').order_by('-fecha_entrada')
    context = {
        'ordenes': ordenes_activas,
    }
    return render(request, 'taller/lista_ordenes.html', context)

def detalle_orden(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion, id=orden_id)
    repuestos = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
    gastos_otros = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')
    abonos = Ingreso.objects.filter(orden=orden).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    tipos_consumible = TipoConsumible.objects.all()
    factura = None
    pendiente_pago = Decimal('0.00')
    try:
        factura = Factura.objects.get(orden=orden)
        pendiente_pago = factura.total_final - abonos
    except Factura.DoesNotExist:
        pass
    if request.method == 'POST' and 'nuevo_estado' in request.POST:
        nuevo_estado = request.POST['nuevo_estado']
        orden.estado = nuevo_estado
        orden.save()
        return redirect('detalle_orden', orden_id=orden.id)
    context = {
        'orden': orden,
        'repuestos': repuestos,
        'gastos_otros': gastos_otros,
        'factura': factura,
        'abonos': abonos,
        'pendiente_pago': pendiente_pago,
        'tipos_consumible': tipos_consumible,
    }
    return render(request, 'taller/detalle_orden.html', context)

def historial_ordenes(request):
    ordenes = OrdenDeReparacion.objects.filter(estado='Entregado').order_by('-fecha_entrada')
    anos_y_meses = get_anos_y_meses_con_datos()
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado and mes_seleccionado:
        ordenes = ordenes.filter(factura__fecha_emision__year=ano_seleccionado, factura__fecha_emision__month=mes_seleccionado)
    context = {
        'ordenes': ordenes,
        'anos_y_meses': anos_y_meses,
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado else None,
        'mes_seleccionado': int(mes_seleccionado) if mes_seleccionado else None,
    }
    return render(request, 'taller/historial_ordenes.html', context)

def historial_movimientos(request):
    periodo = request.GET.get('periodo', 'semana')
    hoy = datetime.now().date()

    gastos = Gasto.objects.all()
    ingresos = Ingreso.objects.all()

    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        gastos = gastos.filter(fecha__gte=inicio_semana)
        ingresos = ingresos.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        gastos = gastos.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        ingresos = ingresos.filter(fecha__month=hoy.month, fecha__year=hoy.year)

    movimientos = sorted(list(gastos) + list(ingresos), key=lambda mov: mov.id, reverse=True)

    context = {
        'movimientos': movimientos,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/historial_movimientos.html', context)

def editar_movimiento(request, tipo, movimiento_id):
    if tipo == 'gasto':
        return redirect(f'/admin/taller/gasto/{movimiento_id}/change/')
    elif tipo == 'ingreso':
        return redirect(f'/admin/taller/ingreso/{movimiento_id}/change/')

def generar_factura(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion, id=orden_id)
    if request.method == 'POST':
        es_factura = 'aplicar_iva' in request.POST
        Factura.objects.filter(orden=orden).delete()
        factura = Factura.objects.create(orden=orden, es_factura=es_factura)

        subtotal = Decimal('0.00')
        repuestos = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
        for repuesto in repuestos:
            pvp_str = request.POST.get(f'pvp_repuesto_{repuesto.id}')
            if pvp_str:
                pvp = Decimal(pvp_str)
                subtotal += pvp
                LineaFactura.objects.create(factura=factura, tipo='Repuesto', descripcion=repuesto.descripcion, cantidad=1, precio_unitario=pvp)

        gastos_otros = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')
        for gasto in gastos_otros:
            pvp_str = request.POST.get(f'pvp_otro_{gasto.id}')
            if pvp_str:
                pvp = Decimal(pvp_str)
                subtotal += pvp
                LineaFactura.objects.create(factura=factura, tipo='Externo', descripcion=gasto.descripcion, cantidad=1, precio_unitario=pvp)

        tipos_consumible = request.POST.getlist('tipo_consumible')
        cantidades_consumible = request.POST.getlist('consumible_cantidad')
        pvps_consumible = request.POST.getlist('consumible_pvp_total')

        for i in range(len(tipos_consumible)):
            if tipos_consumible[i] and cantidades_consumible[i] and pvps_consumible[i]:
                tipo = TipoConsumible.objects.get(id=tipos_consumible[i])
                cantidad = Decimal(cantidades_consumible[i])
                pvp_total = Decimal(pvps_consumible[i])
                subtotal += pvp_total
                LineaFactura.objects.create(factura=factura, tipo='Consumible', descripcion=f'{tipo.nombre}', cantidad=cantidad, precio_unitario=pvp_total/cantidad if cantidad > 0 else 0)

        descripciones = request.POST.getlist('mano_obra_desc')
        importes = request.POST.getlist('mano_obra_importe')
        for desc, importe_str in zip(descripciones, importes):
            if desc and importe_str:
                importe = Decimal(importe_str)
                subtotal += importe
                LineaFactura.objects.create(factura=factura, tipo='Mano de Obra', descripcion=f"Mano de Obra: {desc}", cantidad=1, precio_unitario=importe)

        iva_calculado = Decimal('0.00')
        if es_factura:
            iva_calculado = subtotal * Decimal('0.21')

        total_final = subtotal + iva_calculado
        factura.subtotal = subtotal
        factura.iva = iva_calculado
        factura.total_final = total_final
        factura.save()
        orden.estado = 'Listo para Recoger'
        orden.save()
        return redirect('detalle_orden', orden_id=orden.id)
    return redirect('detalle_orden', orden_id=orden.id)


def ver_factura_pdf(request, factura_id):
    factura = get_object_or_404(Factura, id=factura_id)
    cliente = factura.orden.cliente
    vehiculo = factura.orden.vehiculo
    abonos = Ingreso.objects.filter(orden=factura.orden).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    pendiente = factura.total_final - abonos
    lineas = factura.lineas.all()
    orden_tipos = ['Repuesto', 'Consumible', 'Externo', 'Mano de Obra']
    lineas_ordenadas = sorted(lineas, key=lambda x: orden_tipos.index(x.tipo))
    context = {
        'factura': factura,
        'cliente': cliente,
        'vehiculo': vehiculo,
        'lineas': lineas_ordenadas,
        'abonos': abonos,
        'pendiente': pendiente,
    }
    template_path = 'taller/plantilla_factura.html'
    template = get_template(template_path)
    html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="factura_{factura.id}.pdf"'
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
       return HttpResponse('Hubo un error al generar el PDF.')
    return response

def editar_factura(request, factura_id):
    factura = get_object_or_404(Factura, id=factura_id)
    orden = factura.orden
    if request.method == 'POST':
        orden_id = factura.orden.id
        factura.delete()
        return generar_factura(request, orden_id)
    repuestos = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
    gastos_otros = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')
    tipos_consumible = TipoConsumible.objects.all()
    context = {
        'orden': orden,
        'factura_existente': factura,
        'repuestos': repuestos,
        'gastos_otros': gastos_otros,
        'tipos_consumible': tipos_consumible,
    }
    return render(request, 'taller/editar_factura.html', context)

def informe_rentabilidad(request):
    periodo = request.GET.get('periodo', 'mes')
    hoy = datetime.now().date()

    facturas = Factura.objects.all().order_by('-fecha_emision')
    ingresos_grua = Ingreso.objects.filter(categoria='Grua').order_by('-fecha')
    otras_ganancias = Ingreso.objects.filter(categoria='Otras Ganancias').order_by('-fecha')

    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        facturas = facturas.filter(fecha_emision__gte=inicio_semana)
        ingresos_grua = ingresos_grua.filter(fecha__gte=inicio_semana)
        otras_ganancias = otras_ganancias.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        facturas = facturas.filter(fecha_emision__month=hoy.month, fecha_emision__year=hoy.year)
        ingresos_grua = ingresos_grua.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        otras_ganancias = otras_ganancias.filter(fecha__month=hoy.month, fecha__year=hoy.year)

    ganancia_trabajos = Decimal('0.00')
    reporte = []
    for factura in facturas:
        orden = factura.orden
        coste_total_piezas = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria__in=['Repuestos', 'Otros']).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

        total_cobrado_piezas = Decimal('0.00')
        for linea in factura.lineas.filter(tipo__in=['Repuesto', 'Externo']):
            total_cobrado_piezas += linea.total_linea

        ganancia_piezas = total_cobrado_piezas - coste_total_piezas

        ganancia_servicios = Decimal('0.00')
        for linea in factura.lineas.filter(tipo__in=['Mano de Obra', 'Consumible']):
            coste_linea = Decimal('0.00')
            if linea.tipo == 'Consumible':
                try:
                    # Ajuste para buscar por nombre exacto (asumiendo que la descripción es el nombre)
                    tipo_consumible = TipoConsumible.objects.get(nombre__iexact=linea.descripcion) # Usar iexact para ignorar mayúsculas/minúsculas
                    # Asegurarse de que la compra sea anterior o igual a la fecha de la factura
                    ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                    coste_linea = (ultima_compra.coste_por_unidad or Decimal('0.00')) * linea.cantidad # Añadir or Decimal para evitar errores si es None
                except (TipoConsumible.DoesNotExist, CompraConsumible.DoesNotExist): pass # Ignorar si no se encuentra
            ganancia_servicios += (linea.total_linea - coste_linea)

        ganancia_total_orden = ganancia_piezas + ganancia_servicios
        ganancia_trabajos += ganancia_total_orden
        reporte.append({'orden': orden, 'factura': factura, 'ganancia_total': ganancia_total_orden})

    ganancia_grua = ingresos_grua.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    ganancia_otras = otras_ganancias.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia_general = ganancia_trabajos + ganancia_grua + ganancia_otras

    ganancias_directas_desglose = sorted(
        list(ingresos_grua) + list(otras_ganancias),
        key=lambda x: x.fecha,
        reverse=True
    )

    context = {
        'reporte': reporte,
        'ganancia_trabajos': ganancia_trabajos,
        'ganancia_grua': ganancia_grua,
        'ganancia_otras': ganancia_otras,
        'ganancias_directas_desglose': ganancias_directas_desglose,
        'total_ganancia_general': total_ganancia_general,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/informe_rentabilidad.html', context)

def detalle_ganancia_orden(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion, id=orden_id)
    factura = orden.factura # Asume que siempre hay factura si llegas aquí
    desglose = []
    ganancia_total = Decimal('0.00')

    # Piezas y Trabajos Externos
    gastos_asociados = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria__in=['Repuestos', 'Otros'])
    lineas_piezas = factura.lineas.filter(tipo__in=['Repuesto', 'Externo'])

    for gasto in gastos_asociados:
        pvp = Decimal('0.00')
        # Intentar encontrar la línea de factura correspondiente al gasto
        linea_encontrada = None
        for linea in lineas_piezas:
             # Comparación más flexible (ignorando mayúsculas/minúsculas y espacios)
            if gasto.descripcion.strip().upper() == linea.descripcion.strip().upper():
                linea_encontrada = linea
                break # Salir del bucle una vez encontrada

        if linea_encontrada:
            pvp = linea_encontrada.total_linea # Usar total_linea por si la cantidad no es 1
        coste = gasto.importe or Decimal('0.00') # Asegurar que coste no sea None
        ganancia = pvp - coste
        desglose.append({
            'descripcion': f"{gasto.get_categoria_display()}: {gasto.descripcion}",
            'coste': coste,
            'pvp': pvp,
            'ganancia': ganancia
        })
        ganancia_total += ganancia

    # Mano de Obra y Consumibles
    lineas_servicios = factura.lineas.filter(tipo__in=['Mano de Obra', 'Consumible'])
    for linea in lineas_servicios:
        pvp = linea.total_linea
        coste = Decimal('0.00')
        if linea.tipo == 'Consumible':
            try:
                 # Ajuste para buscar por nombre exacto (asumiendo que la descripción es el nombre)
                tipo_consumible = TipoConsumible.objects.get(nombre__iexact=linea.descripcion) # Usar iexact
                # Asegurarse de que la compra sea anterior o igual a la fecha de la factura
                ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                coste = (ultima_compra.coste_por_unidad or Decimal('0.00')) * linea.cantidad # Asegurar que coste_por_unidad no sea None
            except (TipoConsumible.DoesNotExist, CompraConsumible.DoesNotExist):
                coste = Decimal('0.00') # Si no hay compra registrada, el coste es 0
        ganancia = pvp - coste
        desglose.append({
            'descripcion': linea.descripcion,
            'coste': coste,
            'pvp': pvp,
            'ganancia': ganancia
        })
        ganancia_total += ganancia

    context = {
        'orden': orden,
        'desglose': desglose,
        'ganancia_total': ganancia_total,
    }
    return render(request, 'taller/detalle_ganancia_orden.html', context)


def informe_gastos(request):
    gastos = Gasto.objects.all()
    # Obtener años con datos de gastos O ingresos para filtros más completos
    anos_disponibles_g = Gasto.objects.dates('fecha', 'year', order='DESC').distinct()
    anos_disponibles_i = Ingreso.objects.dates('fecha', 'year', order='DESC').distinct()
    anos_disponibles = sorted(list(set([d.year for d in anos_disponibles_g] + [d.year for d in anos_disponibles_i])), reverse=True)


    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    if ano_seleccionado:
        gastos = gastos.filter(fecha__year=ano_seleccionado)
    if mes_seleccionado:
        gastos = gastos.filter(fecha__month=mes_seleccionado)

    # 1. Calcular totales por categoría
    totales_por_categoria_query = gastos.values('categoria').annotate(total=Sum('importe')).order_by('categoria')

    categoria_display_map = dict(Gasto.CATEGORIA_CHOICES)
    resumen_categorias = {
        item['categoria']: {
            'display_name': categoria_display_map.get(item['categoria'], item['categoria']),
            'total': item['total'] or Decimal('0.00')
        }
        for item in totales_por_categoria_query
    }

    # 2. Calcular desglose de sueldos
    sueldos = gastos.filter(categoria='Sueldos', empleado__isnull=False)
    desglose_sueldos_query = sueldos.values('empleado__nombre').annotate(total=Sum('importe')).order_by('empleado__nombre')

    desglose_sueldos = {
        item['empleado__nombre']: item['total'] or Decimal('0.00')
        for item in desglose_sueldos_query
    }

    context = {
        'totales_por_categoria': resumen_categorias,
        'desglose_sueldos': desglose_sueldos,
        'anos_disponibles': anos_disponibles, # Usar la lista combinada
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado else None,
        'mes_seleccionado': int(mes_seleccionado) if mes_seleccionado else None,
    }
    return render(request, 'taller/informe_gastos.html', context)

def informe_gastos_desglose(request, categoria, empleado_nombre=None):
    gastos = Gasto.objects.all()

    categoria_map = dict(Gasto.CATEGORIA_CHOICES)
    titulo = f"Desglose de Gastos: {categoria_map.get(categoria.replace('_', ' ').title(), categoria.replace('_', ' ').title())}" # Usar mapa para nombre correcto

    if empleado_nombre:
        # Asegurarse de que el nombre coincida exactamente (puede necesitar ajustes si hay variaciones)
        gastos = gastos.filter(categoria='Sueldos', empleado__nombre__iexact=empleado_nombre.replace('_', ' ')) # Usar iexact y reemplazar guiones bajos
        titulo = f"Desglose de Sueldos: {empleado_nombre.replace('_', ' ').upper()}"
    else:
        # Usar la clave interna correcta para filtrar
        gastos = gastos.filter(categoria__iexact=categoria.replace('_', ' ')) # Usar iexact y reemplazar

    # Mantener los filtros de fecha si existen
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado:
        gastos = gastos.filter(fecha__year=ano_seleccionado)
    if mes_seleccionado:
        gastos = gastos.filter(fecha__month=mes_seleccionado)

    total_desglose = gastos.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

    context = {
        'titulo': titulo,
        'gastos_desglose': gastos.order_by('-fecha'),
        'total_desglose': total_desglose,
        'ano_seleccionado': ano_seleccionado,
        'mes_seleccionado': mes_seleccionado,
    }
    return render(request, 'taller/informe_gastos_desglose.html', context)


def informe_ingresos(request):
    ingresos = Ingreso.objects.all()
    # Obtener años con datos de gastos O ingresos para filtros más completos
    anos_disponibles_g = Gasto.objects.dates('fecha', 'year', order='DESC').distinct()
    anos_disponibles_i = Ingreso.objects.dates('fecha', 'year', order='DESC').distinct()
    anos_disponibles = sorted(list(set([d.year for d in anos_disponibles_g] + [d.year for d in anos_disponibles_i])), reverse=True)


    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    if ano_seleccionado:
        ingresos = ingresos.filter(fecha__year=ano_seleccionado)
    if mes_seleccionado:
        ingresos = ingresos.filter(fecha__month=mes_seleccionado)

    # Calcular totales por categoría
    totales_por_categoria_query = ingresos.values('categoria').annotate(total=Sum('importe')).order_by('categoria')

    categoria_display_map = dict(Ingreso.CATEGORIA_CHOICES)
    resumen_categorias = {
        item['categoria']: {
            'display_name': categoria_display_map.get(item['categoria'], item['categoria']),
            'total': item['total'] or Decimal('0.00')
        }
        for item in totales_por_categoria_query
    }

    context = {
        'totales_por_categoria': resumen_categorias,
        'anos_disponibles': anos_disponibles, # Usar la lista combinada
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado else None,
        'mes_seleccionado': int(mes_seleccionado) if mes_seleccionado else None,
    }
    return render(request, 'taller/informe_ingresos.html', context)

def informe_ingresos_desglose(request, categoria):
    ingresos = Ingreso.objects.all()

    categoria_display_map = dict(Ingreso.CATEGORIA_CHOICES)
    # Asegurarse de usar la clave interna correcta o el nombre legible si es necesario
    categoria_filtrar = categoria # Asumimos que la URL pasa la clave interna
    titulo = f"Desglose de Ingresos: {categoria_display_map.get(categoria_filtrar, categoria_filtrar)}"


    ingresos = ingresos.filter(categoria__iexact=categoria_filtrar) # Usar iexact por si acaso

    # Mantener los filtros de fecha si existen
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado:
        ingresos = ingresos.filter(fecha__year=ano_seleccionado)
    if mes_seleccionado:
        ingresos = ingresos.filter(fecha__month=mes_seleccionado)

    total_desglose = ingresos.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

    context = {
        'titulo': titulo,
        'ingresos_desglose': ingresos.order_by('-fecha'),
        'total_desglose': total_desglose,
        'ano_seleccionado': ano_seleccionado,
        'mes_seleccionado': mes_seleccionado,
    }
    return render(request, 'taller/informe_ingresos_desglose.html', context)


def contabilidad(request):
    periodo = request.GET.get('periodo', 'mes')
    hoy = datetime.now().date()
    ingresos = Ingreso.objects.all()
    gastos = Gasto.objects.all()
    facturas = Factura.objects.all()
    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        ingresos = ingresos.filter(fecha__gte=inicio_semana)
        gastos = gastos.filter(fecha__gte=inicio_semana)
        facturas = facturas.filter(fecha_emision__gte=inicio_semana)
    elif periodo == 'mes':
        ingresos = ingresos.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        gastos = gastos.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        facturas = facturas.filter(fecha_emision__month=hoy.month, fecha_emision__year=hoy.year)

    total_ingresado = ingresos.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastado = gastos.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

    # --- Cálculo de Ganancia (Beneficio Bruto) ---
    total_ganancia = Decimal('0.00')

    # 1. Ganancias directas (Grúa, Otras Ganancias)
    ganancia_directa = ingresos.filter(categoria__in=['Grua', 'Otras Ganancias']).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia += ganancia_directa

    # 2. Ganancias de trabajos facturados (Taller)
    for factura in facturas:
        # Coste total de piezas y trabajos externos asociados a la orden de esa factura
        coste_piezas_externos = Gasto.objects.filter(vehiculo=factura.orden.vehiculo, categoria__in=['Repuestos', 'Otros']).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')

        # Coste de consumibles usados en esa factura (calculado a partir de las líneas)
        coste_consumibles = Decimal('0.00')
        for linea in factura.lineas.filter(tipo='Consumible'):
            try:
                tipo_consumible = TipoConsumible.objects.get(nombre__iexact=linea.descripcion)
                ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                coste_consumibles += (ultima_compra.coste_por_unidad or Decimal('0.00')) * linea.cantidad
            except (TipoConsumible.DoesNotExist, CompraConsumible.DoesNotExist):
                pass # Coste 0 si no hay registro

        # Ganancia de la factura = Total Cobrado (sin IVA si no es factura) - Costes asociados
        total_cobrado_trabajo = factura.subtotal if factura.es_factura else factura.total_final # Usamos subtotal si hay IVA, si no, el total
        ganancia_factura = total_cobrado_trabajo - coste_piezas_externos - coste_consumibles
        total_ganancia += ganancia_factura

    # Restar gastos generales que NO están directamente asociados a una factura/orden
    # (Sueldos, Herramientas, Suministros, y "Otros" sin vehículo asociado)
    gastos_generales = gastos.exclude(categoria__in=['Repuestos', 'Compra de Consumibles']).exclude(categoria='Otros', vehiculo__isnull=False)
    # gastos_generales = gastos.filter(
    #    Q(categoria__in=['Sueldos', 'Herramientas', 'Suministros']) |
    #    Q(categoria='Otros', vehiculo__isnull=True)
    # ).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    # total_ganancia -= gastos_generales # Restamos estos gastos al beneficio bruto


    context = {
        'total_ingresado': total_ingresado,
        'total_gastado': total_gastado,
        # 'gastos_generales': gastos_generales, # Opcional: mostrar gastos generales
        'total_ganancia': total_ganancia, # Esto ahora es Beneficio Bruto
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/contabilidad.html', context)


def cuentas_por_cobrar(request):
    # Usar la función auxiliar para obtener años/meses con datos relevantes
    anos_y_meses = get_anos_y_meses_con_datos()

    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    # Filtrar facturas basado en año/mes si están seleccionados
    facturas = Factura.objects.all()
    if ano_seleccionado:
        facturas = facturas.filter(fecha_emision__year=ano_seleccionado)
    if mes_seleccionado:
        facturas = facturas.filter(fecha_emision__month=mes_seleccionado)

    facturas_pendientes = []
    total_pendiente = Decimal('0.00')

    for factura in facturas.order_by('fecha_emision'): # Ordenar por fecha
        abonos = Ingreso.objects.filter(orden=factura.orden).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        pendiente = factura.total_final - abonos
        # Considerar un pequeño margen de error para céntimos
        if pendiente > Decimal('0.01'):
            facturas_pendientes.append({
                'factura': factura,
                'orden': factura.orden,
                'cliente': factura.orden.cliente,
                'vehiculo': factura.orden.vehiculo,
                'pendiente': pendiente,
            })
            total_pendiente += pendiente

    context = {
        'facturas_pendientes': facturas_pendientes,
        'total_pendiente': total_pendiente,
        'anos_y_meses': anos_y_meses, # Pasar al contexto
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado else None,
        'mes_seleccionado': int(mes_seleccionado) if mes_seleccionado else None,
    }
    return render(request, 'taller/cuentas_por_cobrar.html', context)
# taller/views.py
# ... (importaciones existentes al principio del archivo) ...
from django.db.models import Q # Asegúrate de importar Q

# ... (resto de tus vistas: home, ingresar_vehiculo, ..., cuentas_por_cobrar) ...

# --- NUEVA VISTA PARA INFORME DE TARJETA ---
def informe_tarjeta(request):
    # Obtener filtros de periodo (igual que en otros informes)
    periodo = request.GET.get('periodo', 'mes') # Por defecto muestra el mes actual
    hoy = datetime.now().date()

    # Filtrar ingresos por TPV
    ingresos_tpv = Ingreso.objects.filter(es_tpv=True)
    # Filtrar gastos pagados con tarjeta
    gastos_tarjeta = Gasto.objects.filter(pagado_con_tarjeta=True)

    # Aplicar filtro de periodo
    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        ingresos_tpv = ingresos_tpv.filter(fecha__gte=inicio_semana)
        gastos_tarjeta = gastos_tarjeta.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        ingresos_tpv = ingresos_tpv.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        gastos_tarjeta = gastos_tarjeta.filter(fecha__month=hoy.month, fecha__year=hoy.year)
    # Si periodo es 'todo', no se aplica filtro de fecha adicional

    # Calcular totales
    total_ingresos_tpv = ingresos_tpv.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos_tarjeta = gastos_tarjeta.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_tarjeta = total_ingresos_tpv - total_gastos_tarjeta

    # Combinar y ordenar movimientos para la tabla
    movimientos_tarjeta = sorted(
        list(ingresos_tpv) + list(gastos_tarjeta),
        key=lambda mov: mov.fecha, # Ordenar por fecha
        reverse=True # Más recientes primero
    )

    context = {
        'total_ingresos_tpv': total_ingresos_tpv,
        'total_gastos_tarjeta': total_gastos_tarjeta,
        'balance_tarjeta': balance_tarjeta,
        'movimientos_tarjeta': movimientos_tarjeta,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/informe_tarjeta.html', context)