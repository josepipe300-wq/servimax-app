# taller/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import Ingreso, Gasto, Cliente, Vehiculo, OrdenDeReparacion, Empleado, TipoConsumible, CompraConsumible, Factura, LineaFactura, FotoVehiculo
from django.db.models import Sum, F, Q # Importar Q
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
import os
from django.conf import settings

# --- FUNCIÓN AUXILIAR PARA LOS FILTROS DE FECHA ---
# (Sin cambios)
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

# --- FUNCIÓN AUXILIAR PARA OBTENER ÓRDENES RELEVANTES ---
def obtener_ordenes_relevantes():
    """
    Devuelve un QuerySet de OrdenDeReparacion que:
    - No están 'Entregadas' O
    - Están 'Entregadas' pero tienen saldo pendiente > 0.
    """
    ordenes_no_entregadas = OrdenDeReparacion.objects.exclude(estado='Entregado')

    ordenes_entregadas_con_saldo = []
    ordenes_entregadas = OrdenDeReparacion.objects.filter(estado='Entregado').select_related('factura') # Optimización

    for orden in ordenes_entregadas:
        try:
            # Intentar acceder a la factura precargada
            factura = orden.factura
            if factura:
                abonos = Ingreso.objects.filter(orden=orden).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
                pendiente = factura.total_final - abonos
                if pendiente > Decimal('0.01'): # Permitir pequeño margen
                    ordenes_entregadas_con_saldo.append(orden.id)
        except Factura.DoesNotExist:
            # Si está entregada pero no tiene factura (raro), la consideramos relevante por si acaso
            ordenes_entregadas_con_saldo.append(orden.id)
            pass # O podrías decidir no incluirla

    # Combinar los IDs y obtener el queryset final
    ids_relevantes = list(ordenes_no_entregadas.values_list('id', flat=True)) + ordenes_entregadas_con_saldo
    return OrdenDeReparacion.objects.filter(id__in=ids_relevantes).select_related('vehiculo', 'cliente') # Incluimos select_related aquí

# --- VISTA HOME (Modificada previamente) ---
# (Sin cambios respecto a la versión anterior que te di)
def home(request):
    hoy = datetime.now()
    mes_actual = hoy.month
    ano_actual = hoy.year
    ingresos_mes = Ingreso.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    gastos_mes = Gasto.objects.filter(fecha__month=mes_actual, fecha__year=ano_actual)
    total_ingresos = ingresos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos = gastos_mes.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    ingresos_efectivo = ingresos_mes.filter(es_tpv=False).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gastos_efectivo = gastos_mes.filter(pagado_con_tarjeta=False).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_caja = ingresos_efectivo - gastos_efectivo
    ingresos_tpv = ingresos_mes.filter(es_tpv=True).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gastos_tarjeta = gastos_mes.filter(pagado_con_tarjeta=True).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_tarjeta = ingresos_tpv - gastos_tarjeta
    ultimos_gastos = Gasto.objects.order_by('-id')[:5]
    ultimos_ingresos = Ingreso.objects.order_by('-id')[:5]
    movimientos_combinados = sorted(list(ultimos_gastos) + list(ultimos_ingresos), key=lambda mov: mov.fecha if hasattr(mov, 'fecha') else datetime.min.date(), reverse=True)
    movimientos_recientes = movimientos_combinados[:5]
    context = {
        'total_ingresos': total_ingresos,
        'total_gastos': total_gastos,
        'balance_caja': balance_caja,
        'balance_tarjeta': balance_tarjeta,
        'movimientos_recientes': movimientos_recientes,
    }
    return render(request, 'taller/home.html', context)


# --- VISTA INGRESAR VEHÍCULO (Sin cambios) ---
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


# --- VISTA AÑADIR GASTO (Modificada para filtrar vehículos) ---
def anadir_gasto(request):
    if request.method == 'POST':
        # --- Lógica POST sin cambios respecto a la versión anterior ---
        categoria = request.POST['categoria']
        pagado_con_tarjeta = request.POST.get('pagado_con_tarjeta') == 'true'
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
                descripcion=f"Compra de {cantidad} {tipo_consumible.unidad_medida} de {tipo_consumible.nombre}",
                pagado_con_tarjeta=pagado_con_tarjeta
            )
        else:
            importe = request.POST['importe']
            descripcion = request.POST['descripcion']
            gasto = Gasto(
                categoria=categoria,
                importe=importe,
                descripcion=descripcion,
                pagado_con_tarjeta=pagado_con_tarjeta
            )
            if categoria in ['Repuestos', 'Otros']:
                vehiculo_id = request.POST.get('vehiculo')
                if vehiculo_id:
                    # Validar si el vehículo seleccionado está asociado a una orden relevante
                    ordenes_relevantes = obtener_ordenes_relevantes()
                    if ordenes_relevantes.filter(vehiculo_id=vehiculo_id).exists():
                         gasto.vehiculo = Vehiculo.objects.get(id=vehiculo_id)
                    # else: Opcional: añadir mensaje de error si se intenta asociar a un vehículo "cerrado"
            if categoria == 'Sueldos':
                empleado_id = request.POST.get('empleado')
                if empleado_id:
                    gasto.empleado = Empleado.objects.get(id=empleado_id)
            gasto.save()
            # Actualizar estado de orden (sin cambios)
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

    # --- Lógica GET: Filtrar vehículos ---
    ordenes_relevantes = obtener_ordenes_relevantes()
    # Obtenemos los IDs de los vehículos asociados a esas órdenes
    vehiculos_ids_relevantes = ordenes_relevantes.values_list('vehiculo_id', flat=True).distinct()
    # Filtramos el queryset de vehículos
    vehiculos_filtrados = Vehiculo.objects.filter(id__in=vehiculos_ids_relevantes).select_related('cliente')

    context = {
        'vehiculos': vehiculos_filtrados, # <-- Pasamos la lista filtrada
        'empleados': Empleado.objects.all(),
        'tipos_consumible': TipoConsumible.objects.all(),
        'categorias_gasto': Gasto.CATEGORIA_CHOICES,
    }
    return render(request, 'taller/anadir_gasto.html', context)


# --- VISTA REGISTRAR INGRESO (Modificada para filtrar órdenes) ---
def registrar_ingreso(request):
    if request.method == 'POST':
         # --- Lógica POST sin cambios respecto a la versión anterior ---
        categoria = request.POST['categoria']
        importe = request.POST['importe']
        descripcion = request.POST['descripcion']
        es_tpv = request.POST.get('es_tpv') == 'true'
        ingreso = Ingreso(
            categoria=categoria,
            importe=importe,
            descripcion=descripcion,
            es_tpv=es_tpv
        )
        if categoria == 'Taller':
            orden_id = request.POST.get('orden')
            if orden_id:
                # Validar si la orden seleccionada está en la lista de relevantes
                ordenes_relevantes = obtener_ordenes_relevantes()
                try:
                    orden_seleccionada = ordenes_relevantes.get(id=orden_id)
                    ingreso.orden = orden_seleccionada
                except OrdenDeReparacion.DoesNotExist:
                     pass # Opcional: añadir mensaje de error si se intenta asociar a una orden "cerrada"

        ingreso.save()
        return redirect('home')

    # --- Lógica GET: Filtrar órdenes ---
    ordenes_filtradas = obtener_ordenes_relevantes().order_by('-fecha_entrada') # Ordenamos por fecha

    context = {
        'ordenes': ordenes_filtradas, # <-- Pasamos la lista filtrada
        'categorias_ingreso': Ingreso.CATEGORIA_CHOICES,
    }
    return render(request, 'taller/registrar_ingreso.html', context)


# --- VISTA STOCK INICIAL (Sin cambios) ---
def stock_inicial_consumible(request):
    if request.method == 'POST':
        tipo_id = request.POST['tipo_consumible']
        cantidad = Decimal(request.POST['cantidad'])
        coste_total = Decimal(request.POST['coste_total'])
        fecha_compra = datetime.now().date() # Usamos fecha actual para stock inicial
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


# --- OTRAS VISTAS (lista_ordenes, detalle_orden, etc. sin cambios) ---
# (Puedes mantener el resto de tu código de views.py aquí)
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
    return render(request, 'taller/detalle_orden.html', context) # Asegúrate que existe esta plantilla

def historial_ordenes(request):
    ordenes = OrdenDeReparacion.objects.filter(estado='Entregado').select_related('cliente', 'vehiculo', 'factura').order_by('-factura__fecha_emision') # Optimización y orden
    anos_y_meses = get_anos_y_meses_con_datos() # Reutilizar función auxiliar
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    if ano_seleccionado:
        ordenes = ordenes.filter(factura__fecha_emision__year=ano_seleccionado)
    if mes_seleccionado:
        ordenes = ordenes.filter(factura__fecha_emision__month=mes_seleccionado)

    # Convertir a int si existen para comparación en plantilla
    try:
        ano_seleccionado = int(ano_seleccionado) if ano_seleccionado else None
    except ValueError:
        ano_seleccionado = None
    try:
        mes_seleccionado = int(mes_seleccionado) if mes_seleccionado else None
    except ValueError:
        mes_seleccionado = None


    context = {
        'ordenes': ordenes,
        'anos_y_meses': anos_y_meses,
        'ano_seleccionado': ano_seleccionado,
        'mes_seleccionado': mes_seleccionado,
    }
    return render(request, 'taller/historial_ordenes.html', context)


def historial_movimientos(request):
    periodo = request.GET.get('periodo', 'semana') # Default a semana
    hoy = datetime.now().date()

    # Empezamos con todos los movimientos
    gastos_qs = Gasto.objects.all()
    ingresos_qs = Ingreso.objects.all()

    # Aplicar filtro de periodo
    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        gastos_qs = gastos_qs.filter(fecha__gte=inicio_semana)
        ingresos_qs = ingresos_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        gastos_qs = gastos_qs.filter(fecha__year=hoy.year, fecha__month=hoy.month)
        ingresos_qs = ingresos_qs.filter(fecha__year=hoy.year, fecha__month=hoy.month)
    # Si es 'todo', no filtramos por fecha

    # Combinar y ordenar por fecha descendente (más recientes primero)
    # Convertimos a lista para poder ordenar tipos diferentes
    movimientos = sorted(
        list(gastos_qs) + list(ingresos_qs),
        key=lambda x: x.fecha,
        reverse=True
    )

    context = {
        'movimientos': movimientos,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/historial_movimientos.html', context)

def editar_movimiento(request, tipo, movimiento_id):
    # Redirige a la vista de edición del admin de Django
    if tipo == 'gasto':
        return redirect(f'/admin/taller/gasto/{movimiento_id}/change/')
    elif tipo == 'ingreso':
        return redirect(f'/admin/taller/ingreso/{movimiento_id}/change/')
    else:
        # Por si acaso se pasa un tipo incorrecto
        return redirect('historial_movimientos')


def generar_factura(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion, id=orden_id)
    if request.method == 'POST':
        es_factura = 'aplicar_iva' in request.POST

        # Borramos factura anterior si existe para evitar duplicados
        Factura.objects.filter(orden=orden).delete()

        factura = Factura.objects.create(orden=orden, es_factura=es_factura)
        subtotal = Decimal('0.00')

        # Procesar Repuestos asociados a ESTA orden (si los hubiera)
        # Necesitaríamos una forma de asociar Gastos a Órdenes, no solo a Vehículos.
        # Por ahora, asumimos que los gastos del vehículo corresponden a la orden actual.
        repuestos = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
        for repuesto in repuestos:
            pvp_str = request.POST.get(f'pvp_repuesto_{repuesto.id}')
            if pvp_str:
                try:
                    pvp = Decimal(pvp_str)
                    if pvp < repuesto.importe: # Validación básica de coste
                         # Podrías mostrar un error aquí en lugar de continuar
                         pvp = repuesto.importe # O ajustar al coste mínimo
                    subtotal += pvp
                    LineaFactura.objects.create(factura=factura, tipo='Repuesto', descripcion=repuesto.descripcion, cantidad=1, precio_unitario=pvp)
                except (ValueError, TypeError):
                    pass # Ignorar si el valor no es un número válido

        # Procesar Trabajos Externos asociados a ESTA orden
        gastos_otros = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')
        for gasto in gastos_otros:
            pvp_str = request.POST.get(f'pvp_otro_{gasto.id}')
            if pvp_str:
                try:
                    pvp = Decimal(pvp_str)
                    if pvp < gasto.importe: # Validación básica de coste
                        pvp = gasto.importe
                    subtotal += pvp
                    LineaFactura.objects.create(factura=factura, tipo='Externo', descripcion=gasto.descripcion, cantidad=1, precio_unitario=pvp)
                except (ValueError, TypeError):
                    pass

        # Procesar Consumibles
        tipos_consumible = request.POST.getlist('tipo_consumible')
        cantidades_consumible = request.POST.getlist('consumible_cantidad')
        pvps_consumible = request.POST.getlist('consumible_pvp_total')

        for i in range(len(tipos_consumible)):
            if tipos_consumible[i] and cantidades_consumible[i] and pvps_consumible[i]:
                try:
                    tipo = TipoConsumible.objects.get(id=tipos_consumible[i])
                    cantidad = Decimal(cantidades_consumible[i])
                    pvp_total = Decimal(pvps_consumible[i])
                    if cantidad > 0:
                        precio_unitario_calculado = pvp_total / cantidad
                        subtotal += pvp_total
                        LineaFactura.objects.create(
                            factura=factura,
                            tipo='Consumible',
                            descripcion=tipo.nombre, # Usar el nombre del tipo
                            cantidad=cantidad,
                            precio_unitario=precio_unitario_calculado
                        )
                        # Registrar el uso del consumible
                        UsoConsumible.objects.create(orden=orden, tipo=tipo, cantidad_usada=cantidad)
                except (TipoConsumible.DoesNotExist, ValueError, TypeError, Decimal.InvalidOperation):
                     pass # Ignorar línea si hay error

        # Procesar Mano de Obra
        descripciones_mo = request.POST.getlist('mano_obra_desc')
        importes_mo = request.POST.getlist('mano_obra_importe')
        for desc, importe_str in zip(descripciones_mo, importes_mo):
            if desc and importe_str:
                try:
                    importe = Decimal(importe_str)
                    subtotal += importe
                    LineaFactura.objects.create(
                        factura=factura,
                        tipo='Mano de Obra',
                        descripcion=f"{desc}", # Simplificado
                        cantidad=1,
                        precio_unitario=importe
                    )
                except (ValueError, TypeError, Decimal.InvalidOperation):
                    pass # Ignorar línea si hay error

        # Calcular IVA y Total Final
        iva_calculado = Decimal('0.00')
        if es_factura:
            iva_calculado = subtotal * Decimal('0.21') # Asumiendo IVA al 21%

        total_final = subtotal + iva_calculado

        # Guardar totales en la factura
        factura.subtotal = subtotal
        factura.iva = iva_calculado
        factura.total_final = total_final
        factura.save()

        # Actualizar estado de la orden
        orden.estado = 'Listo para Recoger'
        orden.save()

        return redirect('detalle_orden', orden_id=orden.id)

    # Si no es POST, redirigir de vuelta
    return redirect('detalle_orden', orden_id=orden.id)

# --- VISTA ver_factura_pdf (Sin cambios) ---
def ver_factura_pdf(request, factura_id):
    factura = get_object_or_404(Factura, id=factura_id)
    cliente = factura.orden.cliente
    vehiculo = factura.orden.vehiculo
    abonos = Ingreso.objects.filter(orden=factura.orden).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    pendiente = factura.total_final - abonos
    lineas = factura.lineas.all()
    # Ordenar tipos para el PDF
    orden_tipos = ['Mano de Obra', 'Repuesto', 'Consumible', 'Externo'] # Priorizar Mano de Obra
    # Crear un diccionario para agrupar líneas por tipo
    lineas_agrupadas = {tipo: [] for tipo in orden_tipos}
    for linea in lineas:
        if linea.tipo in lineas_agrupadas:
            lineas_agrupadas[linea.tipo].append(linea)
        else: # Por si acaso hay un tipo no esperado
             if 'Otros' not in lineas_agrupadas: lineas_agrupadas['Otros'] = []
             lineas_agrupadas['Otros'].append(linea)

    # Convertir el diccionario a una lista ordenada para la plantilla
    lineas_ordenadas_agrupadas = []
    for tipo in orden_tipos:
        if lineas_agrupadas[tipo]:
            lineas_ordenadas_agrupadas.extend(lineas_agrupadas[tipo])
    # Añadir 'Otros' si existen
    if 'Otros' in lineas_agrupadas and lineas_agrupadas['Otros']:
         lineas_ordenadas_agrupadas.extend(lineas_agrupadas['Otros'])


    context = {
        'factura': factura,
        'cliente': cliente,
        'vehiculo': vehiculo,
        'lineas': lineas_ordenadas_agrupadas, # Usar la lista ordenada y agrupada
        'abonos': abonos,
        'pendiente': pendiente,
        # Pasar STATIC_URL al contexto si usas {% static %} en la plantilla PDF
        'STATIC_URL': settings.STATIC_URL,
         # Construir la ruta completa al logo si es necesario
        'logo_path': os.path.join(settings.BASE_DIR, 'taller', 'static', 'taller', 'images', 'logo.jpg')

    }
    template_path = 'taller/plantilla_factura.html'
    template = get_template(template_path)
    html = template.render(context)

    response = HttpResponse(content_type='application/pdf')
    # Quitar 'inline;' para forzar descarga
    response['Content-Disposition'] = f'inline; filename="fact_{factura.orden.vehiculo.matricula}_{factura.id}.pdf"'

    # create a pdf
    pisa_status = pisa.CreatePDF(
       html, dest=response #, link_callback=link_callback # Necesario si hay imágenes/CSS externos
    )
    # if error then show some funy view
    if pisa_status.err:
       return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


def editar_factura(request, factura_id):
    factura = get_object_or_404(Factura, id=factura_id)
    orden = factura.orden
    if request.method == 'POST':
        # Al editar, borramos la factura vieja y creamos una nueva con los datos del POST
        orden_id = factura.orden.id
        factura.delete() # Elimina la factura y sus líneas asociadas (por CASCADE)
        # También deberíamos eliminar los UsoConsumible asociados a esta factura/orden? Depende...
        # UsoConsumible.objects.filter(orden=orden).delete() # Descomentar si quieres resetear usos
        return generar_factura(request, orden_id) # Reutiliza la lógica de creación

    # Lógica GET para pre-rellenar el formulario (más compleja)
    # Necesitaríamos pasar las líneas existentes a la plantilla para mostrarlas
    # y adaptar el JavaScript para manejar edición/eliminación.
    # Por simplicidad, esta versión solo permite "re-hacer" la factura.

    # Pasamos los mismos datos que al crear, pero indicando que es una edición
    repuestos = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos') # Asociados al vehículo
    gastos_otros = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros') # Asociados al vehículo
    tipos_consumible = TipoConsumible.objects.all()

    # Pre-cargar datos de líneas existentes (simplificado, solo para ejemplo)
    lineas_existentes = {
        'repuestos': list(factura.lineas.filter(tipo='Repuesto').values('descripcion', 'precio_unitario')),
        'externos': list(factura.lineas.filter(tipo='Externo').values('descripcion', 'precio_unitario')),
        'consumibles': list(factura.lineas.filter(tipo='Consumible').values('descripcion', 'cantidad', 'precio_unitario')),
        'mo': list(factura.lineas.filter(tipo='Mano de Obra').values('descripcion', 'precio_unitario'))
    }


    context = {
        'orden': orden,
        'factura_existente': factura, # Para saber que estamos editando
        'repuestos': repuestos,
        'gastos_otros': gastos_otros,
        'tipos_consumible': tipos_consumible,
        'lineas_existentes': lineas_existentes, # Pasar líneas para posible pre-llenado en JS
    }
    # Usaremos una plantilla específica o adaptaremos la de detalle_orden si es necesario
    return render(request, 'taller/editar_factura.html', context)


# --- VISTAS DE INFORMES (informe_rentabilidad, detalle_ganancia_orden, etc.) ---
# (Sin cambios respecto a la versión anterior que te di)
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
        # Coste de piezas/externos asociados a la orden específica (si tuviéramos esa relación)
        # Si no, usamos los del vehículo como aproximación
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
                    tipo_consumible = TipoConsumible.objects.get(nombre__iexact=linea.descripcion)
                    ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                    coste_linea = (ultima_compra.coste_por_unidad or Decimal('0.00')) * linea.cantidad
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
    try:
        factura = orden.factura # Acceder a la factura relacionada
    except Factura.DoesNotExist:
         # Si no hay factura, no podemos calcular desglose, redirigir o mostrar error
         return redirect('detalle_orden', orden_id=orden.id) # O mostrar mensaje

    desglose = []
    ganancia_total = Decimal('0.00')

    # Piezas y Trabajos Externos: Comparar líneas de factura con gastos asociados
    # Asumiendo que los gastos del vehículo corresponden a esta orden (mejoraría con Gasto.orden)
    gastos_asociados = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria__in=['Repuestos', 'Otros'])
    lineas_piezas = factura.lineas.filter(tipo__in=['Repuesto', 'Externo'])

    gastos_usados = set() # Para no contar un gasto dos veces si aparece en varias líneas

    for linea in lineas_piezas:
        coste = Decimal('0.00')
        gasto_encontrado = None
        # Intentar encontrar el gasto correspondiente por descripción (puede fallar si no es exacto)
        for gasto in gastos_asociados:
            if gasto.id not in gastos_usados and gasto.descripcion.strip().upper() == linea.descripcion.strip().upper():
                 gasto_encontrado = gasto
                 gastos_usados.add(gasto.id)
                 break
        if gasto_encontrado:
             coste = gasto_encontrado.importe or Decimal('0.00')

        pvp = linea.total_linea # El precio de venta es el total de la línea
        ganancia = pvp - coste
        desglose.append({
            'descripcion': f"{linea.get_tipo_display()}: {linea.descripcion}",
            'coste': coste,
            'pvp': pvp,
            'ganancia': ganancia
        })
        ganancia_total += ganancia

     # Añadir gastos asociados que NO se encontraron en líneas de factura (coste sin venta)
    # for gasto in gastos_asociados:
    #      if gasto.id not in gastos_usados:
    #          coste = gasto.importe or Decimal('0.00')
    #          ganancia = -coste # Ganancia negativa (es un coste no repercutido)
    #          desglose.append({
    #              'descripcion': f"{gasto.get_categoria_display()} (No facturado): {gasto.descripcion}",
    #              'coste': coste,
    #              'pvp': Decimal('0.00'),
    #              'ganancia': ganancia
    #          })
    #          ganancia_total += ganancia


    # Mano de Obra y Consumibles
    lineas_servicios = factura.lineas.filter(tipo__in=['Mano de Obra', 'Consumible'])
    for linea in lineas_servicios:
        pvp = linea.total_linea
        coste = Decimal('0.00')
        descripcion_detalle = linea.descripcion # Por defecto

        if linea.tipo == 'Consumible':
             descripcion_detalle = f"Consumible: {linea.descripcion}"
             try:
                tipo_consumible = TipoConsumible.objects.get(nombre__iexact=linea.descripcion)
                ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                coste = (ultima_compra.coste_por_unidad or Decimal('0.00')) * linea.cantidad
             except (TipoConsumible.DoesNotExist, CompraConsumible.DoesNotExist):
                 coste = Decimal('0.00') # Coste 0 si no hay registro de compra
        elif linea.tipo == 'Mano de Obra':
             # Descripción ya incluye "Mano de Obra:"
             descripcion_detalle = linea.descripcion # Coste de mano de obra directa es 0 (se asume cubierto por precio)


        ganancia = pvp - coste
        desglose.append({
            'descripcion': descripcion_detalle,
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
    anos_disponibles_g = Gasto.objects.dates('fecha', 'year', order='DESC').distinct()
    anos_disponibles_i = Ingreso.objects.dates('fecha', 'year', order='DESC').distinct()
    anos_disponibles = sorted(list(set([d.year for d in anos_disponibles_g] + [d.year for d in anos_disponibles_i])), reverse=True)
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    if ano_seleccionado:
        gastos = gastos.filter(fecha__year=ano_seleccionado)
    if mes_seleccionado:
        gastos = gastos.filter(fecha__month=mes_seleccionado)

    totales_por_categoria_query = gastos.values('categoria').annotate(total=Sum('importe')).order_by('categoria')
    categoria_display_map = dict(Gasto.CATEGORIA_CHOICES)
    resumen_categorias = {}
    for item in totales_por_categoria_query:
         # Usar la clave interna ('Compra de Consumibles') para el enlace, pero el nombre legible para mostrar
         clave_interna = item['categoria']
         nombre_legible = categoria_display_map.get(clave_interna, clave_interna)
         resumen_categorias[clave_interna] = {
             'display_name': nombre_legible,
             'total': item['total'] or Decimal('0.00')
         }


    sueldos = gastos.filter(categoria='Sueldos', empleado__isnull=False)
    desglose_sueldos_query = sueldos.values('empleado__nombre').annotate(total=Sum('importe')).order_by('empleado__nombre')
    desglose_sueldos = {
        item['empleado__nombre']: item['total'] or Decimal('0.00')
        for item in desglose_sueldos_query
    }

    try:
        ano_seleccionado = int(ano_seleccionado) if ano_seleccionado else None
    except ValueError:
        ano_seleccionado = None
    try:
        mes_seleccionado = int(mes_seleccionado) if mes_seleccionado else None
    except ValueError:
        mes_seleccionado = None

    context = {
        'totales_por_categoria': resumen_categorias,
        'desglose_sueldos': desglose_sueldos,
        'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_seleccionado,
        'mes_seleccionado': mes_seleccionado,
    }
    return render(request, 'taller/informe_gastos.html', context)

def informe_gastos_desglose(request, categoria, empleado_nombre=None):
    gastos = Gasto.objects.all()
    categoria_map = dict(Gasto.CATEGORIA_CHOICES)
    # Reemplazar guion bajo si viene de la URL (aunque ahora usamos clave interna)
    categoria_limpia = categoria.replace('_', ' ')

    if empleado_nombre:
        # Asegurarse de decodificar el nombre de la URL si tiene espacios
        empleado_nombre_limpio = empleado_nombre.replace('_', ' ')
        gastos = gastos.filter(categoria='Sueldos', empleado__nombre__iexact=empleado_nombre_limpio)
        titulo = f"Desglose de Sueldos: {empleado_nombre_limpio.upper()}"
    else:
        # Filtrar por la clave interna (que viene de la URL)
        gastos = gastos.filter(categoria__iexact=categoria_limpia)
        # Obtener el nombre legible para el título
        titulo_categoria = categoria_map.get(categoria_limpia, categoria_limpia)
        titulo = f"Desglose de Gastos: {titulo_categoria}"


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
        # Pasar la categoría original (con guiones bajos si los tenía) para el botón volver
        'categoria_original_url': categoria
    }
    return render(request, 'taller/informe_gastos_desglose.html', context)


def informe_ingresos(request):
    ingresos = Ingreso.objects.all()
    anos_disponibles_g = Gasto.objects.dates('fecha', 'year', order='DESC').distinct()
    anos_disponibles_i = Ingreso.objects.dates('fecha', 'year', order='DESC').distinct()
    anos_disponibles = sorted(list(set([d.year for d in anos_disponibles_g] + [d.year for d in anos_disponibles_i])), reverse=True)
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    if ano_seleccionado:
        ingresos = ingresos.filter(fecha__year=ano_seleccionado)
    if mes_seleccionado:
        ingresos = ingresos.filter(fecha__month=mes_seleccionado)

    totales_por_categoria_query = ingresos.values('categoria').annotate(total=Sum('importe')).order_by('categoria')
    categoria_display_map = dict(Ingreso.CATEGORIA_CHOICES)
    resumen_categorias = {
        item['categoria']: {
            'display_name': categoria_display_map.get(item['categoria'], item['categoria']),
            'total': item['total'] or Decimal('0.00')
        }
        for item in totales_por_categoria_query
    }

    try:
        ano_seleccionado = int(ano_seleccionado) if ano_seleccionado else None
    except ValueError:
        ano_seleccionado = None
    try:
        mes_seleccionado = int(mes_seleccionado) if mes_seleccionado else None
    except ValueError:
        mes_seleccionado = None


    context = {
        'totales_por_categoria': resumen_categorias,
        'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_seleccionado,
        'mes_seleccionado': mes_seleccionado,
    }
    return render(request, 'taller/informe_ingresos.html', context)

def informe_ingresos_desglose(request, categoria):
    ingresos = Ingreso.objects.all()
    categoria_display_map = dict(Ingreso.CATEGORIA_CHOICES)
    categoria_filtrar = categoria.replace('_', ' ') # Por si viene con guion bajo
    titulo = f"Desglose de Ingresos: {categoria_display_map.get(categoria_filtrar, categoria_filtrar)}"

    ingresos = ingresos.filter(categoria__iexact=categoria_filtrar)

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
        'categoria_original_url': categoria # Para el botón volver
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

    total_ganancia = Decimal('0.00')
    ganancia_directa = ingresos.filter(categoria__in=['Grua', 'Otras Ganancias']).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia += ganancia_directa

    for factura in facturas:
        # Necesitamos recalcular costes asociados a CADA factura
        coste_piezas_externos_factura = Gasto.objects.filter(vehiculo=factura.orden.vehiculo, categoria__in=['Repuestos', 'Otros']).aggregate(total=Sum('importe'))['total'] or Decimal('0.00') # Simplificación: asociar todos los gastos del vehiculo
        coste_consumibles_factura = Decimal('0.00')
        for linea in factura.lineas.filter(tipo='Consumible'):
            try:
                tipo_consumible = TipoConsumible.objects.get(nombre__iexact=linea.descripcion)
                ultima_compra = CompraConsumible.objects.filter(tipo=tipo_consumible, fecha_compra__lte=factura.fecha_emision).latest('fecha_compra')
                coste_consumibles_factura += (ultima_compra.coste_por_unidad or Decimal('0.00')) * linea.cantidad
            except (TipoConsumible.DoesNotExist, CompraConsumible.DoesNotExist): pass

        total_cobrado_trabajo = factura.subtotal if factura.es_factura else factura.total_final
        ganancia_factura = total_cobrado_trabajo - coste_piezas_externos_factura - coste_consumibles_factura
        total_ganancia += ganancia_factura

    # Restar gastos NO asociados directamente a las facturas del periodo
    # gastos_generales = gastos.exclude(Q(categoria__in=['Repuestos', 'Compra de Consumibles']) | Q(categoria='Otros', vehiculo__isnull=False)).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    # total_ganancia_neta = total_ganancia - gastos_generales # Beneficio Neto (aproximado)


    context = {
        'total_ingresado': total_ingresado,
        'total_gastado': total_gastado,
        'total_ganancia': total_ganancia, # Beneficio Bruto
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/contabilidad.html', context)


def cuentas_por_cobrar(request):
    anos_y_meses = get_anos_y_meses_con_datos()
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
    facturas = Factura.objects.all()
    if ano_seleccionado:
        facturas = facturas.filter(fecha_emision__year=ano_seleccionado)
    if mes_seleccionado:
        facturas = facturas.filter(fecha_emision__month=mes_seleccionado)

    facturas_pendientes = []
    total_pendiente = Decimal('0.00')

    # Optimizar: obtener todos los ingresos relevantes de una vez
    orden_ids = facturas.values_list('orden_id', flat=True)
    abonos_dict = Ingreso.objects.filter(orden_id__in=orden_ids).values('orden_id').annotate(total_abonos=Sum('importe'))
    abonos_por_orden = {item['orden_id']: item['total_abonos'] for item in abonos_dict}


    for factura in facturas.select_related('orden__cliente', 'orden__vehiculo').order_by('fecha_emision'): # Optimizar consulta
        abonos = abonos_por_orden.get(factura.orden_id, Decimal('0.00')) # Obtener abonos del diccionario
        pendiente = factura.total_final - abonos
        if pendiente > Decimal('0.01'): # Margen de error
            facturas_pendientes.append({
                'factura': factura,
                'orden': factura.orden,
                'cliente': factura.orden.cliente,
                'vehiculo': factura.orden.vehiculo,
                'pendiente': pendiente,
            })
            total_pendiente += pendiente

    try:
        ano_seleccionado = int(ano_seleccionado) if ano_seleccionado else None
    except ValueError:
        ano_seleccionado = None
    try:
        mes_seleccionado = int(mes_seleccionado) if mes_seleccionado else None
    except ValueError:
        mes_seleccionado = None


    context = {
        'facturas_pendientes': facturas_pendientes,
        'total_pendiente': total_pendiente,
        'anos_y_meses': anos_y_meses,
        'ano_seleccionado': ano_seleccionado,
        'mes_seleccionado': mes_seleccionado,
    }
    return render(request, 'taller/cuentas_por_cobrar.html', context)

# --- VISTA INFORME TARJETA (Añadida previamente) ---
# (Sin cambios respecto a la versión anterior que te di)
from django.db.models import Q # Asegúrate de importar Q
def informe_tarjeta(request):
    periodo = request.GET.get('periodo', 'mes')
    hoy = datetime.now().date()
    ingresos_tpv = Ingreso.objects.filter(es_tpv=True)
    gastos_tarjeta = Gasto.objects.filter(pagado_con_tarjeta=True)
    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        ingresos_tpv = ingresos_tpv.filter(fecha__gte=inicio_semana)
        gastos_tarjeta = gastos_tarjeta.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        ingresos_tpv = ingresos_tpv.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        gastos_tarjeta = gastos_tarjeta.filter(fecha__month=hoy.month, fecha__year=hoy.year)
    total_ingresos_tpv = ingresos_tpv.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos_tarjeta = gastos_tarjeta.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_tarjeta = total_ingresos_tpv - total_gastos_tarjeta
    movimientos_tarjeta = sorted(
        list(ingresos_tpv) + list(gastos_tarjeta),
        key=lambda mov: mov.fecha,
        reverse=True
    )
    context = {
        'total_ingresos_tpv': total_ingresos_tpv,
        'total_gastos_tarjeta': total_gastos_tarjeta,
        'balance_tarjeta': balance_tarjeta,
        'movimientos_tarjeta': movimientos_tarjeta,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/informe_tarjeta.html', context)