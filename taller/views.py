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

def home(request):
    hoy = datetime.now()
    mes_actual = hoy.month
    ano_actual = hoy.year
    total_ingresos = Ingreso.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos = Gasto.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    beneficio = total_ingresos - total_gastos
    ultimos_gastos = Gasto.objects.order_by('-id')[:5]
    ultimos_ingresos = Ingreso.objects.order_by('-id')[:5]
    movimientos = sorted(list(ultimos_gastos) + list(ultimos_ingresos), key=lambda mov: mov.id, reverse=True)
    context = {
        'total_ingresos': total_ingresos,
        'total_gastos': total_gastos,
        'beneficio': beneficio,
        'movimientos_recientes': movimientos,
    }
    return render(request, 'taller/home.html', context)

def ingresar_vehiculo(request):
    if request.method == 'POST':
        nombre_cliente = request.POST['cliente_nombre']
        telefono_cliente = request.POST['cliente_telefono']
        matricula_vehiculo = request.POST['vehiculo_matricula'].upper()
        marca_vehiculo = request.POST['vehiculo_marca']
        modelo_vehiculo = request.POST['vehiculo_modelo']
        kilometraje_vehiculo = request.POST.get('vehiculo_kilometraje', 0)
        problema_reportado = request.POST['problema']

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
            Gasto.objects.create(
                categoria=categoria,
                importe=coste_total,
                descripcion=f"Compra de {cantidad} {tipo_consumible.unidad_medida} de {tipo_consumible.nombre}"
            )
        else:
            importe = request.POST['importe']
            descripcion = request.POST['descripcion']
            gasto = Gasto(categoria=categoria, importe=importe, descripcion=descripcion)
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
        ingreso = Ingreso(categoria=categoria, importe=importe, descripcion=descripcion)
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
        return redirect('home')
    context = {
        'tipos_consumible': TipoConsumible.objects.all()
    }
    return render(request, 'taller/stock_inicial_consumible.html', context)

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
    movimientos_brutos = sorted(list(gastos) + list(ingresos), key=lambda mov: mov.id, reverse=True)
    movimientos_agrupados = []
    if periodo == 'todo':
        movimientos_ordenados_fecha = sorted(movimientos_brutos, key=lambda mov: mov.fecha, reverse=True)
        for mes, grupo in groupby(movimientos_ordenados_fecha, key=lambda mov: mov.fecha.strftime('%B %Y')):
            movimientos_agrupados.append({'mes': mes, 'movimientos': list(grupo)})
    context = {
        'movimientos': movimientos_brutos,
        'movimientos_agrupados': movimientos_agrupados,
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
                    tipo_consumible = TipoConsumible.objects.get(nombre=linea.descripcion)
                    ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                    coste_linea = ultima_compra.coste_por_unidad * linea.cantidad
                except (TipoConsumible.DoesNotExist, CompraConsumible.DoesNotExist): pass
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
    factura = orden.factura
    desglose = []
    ganancia_total = Decimal('0.00')
    gastos_asociados = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria__in=['Repuestos', 'Otros'])
    lineas_piezas = factura.lineas.filter(tipo__in=['Repuesto', 'Externo'])
    for gasto in gastos_asociados:
        pvp = Decimal('0.00')
        for linea in lineas_piezas:
            if gasto.descripcion == linea.descripcion:
                pvp = linea.precio_unitario
                break
        coste = gasto.importe
        ganancia = pvp - coste
        desglose.append({
            'descripcion': f"{gasto.get_categoria_display()}: {gasto.descripcion}",
            'coste': coste,
            'pvp': pvp,
            'ganancia': ganancia
        })
        ganancia_total += ganancia
    lineas_servicios = factura.lineas.filter(tipo__in=['Mano de Obra', 'Consumible'])
    for linea in lineas_servicios:
        pvp = linea.total_linea
        coste = Decimal('0.00')
        if linea.tipo == 'Consumible':
            try:
                tipo_consumible = TipoConsumible.objects.get(nombre=linea.descripcion)
                ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                coste = ultima_compra.coste_por_unidad * linea.cantidad
            except (TipoConsumible.DoesNotExist, CompraConsumible.DoesNotExist):
                coste = Decimal('0.00')
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
    gastos = Gasto.objects.all().order_by('-fecha')
    anos_y_meses = get_anos_y_meses_con_datos()
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado and mes_seleccionado:
        gastos = gastos.filter(fecha__year=ano_seleccionado, fecha__month=mes_seleccionado)
    total_gastos_filtrados = gastos.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    context = {
        'gastos': gastos,
        'total_gastos_filtrados': total_gastos_filtrados,
        'anos_y_meses': anos_y_meses,
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado else None,
        'mes_seleccionado': int(mes_seleccionado) if mes_seleccionado else None,
    }
    return render(request, 'taller/informe_gastos.html', context)

def informe_ingresos(request):
    ingresos = Ingreso.objects.all().order_by('-fecha')
    anos_y_meses = get_anos_y_meses_con_datos()
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado and mes_seleccionado:
        ingresos = ingresos.filter(fecha__year=ano_seleccionado, fecha__month=mes_seleccionado)
    total_ingresos_filtrados = ingresos.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    context = {
        'ingresos': ingresos,
        'categorias_ingreso': Ingreso.CATEGORIA_CHOICES,
        'total_ingresos_filtrados': total_ingresos_filtrados,
        'anos_y_meses': anos_y_meses,
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado else None,
        'mes_seleccionado': int(mes_seleccionado) if mes_seleccionado else None,
    }
    return render(request, 'taller/informe_ingresos.html', context)

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
        facturas = facturas.filter(fecha_emision__month=hoy.month, fecha__emision__year=hoy.year)
    total_ingresado = ingresos.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastado = gastos.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia = Decimal('0.00')
    ganancia_directa = ingresos.filter(categoria__in=['Grua', 'Otras Ganancias']).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia += ganancia_directa
    for factura in facturas:
        coste_piezas = Gasto.objects.filter(vehiculo=factura.orden.vehiculo, categoria__in=['Repuestos', 'Otros']).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        total_cobrado_piezas = Decimal('0.00')
        for linea in factura.lineas.filter(tipo__in=['Repuesto', 'Externo']):
            total_cobrado_piezas += linea.total_linea
        ganancia_piezas = total_cobrado_piezas - coste_piezas
        ganancia_servicios = Decimal('0.00')
        for linea in factura.lineas.filter(tipo__in=['Mano de Obra', 'Consumible']):
            coste_linea = Decimal('0.00')
            if linea.tipo == 'Consumible':
                try:
                    tipo_consumible = TipoConsumible.objects.get(nombre=linea.descripcion)
                    ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                    coste_linea = ultima_compra.coste_por_unidad * linea.cantidad
                except (TipoConsumible.DoesNotExist, CompraConsumible.DoesNotExist): pass
            ganancia_servicios += (linea.total_linea - coste_linea)
        total_ganancia += ganancia_piezas + ganancia_servicios
    context = {
        'total_ingresado': total_ingresado,
        'total_gastado': total_gastado,
        'total_ganancia': total_ganancia,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/contabilidad.html', context)

def cuentas_por_cobrar(request):
    facturas = Factura.objects.all().order_by('fecha_emision')
    anos_y_meses = get_anos_y_meses_con_datos()
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
    if ano_seleccionado and mes_seleccionado:
        facturas = facturas.filter(fecha_emision__year=ano_seleccionado, fecha_emision__month=mes_seleccionado)
    facturas_pendientes = []
    total_pendiente = Decimal('0.00')
    for factura in facturas:
        abonos = Ingreso.objects.filter(orden=factura.orden).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
        pendiente = factura.total_final - abonos
        if pendiente > 0:
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
        'anos_y_meses': anos_y_meses,
        'ano_seleccionado': int(ano_seleccionado) if ano_seleccionado else None,
        'mes_seleccionado': int(mes_seleccionado) if mes_seleccionado else None,
    }
    return render(request, 'taller/cuentas_por_cobrar.html', context)