# taller/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import (
    Ingreso, Gasto, Cliente, Vehiculo, OrdenDeReparacion, Empleado,
    TipoConsumible, CompraConsumible, Factura, LineaFactura, FotoVehiculo,
    Presupuesto, LineaPresupuesto, UsoConsumible # <-- CORREGIDO: AÑADIDO UsoConsumible
)
from django.db.models import Sum, F, Q # Importar Q
from django.db import transaction # <-- Importamos transaction para seguridad en edición
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
import os
from django.conf import settings
from django.utils import timezone # Necesario para Presupuesto
import json # Necesario para editar_factura
from django.urls import reverse # Necesario para editar_movimiento

# --- FUNCIÓN AUXILIAR PARA LOS FILTROS DE FECHA ---
def get_anos_y_meses_con_datos():
    fechas_gastos = Gasto.objects.values_list('fecha', flat=True)
    fechas_ingresos = Ingreso.objects.values_list('fecha', flat=True)
    fechas_facturas = Factura.objects.values_list('fecha_emision', flat=True)
    fechas_presupuestos = Presupuesto.objects.values_list('fecha_creacion', flat=True) # Añadir fechas presupuesto

    # Convertir DateTimeField a Date para la comparación
    fechas_presupuestos_date = [dt.date() for dt in fechas_presupuestos if dt] # Asegurarse que dt no es None

    # Combinar todas las fechas únicas
    fechas_combinadas = set(fechas_gastos) | set(fechas_ingresos) | set(fechas_facturas) | set(fechas_presupuestos_date)
    # Filtrar None si existe
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

    # Ordenar los meses dentro de cada año
    for ano in anos_y_meses:
        anos_y_meses[ano].sort()

    # Ordenar los años
    anos_ordenados = sorted(anos_y_meses.keys(), reverse=True)
    anos_y_meses_ordenado = {ano: anos_y_meses[ano] for ano in anos_ordenados}


    return anos_y_meses_ordenado


# --- FUNCIÓN AUXILIAR PARA OBTENER ÓRDENES RELEVANTES ---
def obtener_ordenes_relevantes():
    """
    Devuelve un QuerySet de OrdenDeReparacion que:
    - No están 'Entregadas' O
    - Están 'Entregadas' pero tienen saldo pendiente > 0.
    """
    ordenes_no_entregadas = OrdenDeReparacion.objects.exclude(estado='Entregado')

    ordenes_entregadas_con_saldo = []
    # Usar prefetch_related para cargar ingresos asociados eficientemente
    ordenes_entregadas = OrdenDeReparacion.objects.filter(estado='Entregado').select_related('factura').prefetch_related('ingreso_set')

    for orden in ordenes_entregadas:
        try:
            # Intentar acceder a la factura; si no existe, salta a DoesNotExist
            factura = orden.factura
            # Calcular abonos desde los ingresos precargados
            abonos = sum(ing.importe for ing in orden.ingreso_set.all()) if orden.ingreso_set.exists() else Decimal('0.00')
            pendiente = factura.total_final - abonos
            if pendiente > Decimal('0.01'): # Permitir pequeño margen
                ordenes_entregadas_con_saldo.append(orden.id)
        except Factura.DoesNotExist:
            # Si está entregada pero no tiene factura (raro), la consideramos relevante
            ordenes_entregadas_con_saldo.append(orden.id)
        except AttributeError: # Si factura es None (raro pero posible)
             ordenes_entregadas_con_saldo.append(orden.id)


    # Combinar los IDs y obtener el queryset final
    ids_relevantes = list(ordenes_no_entregadas.values_list('id', flat=True)) + ordenes_entregadas_con_saldo
    # Devolver IDs únicos para evitar duplicados
    return OrdenDeReparacion.objects.filter(id__in=list(set(ids_relevantes))).select_related('vehiculo', 'cliente')


# --- VISTA HOME ---
def home(request):
    hoy = timezone.now() # Usar timezone.now() para consistencia
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
    movimientos_combinados = sorted(
        list(ultimos_gastos) + list(ultimos_ingresos),
        key=lambda mov: mov.fecha if hasattr(mov, 'fecha') else timezone.now().date(),
        reverse=True
    )
    movimientos_recientes = movimientos_combinados[:5]

    # --- CÁLCULO DE STOCK Y ALERTAS ---
    tipos_consumible = TipoConsumible.objects.all()
    alertas_stock = []
    for tipo in tipos_consumible:
        total_comprado = CompraConsumible.objects.filter(tipo=tipo).aggregate(total=Sum('cantidad'))['total'] or Decimal('0.00')
        total_usado = UsoConsumible.objects.filter(tipo=tipo).aggregate(total=Sum('cantidad_usada'))['total'] or Decimal('0.00')
        stock_actual = total_comprado - total_usado
        if tipo.nivel_minimo_stock is not None and stock_actual <= tipo.nivel_minimo_stock:
            alertas_stock.append({
                'nombre': tipo.nombre,
                'stock_actual': stock_actual,
                'unidad': tipo.unidad_medida,
                'minimo': tipo.nivel_minimo_stock
            })
    # --- FIN CÁLCULO DE STOCK ---

    # ---> ¡ASEGÚRATE DE QUE ESTAS LÍNEAS ESTÉN INDENTADAS CORRECTAMENTE! <---
    context = {
        'total_ingresos': total_ingresos,
        'total_gastos': total_gastos,
        'balance_caja': balance_caja,
        'balance_tarjeta': balance_tarjeta,
        'movimientos_recientes': movimientos_recientes,
        'alertas_stock': alertas_stock, 
    }
    return render(request, 'taller/home.html', context) # <--- Esta línea también debe estar indentada


# --- VISTA INGRESAR VEHÍCULO ---
def ingresar_vehiculo(request):
    if request.method == 'POST':
        nombre_cliente = request.POST['cliente_nombre'].upper()
        telefono_cliente = request.POST['cliente_telefono']
        matricula_vehiculo = request.POST['vehiculo_matricula'].upper()
        marca_vehiculo = request.POST['vehiculo_marca'].upper()
        modelo_vehiculo = request.POST['vehiculo_modelo'].upper()
        kilometraje_vehiculo_str = request.POST.get('vehiculo_kilometraje')
        kilometraje_vehiculo = int(kilometraje_vehiculo_str) if kilometraje_vehiculo_str else 0 # Convertir a int, default 0
        problema_reportado = request.POST['problema'].upper()

        cliente, created = Cliente.objects.get_or_create(
            telefono=telefono_cliente,
            defaults={'nombre': nombre_cliente}
        )
        vehiculo, v_created = Vehiculo.objects.get_or_create(
            matricula=matricula_vehiculo,
            defaults={
                'marca': marca_vehiculo,
                'modelo': modelo_vehiculo,
                'kilometraje': kilometraje_vehiculo, # Ya es int o 0
                'cliente': cliente
            }
        )
        # Actualizar kilometraje si el vehículo ya existía y el nuevo es mayor
        if not v_created and kilometraje_vehiculo > vehiculo.kilometraje:
            vehiculo.kilometraje = kilometraje_vehiculo
            vehiculo.save()
        # Asociar cliente correcto si el vehículo existía con otro cliente
        elif not v_created and vehiculo.cliente != cliente:
             vehiculo.cliente = cliente
             vehiculo.save()

        presupuesto_id = request.POST.get('presupuesto_asociado')
        presupuesto = None
        if presupuesto_id:
            try:
                # Buscar presupuesto válido para asociar
                presupuesto = Presupuesto.objects.get(id=presupuesto_id, estado='Aceptado')
                # Si el vehículo se acaba de crear y el presupuesto tenía datos, actualizarlos
                if v_created and presupuesto.marca_nueva and not vehiculo.marca:
                     vehiculo.marca = presupuesto.marca_nueva
                     vehiculo.modelo = presupuesto.modelo_nuevo
                     vehiculo.save() # Guardar vehículo actualizado
            except Presupuesto.DoesNotExist:
                presupuesto = None # No hacer nada si no se encuentra o no es válido

        # Crear la orden asociando el presupuesto si se encontró
        nueva_orden = OrdenDeReparacion.objects.create(
            cliente=cliente,
            vehiculo=vehiculo,
            problema=problema_reportado,
            presupuesto_origen=presupuesto
        )

        # Si se asoció un presupuesto, cambiar su estado a 'Convertido'
        if presupuesto:
            presupuesto.estado = 'Convertido'
            presupuesto.save()

        # Guardar fotos
        descripciones = ['Frontal', 'Trasera', 'Lateral Izquierdo', 'Lateral Derecho', 'Cuadro/Km']
        for i in range(1, 6):
            foto_campo = f'foto{i}'
            if foto_campo in request.FILES:
                FotoVehiculo.objects.create(
                    orden=nueva_orden,
                    imagen=request.FILES[foto_campo],
                    descripcion=descripciones[i-1]
                )

        # Ir a la página de detalle de la nueva orden creada
        return redirect('detalle_orden', orden_id=nueva_orden.id)


    # --- Lógica GET ---
    presupuestos_disponibles = Presupuesto.objects.filter(estado='Aceptado').select_related('cliente', 'vehiculo').order_by('-fecha_creacion')
    context = {
        'presupuestos_disponibles': presupuestos_disponibles
    }
    return render(request, 'taller/ingresar_vehiculo.html', context)


# --- VISTA AÑADIR GASTO ---
def anadir_gasto(request):
    if request.method == 'POST':
        categoria = request.POST['categoria']
        pagado_con_tarjeta = request.POST.get('pagado_con_tarjeta') == 'true'

        if categoria == 'Compra de Consumibles':
            tipo_id = request.POST.get('tipo_consumible')
            fecha_compra_str = request.POST.get('fecha_compra')
            cantidad_str = request.POST.get('cantidad')
            coste_total_str = request.POST.get('coste_total')

            # Validar que los campos necesarios no estén vacíos
            if not all([tipo_id, fecha_compra_str, cantidad_str, coste_total_str]):
                 # Aquí podrías añadir un mensaje de error para el usuario
                 return redirect('anadir_gasto') # Redirigir de nuevo al formulario

            try:
                cantidad = Decimal(cantidad_str)
                coste_total = Decimal(coste_total_str)
                # Validar valores no negativos
                if cantidad <= 0 or coste_total < 0:
                     return redirect('anadir_gasto') # O mostrar error
                tipo_consumible = get_object_or_404(TipoConsumible, id=tipo_id)

                # Validar fecha
                try:
                    fecha_compra = datetime.strptime(fecha_compra_str, '%Y-%m-%d').date()
                except ValueError:
                    return redirect('anadir_gasto') # Fecha inválida

                CompraConsumible.objects.create(
                    tipo=tipo_consumible,
                    fecha_compra=fecha_compra,
                    cantidad=cantidad,
                    coste_total=coste_total
                )
                Gasto.objects.create(
                    fecha=fecha_compra, # Usar la fecha de compra para el gasto
                    categoria=categoria,
                    importe=coste_total,
                    descripcion=f"Compra de {cantidad} {tipo_consumible.unidad_medida} de {tipo_consumible.nombre}",
                    pagado_con_tarjeta=pagado_con_tarjeta
                )
            except (ValueError, TypeError, Decimal.InvalidOperation):
                 return redirect('anadir_gasto')


        else: # Otros tipos de gasto
            importe_str = request.POST.get('importe')
            descripcion = request.POST.get('descripcion', '')
            fecha_gasto_str = request.POST.get('fecha_gasto') # Campo fecha opcional para otros gastos

             # Usar fecha proporcionada o la actual si no se da
            try:
                fecha_gasto = datetime.strptime(fecha_gasto_str, '%Y-%m-%d').date() if fecha_gasto_str else timezone.now().date()
            except ValueError:
                fecha_gasto = timezone.now().date() # Usar fecha actual si el formato es incorrecto

            # Validar importe
            try:
                importe = Decimal(importe_str) if importe_str else None
                if importe is not None and importe < 0:
                     importe = None # Ignorar importes negativos o manejar error
            except (ValueError, TypeError, Decimal.InvalidOperation):
                importe = None # Poner a None si no es un número válido

            # Crear objeto Gasto
            gasto = Gasto(
                fecha=fecha_gasto, # Usar la fecha determinada
                categoria=categoria,
                importe=importe,
                descripcion=descripcion.upper(), # Guardar en mayúsculas
                pagado_con_tarjeta=pagado_con_tarjeta
            )

            # Asociar vehículo si aplica y es válido
            if categoria in ['Repuestos', 'Otros']:
                vehiculo_id = request.POST.get('vehiculo')
                if vehiculo_id:
                    try:
                        vehiculo = Vehiculo.objects.get(id=vehiculo_id)
                        ordenes_relevantes = obtener_ordenes_relevantes()
                        if ordenes_relevantes.filter(vehiculo=vehiculo).exists():
                            gasto.vehiculo = vehiculo
                    except Vehiculo.DoesNotExist: pass

            # Asociar empleado si aplica y es válido
            if categoria == 'Sueldos':
                empleado_id = request.POST.get('empleado')
                if empleado_id:
                     try:
                        gasto.empleado = Empleado.objects.get(id=empleado_id)
                     except Empleado.DoesNotExist: pass

            gasto.save() # Guardar el gasto

            # Actualizar estado de la orden si se asoció vehículo y categoría relevante
            if gasto.vehiculo and categoria in ['Repuestos', 'Otros']:
                try:
                    orden_a_actualizar = OrdenDeReparacion.objects.filter(
                        vehiculo=gasto.vehiculo,
                        estado__in=['Recibido', 'En Diagnostico']
                    ).latest('fecha_entrada')
                    orden_a_actualizar.estado = 'En Reparacion'
                    orden_a_actualizar.save()
                except OrdenDeReparacion.DoesNotExist: pass

        return redirect('home') # Redirigir a home tras guardar

    # --- Lógica GET ---
    ordenes_relevantes = obtener_ordenes_relevantes()
    vehiculos_ids_relevantes = ordenes_relevantes.values_list('vehiculo_id', flat=True).distinct()
    vehiculos_filtrados = Vehiculo.objects.filter(id__in=vehiculos_ids_relevantes).select_related('cliente')
    empleados = Empleado.objects.all()
    tipos_consumible = TipoConsumible.objects.all()
    # Excluir 'Compra de Consumibles' de las opciones directas
    categorias_gasto_choices = [choice for choice in Gasto.CATEGORIA_CHOICES if choice[0] != 'Compra de Consumibles']


    context = {
        'vehiculos': vehiculos_filtrados,
        'empleados': empleados,
        'tipos_consumible': tipos_consumible,
        'categorias_gasto': Gasto.CATEGORIA_CHOICES, # Pasar todas para el JS
        'categorias_gasto_select': categorias_gasto_choices, # Pasar filtradas para el select inicial
    }
    return render(request, 'taller/anadir_gasto.html', context)


# --- VISTA REGISTRAR INGRESO ---
def registrar_ingreso(request):
    if request.method == 'POST':
        categoria = request.POST['categoria']
        importe_str = request.POST.get('importe')
        descripcion = request.POST.get('descripcion', '')
        es_tpv = request.POST.get('es_tpv') == 'true'
        fecha_ingreso_str = request.POST.get('fecha_ingreso') # Añadir campo fecha

        # Usar fecha proporcionada o la actual si no se da
        try:
            fecha_ingreso = datetime.strptime(fecha_ingreso_str, '%Y-%m-%d').date() if fecha_ingreso_str else timezone.now().date()
        except ValueError:
            fecha_ingreso = timezone.now().date() # Usar fecha actual si el formato es incorrecto

        # Validar importe
        try:
            importe = Decimal(importe_str) if importe_str else Decimal('0.00')
            if importe <= 0:
                 # Añadir mensaje de error, importe debe ser positivo
                 return redirect('registrar_ingreso')
        except (ValueError, TypeError, Decimal.InvalidOperation):
            # Añadir mensaje de error
            return redirect('registrar_ingreso')


        ingreso = Ingreso(
            fecha=fecha_ingreso, # Usar la fecha determinada
            categoria=categoria,
            importe=importe,
            descripcion=descripcion.upper(), # Guardar en mayúsculas
            es_tpv=es_tpv
        )

        # Asociar orden si aplica y es válida
        if categoria == 'Taller':
            orden_id = request.POST.get('orden')
            if orden_id:
                ordenes_relevantes = obtener_ordenes_relevantes() # Asegura que la orden esté "abierta"
                try:
                    # Usar get_object_or_404 sería más directo si queremos error si no existe
                    orden_seleccionada = ordenes_relevantes.get(id=orden_id)
                    ingreso.orden = orden_seleccionada
                except OrdenDeReparacion.DoesNotExist:
                     # Añadir mensaje indicando que la orden no es válida o está cerrada
                     pass # O redirigir con error

        ingreso.save()
        return redirect('home')

    # --- Lógica GET ---
    # Obtener solo órdenes que aún no están totalmente pagadas o no entregadas
    ordenes_filtradas = obtener_ordenes_relevantes().order_by('-fecha_entrada')
    categorias_ingreso = Ingreso.CATEGORIA_CHOICES

    context = {
        'ordenes': ordenes_filtradas,
        'categorias_ingreso': categorias_ingreso,
    }
    return render(request, 'taller/registrar_ingreso.html', context)


# --- VISTA STOCK INICIAL ---
def stock_inicial_consumible(request):
    if request.method == 'POST':
        tipo_id = request.POST['tipo_consumible']
        cantidad_str = request.POST.get('cantidad')
        coste_total_str = request.POST.get('coste_total')

        try:
            cantidad = Decimal(cantidad_str)
            coste_total = Decimal(coste_total_str)
            if cantidad <= 0 or coste_total < 0:
                 # Añadir mensaje de error
                 return redirect('stock_inicial_consumible')

            tipo_consumible = get_object_or_404(TipoConsumible, id=tipo_id)
            # Usar fecha actual para registrar la compra inicial
            fecha_compra = timezone.now().date()
            CompraConsumible.objects.create(
                tipo=tipo_consumible,
                fecha_compra=fecha_compra,
                cantidad=cantidad,
                coste_total=coste_total
            )
            # No se crea un Gasto aquí, solo la Compra
            return redirect('home')

        except (ValueError, TypeError, Decimal.InvalidOperation):
            # Añadir mensaje de error
            return redirect('stock_inicial_consumible')


    # --- Lógica GET ---
    tipos_consumible = TipoConsumible.objects.all()
    context = {
        'tipos_consumible': tipos_consumible
    }
    return render(request, 'taller/stock_inicial_consumible.html', context)

# --- VISTA CREAR PRESUPUESTO ---
def crear_presupuesto(request):
    if request.method == 'POST':
        cliente_id = request.POST.get('cliente_existente')
        nombre_cliente_form = request.POST.get('cliente_nombre', '').upper()
        telefono_cliente_form = request.POST.get('cliente_telefono', '')

        cliente = None
        created = False # Variable para saber si el cliente fue creado o encontrado

        if cliente_id:
            try:
                cliente = Cliente.objects.get(id=cliente_id)
            except Cliente.DoesNotExist: pass
        elif nombre_cliente_form and telefono_cliente_form:
            # --- LÓGICA DE CLIENTE MODIFICADA (PARA ACTUALIZAR NOMBRE SI TELÉFONO EXISTE) ---
            try:
                cliente = Cliente.objects.get(telefono=telefono_cliente_form)
                if nombre_cliente_form and cliente.nombre != nombre_cliente_form:
                    cliente.nombre = nombre_cliente_form
                    cliente.save()
            except Cliente.DoesNotExist:
                cliente = Cliente.objects.create(nombre=nombre_cliente_form, telefono=telefono_cliente_form)
                created = True
            # --- FIN LÓGICA DE CLIENTE MODIFICADA ---

        if not cliente:
             return HttpResponse("Error: Cliente inválido o no proporcionado.", status=400)

        # --- Lógica del vehículo (sin cambios) ---
        vehiculo_id = request.POST.get('vehiculo_existente')
        matricula_nueva = request.POST.get('matricula_nueva', '').upper()
        marca_nueva = request.POST.get('marca_nueva', '').upper()
        modelo_nuevo = request.POST.get('modelo_nuevo', '').upper()

        vehiculo = None
        if vehiculo_id:
            try:
                vehiculo = Vehiculo.objects.get(id=vehiculo_id)
                if vehiculo.cliente != cliente:
                     vehiculo.cliente = cliente
                     vehiculo.save()
            except Vehiculo.DoesNotExist: pass
        elif not matricula_nueva:
             pass

        # --- Lógica del presupuesto y líneas (sin cambios) ---
        problema = request.POST.get('problema_o_trabajo', '').upper()

        presupuesto = Presupuesto.objects.create(
            cliente=cliente,
            vehiculo=vehiculo,
            matricula_nueva=matricula_nueva if not vehiculo and matricula_nueva else None,
            marca_nueva=marca_nueva if not vehiculo and marca_nueva else None,
            modelo_nuevo=modelo_nuevo if not vehiculo and modelo_nuevo else None,
            problema_o_trabajo=problema,
            estado='Pendiente'
        )

        tipos_linea = request.POST.getlist('linea_tipo')
        descripciones_linea = request.POST.getlist('linea_descripcion')
        cantidades_linea = request.POST.getlist('linea_cantidad')
        precios_linea = request.POST.getlist('linea_precio_unitario')
        total_estimado_calculado = Decimal('0.00')

        lineas_creadas = False
        for i in range(len(tipos_linea)):
             if all([tipos_linea[i], descripciones_linea[i], cantidades_linea[i], precios_linea[i]]):
                 try:
                     cantidad = Decimal(cantidades_linea[i])
                     precio_unitario = Decimal(precios_linea[i])
                     if cantidad <= 0 or precio_unitario < 0: continue

                     linea_total = cantidad * precio_unitario
                     total_estimado_calculado += linea_total
                     LineaPresupuesto.objects.create(
                         presupuesto=presupuesto,
                         tipo=tipos_linea[i],
                         descripcion=descripciones_linea[i].upper(),
                         cantidad=cantidad,
                         precio_unitario_estimado=precio_unitario
                     )
                     lineas_creadas = True
                 except (ValueError, TypeError, Decimal.InvalidOperation): pass

        presupuesto.total_estimado = total_estimado_calculado
        presupuesto.save()

        return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)


    # --- Lógica GET ---
    clientes = Cliente.objects.all().order_by('nombre')
    vehiculos = Vehiculo.objects.select_related('cliente').order_by('matricula')
    tipos_linea = LineaFactura.TIPO_CHOICES
    context = {
        'clientes': clientes,
        'vehiculos': vehiculos,
        'tipos_linea': tipos_linea,
    }
    return render(request, 'taller/crear_presupuesto.html', context)

# --- VISTA LISTA PRESUPUESTOS (CON FILTROS DE FECHA) ---
def lista_presupuestos(request):
    estado_filtro = request.GET.get('estado')
    ano_seleccionado = request.GET.get('ano') # <-- NUEVO
    mes_seleccionado = request.GET.get('mes') # <-- NUEVO

    presupuestos_qs = Presupuesto.objects.select_related('cliente', 'vehiculo').order_by('-fecha_creacion')

    # Aplicar filtro de estado
    if estado_filtro and estado_filtro in [choice[0] for choice in Presupuesto.ESTADO_CHOICES]:
        presupuestos_qs = presupuestos_qs.filter(estado=estado_filtro)

    # Aplicar filtros de fecha si son válidos <-- NUEVO BLOQUE
    if ano_seleccionado:
        try:
            ano_int = int(ano_seleccionado)
            presupuestos_qs = presupuestos_qs.filter(fecha_creacion__year=ano_int)
        except (ValueError, TypeError):
            ano_seleccionado = None # Ignorar si no es un número válido
    if mes_seleccionado:
         try:
            mes_int = int(mes_seleccionado)
            if 1 <= mes_int <= 12:
                presupuestos_qs = presupuestos_qs.filter(fecha_creacion__month=mes_int)
            else:
                mes_seleccionado = None # Ignorar si no es un mes válido
         except (ValueError, TypeError):
            mes_seleccionado = None # Ignorar si no es un número válido
    # --- FIN NUEVO BLOQUE ---

    # Obtener años y meses para los filtros
    anos_y_meses_data = get_anos_y_meses_con_datos() # <-- NUEVO
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True) # <-- NUEVO

    # Convertir selecciones a int para la plantilla (si existen) <-- NUEVO
    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None
    mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None


    context = {
        'presupuestos': presupuestos_qs,
        'estado_actual': estado_filtro,
        'estados_posibles': Presupuesto.ESTADO_CHOICES,
        'anos_y_meses': anos_y_meses_data, # <-- NUEVO
        'anos_disponibles': anos_disponibles, # <-- NUEVO
        'ano_seleccionado': ano_sel_int, # <-- NUEVO
        'mes_seleccionado': mes_sel_int, # <-- NUEVO
        'meses_del_ano': range(1, 13) # <-- NUEVO (Para el select de meses)
    }
    return render(request, 'taller/lista_presupuestos.html', context)


# --- VISTA DETALLE PRESUPUESTO ---
def detalle_presupuesto(request, presupuesto_id):
    # Obtener el presupuesto o mostrar error 404 si no existe
    # Usamos select_related y prefetch_related para optimizar
    presupuesto = get_object_or_404(
        Presupuesto.objects.select_related('cliente', 'vehiculo__cliente') # Cargar cliente y cliente del vehículo
                          .prefetch_related('lineas'), # Cargar líneas
        id=presupuesto_id
    )

    # Manejar cambio de estado si se envía el formulario
    if request.method == 'POST' and 'nuevo_estado' in request.POST:
        nuevo_estado = request.POST['nuevo_estado']
        # Validar que el nuevo estado sea válido y que no esté ya 'Convertido'
        estados_validos_cambio = ['Aceptado', 'Rechazado', 'Pendiente']
        if nuevo_estado in estados_validos_cambio and presupuesto.estado != 'Convertido':
            presupuesto.estado = nuevo_estado
            presupuesto.save()
            # Redirigir a la misma página para ver el cambio
            return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)
        # else: Podríamos añadir un mensaje si el estado no es válido o ya está convertido

    # Intentar obtener la orden generada si existe
    orden_generada = None
    try:
        # Acceder a través del related_name 'orden_generada'
        orden_generada = presupuesto.orden_generada
    except OrdenDeReparacion.DoesNotExist:
        pass # No existe orden asociada

    context = {
        'presupuesto': presupuesto,
        'lineas': presupuesto.lineas.all(), # Ya están precargadas por prefetch_related
        'estados_posibles': Presupuesto.ESTADO_CHOICES, # Para el selector de estado
        'orden_generada': orden_generada # Pasar la orden al contexto si existe
    }
    return render(request, 'taller/detalle_presupuesto.html', context)

# --- VISTA EDITAR PRESUPUESTO (CON TRANSACCIÓN ATÓMICA) ---
def editar_presupuesto(request, presupuesto_id):
    presupuesto = get_object_or_404(
        Presupuesto.objects.select_related('cliente', 'vehiculo')
                           .prefetch_related('lineas'), # Cargar líneas
        id=presupuesto_id
    )

    # No permitir editar si ya está convertido a orden
    if presupuesto.estado == 'Convertido':
        return redirect('detalle_presupuesto', presupuesto_id=presupuesto.id)

    if request.method == 'POST':
        # --- INICIO BLOQUE ATÓMICO: PROTECCIÓN CONTRA PÉRDIDA DE DATOS ---
        try:
            with transaction.atomic():
                
                # 1. Borrar el presupuesto existente (las líneas se borran en cascada)
                presupuesto_id_original = presupuesto.id # Guardar ID por si falla
                presupuesto.delete()

                # 2. Reutilizar la lógica de 'crear_presupuesto' adaptada para guardar
                cliente_id = request.POST.get('cliente_existente')
                nombre_cliente_form = request.POST.get('cliente_nombre', '').upper()
                telefono_cliente_form = request.POST.get('cliente_telefono', '')
                cliente = None
                if cliente_id:
                    try: cliente = Cliente.objects.get(id=cliente_id)
                    except Cliente.DoesNotExist: pass
                elif nombre_cliente_form and telefono_cliente_form:
                    try:
                        cliente = Cliente.objects.get(telefono=telefono_cliente_form)
                        if nombre_cliente_form and cliente.nombre != nombre_cliente_form:
                            cliente.nombre = nombre_cliente_form
                            cliente.save()
                    except Cliente.DoesNotExist:
                        cliente = Cliente.objects.create(nombre=nombre_cliente_form, telefono=telefono_cliente_form)
                if not cliente: 
                    raise ValueError("Error: Cliente inválido.") 

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
                elif not matricula_nueva: pass

                problema = request.POST.get('problema_o_trabajo', '').upper()
                # Crear NUEVO presupuesto con los datos del formulario
                nuevo_presupuesto = Presupuesto.objects.create(
                    cliente=cliente, vehiculo=vehiculo,
                    matricula_nueva=matricula_nueva if not vehiculo and matricula_nueva else None,
                    marca_nueva=marca_nueva if not vehiculo and marca_nueva else None,
                    modelo_nuevo=modelo_nuevo if not vehiculo and modelo_nuevo else None,
                    problema_o_trabajo=problema,
                    estado='Pendiente' # Vuelve a Pendiente
                )

                tipos_linea = request.POST.getlist('linea_tipo')
                descripciones_linea = request.POST.getlist('linea_descripcion')
                cantidades_linea = request.POST.getlist('linea_cantidad')
                precios_linea = request.POST.getlist('linea_precio_unitario')
                total_estimado_calculado = Decimal('0.00')

                for i in range(len(tipos_linea)):
                     if all([tipos_linea[i], descripciones_linea[i], cantidades_linea[i], precios_linea[i]]):
                         try:
                             cantidad = Decimal(cantidades_linea[i])
                             precio_unitario = Decimal(precios_linea[i])
                             if cantidad <= 0 or precio_unitario < 0: continue
                             linea_total = cantidad * precio_unitario
                             total_estimado_calculado += linea_total
                             LineaPresupuesto.objects.create(
                                 presupuesto=nuevo_presupuesto, tipo=tipos_linea[i],
                                 descripcion=descripciones_linea[i].upper(), cantidad=cantidad,
                                 precio_unitario_estimado=precio_unitario
                             )
                         except (ValueError, TypeError, Decimal.InvalidOperation): 
                             raise ValueError("Una de las líneas de presupuesto es inválida.")

                nuevo_presupuesto.total_estimado = total_estimado_calculado
                nuevo_presupuesto.save()

                # Redirigir al detalle del *nuevo* presupuesto creado
                return redirect('detalle_presupuesto', presupuesto_id=nuevo_presupuesto.id)

        except Exception as e:
            # En caso de cualquier error, redirigimos de vuelta al formulario de edición 
            # (el presupuesto original sigue ahí gracias a la transacción).
            # Aquí podrías usar messages.error(request, str(e)) para notificar el error.
            return redirect('editar_presupuesto', presupuesto_id=presupuesto_id_original) # Usar ID original guardado
            
        # --- FIN BLOQUE ATÓMICO ---


    # --- Lógica GET (Mostrar formulario con datos existentes) ---
    clientes = Cliente.objects.all().order_by('nombre')
    vehiculos = Vehiculo.objects.select_related('cliente').order_by('matricula')
    tipos_linea = LineaFactura.TIPO_CHOICES # Reutilizar tipos

    # Preparar datos de líneas existentes para JavaScript
    lineas_existentes_list = []
    for linea in presupuesto.lineas.all(): # Usar líneas precargadas
        linea_data = {
            'tipo': linea.tipo,
            'descripcion': linea.descripcion,
            'cantidad': float(linea.cantidad), # Float para JS
            'precio_unitario_estimado': float(linea.precio_unitario_estimado), # Float para JS
        }
        lineas_existentes_list.append(linea_data)

    context = {
        'presupuesto_existente': presupuesto, # Pasar el presupuesto para pre-rellenar campos
        'clientes': clientes,
        'vehiculos': vehiculos,
        'tipos_linea': tipos_linea,
        'lineas_existentes_json': json.dumps(lineas_existentes_list), # Convertir a JSON
    }
    return render(request, 'taller/editar_presupuesto.html', context)


# --- VISTA LISTA ORDENES ---
def lista_ordenes(request):
    # Mostrar órdenes que no estén entregadas
    ordenes_activas = OrdenDeReparacion.objects.exclude(estado='Entregado').select_related('cliente', 'vehiculo').order_by('-fecha_entrada')
    context = {
        'ordenes': ordenes_activas,
    }
    return render(request, 'taller/lista_ordenes.html', context)


# --- VISTA DETALLE ORDEN ---
def detalle_orden(request, orden_id):
    # Cargar orden con relaciones importantes
    orden = get_object_or_404(
        OrdenDeReparacion.objects.select_related(
            'cliente', 'vehiculo', 'presupuesto_origen' # Cargar presupuesto si existe
        ).prefetch_related('fotos', 'ingreso_set', 'factura'), # Prefetch factura, fotos e ingresos
        id=orden_id
    )

    # Gastos asociados al vehículo (mejoraría si se asociaran a la orden)
    repuestos = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
    gastos_otros = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')

    # Abonos (usando prefetch)
    abonos = sum(ing.importe for ing in orden.ingreso_set.all()) if hasattr(orden, 'ingreso_set') and orden.ingreso_set.exists() else Decimal('0.00')


    tipos_consumible = TipoConsumible.objects.all()
    factura = None
    pendiente_pago = Decimal('0.00')
    try:
        # Acceder a la factura precargada
        factura = orden.factura
        pendiente_pago = factura.total_final - abonos
    except Factura.DoesNotExist:
        pass # No hay factura, pendiente_pago sigue en 0

    # Manejar cambio de estado
    if request.method == 'POST' and 'nuevo_estado' in request.POST:
        nuevo_estado = request.POST['nuevo_estado']
        if nuevo_estado in [choice[0] for choice in OrdenDeReparacion.ESTADO_CHOICES]:
            orden.estado = nuevo_estado
            orden.save()
        return redirect('detalle_orden', orden_id=orden.id)

    context = {
        'orden': orden,
        'repuestos': repuestos,
        'gastos_otros': gastos_otros,
        'factura': factura,
        'abonos': abonos,
        'pendiente_pago': pendiente_pago, # Ya es 0 si no hay factura
        'tipos_consumible': tipos_consumible,
        'fotos': orden.fotos.all(), # Usar prefetch
        'estados_orden': OrdenDeReparacion.ESTADO_CHOICES,
    }
    return render(request, 'taller/detalle_orden.html', context)


# --- VISTA HISTORIAL ORDENES ---
def historial_ordenes(request):
    # Queryset base optimizado
    ordenes_qs = OrdenDeReparacion.objects.filter(estado='Entregado').select_related('cliente', 'vehiculo', 'factura')

    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)

    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    # Aplicar filtros de fecha si son válidos
    if ano_seleccionado:
        try:
            ano_int = int(ano_seleccionado)
            ordenes_qs = ordenes_qs.filter(factura__fecha_emision__year=ano_int)
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
         try:
            mes_int = int(mes_seleccionado)
            if 1 <= mes_int <= 12:
                ordenes_qs = ordenes_qs.filter(factura__fecha_emision__month=mes_int)
            else: mes_seleccionado = None
         except (ValueError, TypeError): mes_seleccionado = None

    # Ordenar resultados
    ordenes = ordenes_qs.order_by('-factura__fecha_emision', '-id')

    # Convertir selecciones a int para la plantilla
    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None
    mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None


    context = {
        'ordenes': ordenes,
        'anos_y_meses': anos_y_meses_data, # Pasar diccionario completo
        'anos_disponibles': anos_disponibles, # Pasar solo años para selector AÑO
        'ano_seleccionado': ano_sel_int,
        'mes_seleccionado': mes_sel_int,
        'meses_del_ano': range(1, 13) # Pasar rango de meses para selector MES
    }
    return render(request, 'taller/historial_ordenes.html', context)


# --- VISTA HISTORIAL MOVIMIENTOS ---
def historial_movimientos(request):
    periodo = request.GET.get('periodo', 'semana')
    hoy = timezone.now().date() # Usar timezone.now()

    gastos_qs = Gasto.objects.all()
    ingresos_qs = Ingreso.objects.all()

    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        gastos_qs = gastos_qs.filter(fecha__gte=inicio_semana)
        ingresos_qs = ingresos_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        gastos_qs = gastos_qs.filter(fecha__year=hoy.year, fecha__month=hoy.month)
        ingresos_qs = ingresos_qs.filter(fecha__year=hoy.year, fecha__month=hoy.month)

    # Combinar y ordenar
    movimientos = sorted(
        list(gastos_qs) + list(ingresos_qs),
        # Usar fecha como clave principal y ID como secundaria para orden estable
        key=lambda x: (x.fecha, -x.id if hasattr(x, 'id') else 0),
        reverse=True
    )

    context = {
        'movimientos': movimientos,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/historial_movimientos.html', context)


# --- VISTA EDITAR MOVIMIENTO ---
def editar_movimiento(request, tipo, movimiento_id):
    # Validar tipo
    if tipo not in ['gasto', 'ingreso']:
        return redirect('historial_movimientos') # O mostrar error 404

    admin_url_name = f'admin:taller_{tipo}_change' # Construir nombre URL admin
    try:
        admin_url = reverse(admin_url_name, args=[movimiento_id])
        return redirect(admin_url)
    except Exception as e:
        print(f"Error reversing admin URL: {e}") # Log del error
        # Fallback a URL hardcoded (menos ideal pero funciona si el admin está en /admin/)
        return redirect(f'/admin/taller/{tipo}/{movimiento_id}/change/')



# --- VISTA GENERAR FACTURA ---
def generar_factura(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo'), id=orden_id) # Cargar vehiculo

    if request.method == 'POST':
        es_factura = 'aplicar_iva' in request.POST

        # Borrar factura y usos de consumibles anteriores si existen
        Factura.objects.filter(orden=orden).delete()
        UsoConsumible.objects.filter(orden=orden).delete()

        factura = Factura.objects.create(orden=orden, es_factura=es_factura)
        subtotal = Decimal('0.00')

        # --- CORRECCIÓN LÓGICA: Procesar Repuestos y Trabajos Externos ---
        # 1. Obtener los gastos asociados al vehículo de la ORDEN (que aparecen en el formulario)
        repuestos_qs = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
        gastos_otros_qs = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')

        # Procesar Repuestos
        for repuesto in repuestos_qs:
            pvp_str = request.POST.get(f'pvp_repuesto_{repuesto.id}')
            if pvp_str:
                try:
                    pvp = Decimal(pvp_str)
                    coste_repuesto = repuesto.importe or Decimal('0.00')
                    # Validación de coste (opcional pero bueno)
                    if pvp < coste_repuesto: pvp = coste_repuesto
                    
                    subtotal += pvp
                    LineaFactura.objects.create(
                        factura=factura, 
                        tipo='Repuesto', 
                        descripcion=repuesto.descripcion, # Usar la descripción original del Gasto
                        cantidad=1, 
                        precio_unitario=pvp
                    )
                except (ValueError, TypeError, Decimal.InvalidOperation): pass

        # Procesar Trabajos Externos (Otros)
        for gasto_otro in gastos_otros_qs:
            pvp_str = request.POST.get(f'pvp_otro_{gasto_otro.id}')
            if pvp_str:
                try:
                    pvp = Decimal(pvp_str)
                    coste_gasto = gasto_otro.importe or Decimal('0.00')
                    if pvp < coste_gasto: pvp = coste_gasto
                    
                    subtotal += pvp
                    LineaFactura.objects.create(
                        factura=factura, 
                        tipo='Externo', 
                        descripcion=gasto_otro.descripcion, # Usar la descripción original del Gasto
                        cantidad=1, 
                        precio_unitario=pvp
                    )
                except (ValueError, TypeError, Decimal.InvalidOperation): pass
        # --- FIN CORRECCIÓN LÓGICA DE GASTOS ASOCIADOS ---


        # Procesar Consumibles
        tipos_consumible_id = request.POST.getlist('tipo_consumible')
        cantidades_consumible = request.POST.getlist('consumible_cantidad')
        pvps_consumible = request.POST.getlist('consumible_pvp_total')

        for i in range(len(tipos_consumible_id)):
            if tipos_consumible_id[i] and cantidades_consumible[i] and pvps_consumible[i]:
                try:
                    tipo = TipoConsumible.objects.get(id=tipos_consumible_id[i])
                    cantidad = Decimal(cantidades_consumible[i])
                    pvp_total = Decimal(pvps_consumible[i])
                    if cantidad <= 0 or pvp_total < 0: continue

                    precio_unitario_calculado = (pvp_total / cantidad).quantize(Decimal('0.01'))
                    subtotal += pvp_total
                    LineaFactura.objects.create(
                        factura=factura, tipo='Consumible', descripcion=tipo.nombre,
                        cantidad=cantidad, precio_unitario=precio_unitario_calculado
                    )
                    UsoConsumible.objects.create(orden=orden, tipo=tipo, cantidad_usada=cantidad)
                except (TipoConsumible.DoesNotExist, ValueError, TypeError, Decimal.InvalidOperation, ZeroDivisionError): pass

        # Procesar Mano de Obra
        descripciones_mo = request.POST.getlist('mano_obra_desc')
        importes_mo = request.POST.getlist('mano_obra_importe')
        for desc, importe_str in zip(descripciones_mo, importes_mo):
            if desc and importe_str:
                try:
                    importe = Decimal(importe_str)
                    if importe <= 0: continue
                    subtotal += importe
                    LineaFactura.objects.create(
                        factura=factura, tipo='Mano de Obra', descripcion=desc.upper(),
                        cantidad=1, precio_unitario=importe
                    )
                except (ValueError, TypeError, Decimal.InvalidOperation): pass

        # Calcular IVA y Total Final
        iva_calculado = Decimal('0.00')
        subtotal_positivo = max(subtotal, Decimal('0.00')) # Asegurar no negativo
        if es_factura:
            iva_calculado = (subtotal_positivo * Decimal('0.21')).quantize(Decimal('0.01'))

        total_final = subtotal_positivo + iva_calculado # Sumar IVA a subtotal no negativo

        factura.subtotal = subtotal # Guardar subtotal real
        factura.iva = iva_calculado
        factura.total_final = total_final
        factura.save()

        orden.estado = 'Listo para Recoger'
        orden.save()

        return redirect('detalle_orden', orden_id=orden.id)

    # Si no es POST o falla
    return redirect('detalle_orden', orden_id=orden.id)


# --- VISTA VER FACTURA PDF ---
def ver_factura_pdf(request, factura_id):
    factura = get_object_or_404(Factura.objects.select_related('orden__cliente', 'orden__vehiculo'), id=factura_id)
    cliente = factura.orden.cliente
    vehiculo = factura.orden.vehiculo
    # Optimizar cálculo de abonos usando related_name 'ingreso_set'
    abonos = factura.orden.ingreso_set.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    pendiente = factura.total_final - abonos
    lineas = factura.lineas.all() # Usar prefetch_related si se necesita optimizar más

    orden_tipos = ['Mano de Obra', 'Repuesto', 'Consumible', 'Externo']
    lineas_agrupadas = {tipo: [] for tipo in orden_tipos}
    otros_tipos = []
    for linea in lineas:
        if linea.tipo in lineas_agrupadas: lineas_agrupadas[linea.tipo].append(linea)
        else: otros_tipos.append(linea)

    lineas_ordenadas_agrupadas = []
    for tipo in orden_tipos: lineas_ordenadas_agrupadas.extend(lineas_agrupadas[tipo])
    lineas_ordenadas_agrupadas.extend(otros_tipos)

    context = {
        'factura': factura, 'cliente': cliente, 'vehiculo': vehiculo,
        'lineas': lineas_ordenadas_agrupadas, 'abonos': abonos, 'pendiente': pendiente,
        'STATIC_URL': settings.STATIC_URL,
        # Construir ruta asegurando que BASE_DIR es un objeto Path
        'logo_path': os.path.join(settings.BASE_DIR, 'taller', 'static', 'taller', 'images', 'logo.jpg')
    }
    template_path = 'taller/plantilla_factura.html'
    template = get_template(template_path)
    html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    # Corregido: asegurar que la matrícula no sea None antes de usarla en el nombre
    matricula_filename = factura.orden.vehiculo.matricula if factura.orden.vehiculo else 'SIN_MATRICULA'
    response['Content-Disposition'] = f'inline; filename="fact_{matricula_filename}_{factura.id}.pdf"'


    # Callback para encontrar recursos estáticos
    def link_callback(uri, rel):
        logo_uri_abs = context.get('logo_path')
        if logo_uri_abs: logo_uri_abs = logo_uri_abs.replace("\\", "/") # Normalizar separadores
        if uri == logo_uri_abs: return logo_uri_abs

        if uri.startswith(settings.STATIC_URL):
            path = uri.replace(settings.STATIC_URL, "", 1)
            # Buscar en STATICFILES_DIRS (prioridad en desarrollo)
            for static_dir in settings.STATICFILES_DIRS:
                file_path = os.path.join(static_dir, path)
                if os.path.exists(file_path): return file_path
            # Fallback a STATIC_ROOT (si existe, para producción)
            if hasattr(settings, 'STATIC_ROOT') and settings.STATIC_ROOT:
                 file_path = os.path.join(settings.STATIC_ROOT, path)
                 if os.path.exists(file_path): return file_path

        # Si no se encuentra localmente, intentar retornar la URI original (para URLs externas)
        if uri.startswith("http://") or uri.startswith("https://"): return uri

        print(f"WARN: Could not resolve URI '{uri}' in PDF generation.")
        return None # Retornar None si no se encuentra para evitar error


    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err: return HttpResponse('Error al generar PDF: <pre>' + html + '</pre>')
    return response


# --- VISTA EDITAR FACTURA ---
# (Requiere import json)
def editar_factura(request, factura_id):
    factura = get_object_or_404(Factura.objects.prefetch_related('lineas'), id=factura_id) # Cargar líneas
    # Cargar orden con vehículo y cliente asociados
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo__cliente'), id=factura.orden_id)

    if request.method == 'POST':
        # Borrar usos de consumible asociados a la ORDEN
        UsoConsumible.objects.filter(orden=orden).delete()
        # Borrar la factura vieja (líneas se borran en cascada)
        factura.delete()
        # Reutilizar la lógica de generar_factura
        return generar_factura(request, orden.id)

    # --- Lógica GET ---
    # Gastos asociados al vehículo para llenar selectores
    repuestos_qs = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Repuestos')
    gastos_otros_qs = Gasto.objects.filter(vehiculo=orden.vehiculo, categoria='Otros')
    tipos_consumible = TipoConsumible.objects.all()

    # Preparar datos de líneas existentes para JavaScript
    lineas_existentes_list = []
    for linea in factura.lineas.all(): # Usar líneas precargadas
        linea_data = {
            'tipo': linea.tipo,
            'descripcion': linea.descripcion,
            'cantidad': float(linea.cantidad), # Usar float para JS
            'precio_unitario': float(linea.precio_unitario),
            # IDs para preselección en <select>
            'tipo_consumible_id': None,
            'repuesto_id': None,
            'externo_id': None,
        }
        if linea.tipo == 'Consumible':
            tipo_obj = TipoConsumible.objects.filter(nombre__iexact=linea.descripcion).first()
            linea_data['tipo_consumible_id'] = tipo_obj.id if tipo_obj else None
        elif linea.tipo == 'Repuesto':
            # Buscar coincidencia entre los gastos disponibles para este vehículo
            gasto_obj = repuestos_qs.filter(descripcion__iexact=linea.descripcion).first()
            linea_data['repuesto_id'] = gasto_obj.id if gasto_obj else None
        elif linea.tipo == 'Externo':
            gasto_obj = gastos_otros_qs.filter(descripcion__iexact=linea.descripcion).first()
            linea_data['externo_id'] = gasto_obj.id if gasto_obj else None

        lineas_existentes_list.append(linea_data)

    context = {
        'orden': orden,
        'factura_existente': factura,
        'repuestos': repuestos_qs,
        'gastos_otros': gastos_otros_qs,
        'tipos_consumible': tipos_consumible,
        'lineas_existentes_json': json.dumps(lineas_existentes_list), # Convertir a JSON
    }

    return render(request, 'taller/editar_factura.html', context)


# --- INFORME RENTABILIDAD ---
def informe_rentabilidad(request):
    periodo = request.GET.get('periodo', 'mes')
    hoy = timezone.now().date()

    # Filtrar facturas, ingresos_grua y otras_ganancias según el periodo
    facturas_qs = Factura.objects.select_related('orden__vehiculo').prefetch_related('lineas', 'orden__vehiculo__gasto_set')
    ingresos_grua_qs = Ingreso.objects.filter(categoria='Grua')
    otras_ganancias_qs = Ingreso.objects.filter(categoria='Otras Ganancias')

    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        facturas_qs = facturas_qs.filter(fecha_emision__gte=inicio_semana)
        ingresos_grua_qs = ingresos_grua_qs.filter(fecha__gte=inicio_semana)
        otras_ganancias_qs = otras_ganancias_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        facturas_qs = facturas_qs.filter(fecha_emision__month=hoy.month, fecha_emision__year=hoy.year)
        ingresos_grua_qs = ingresos_grua_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        otras_ganancias_qs = otras_ganancias_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)

    facturas = facturas_qs.order_by('-fecha_emision')
    ingresos_grua = ingresos_grua_qs.order_by('-fecha')
    otras_ganancias = otras_ganancias_qs.order_by('-fecha')


    ganancia_trabajos = Decimal('0.00')
    reporte = []

    # Pre-cargar todas las compras de consumibles
    compras_consumibles = CompraConsumible.objects.order_by('tipo_id', '-fecha_compra')
    # Crear un lookup rápido para la última compra por tipo
    ultimas_compras_por_tipo = {}
    for compra in compras_consumibles:
        if compra.tipo_id not in ultimas_compras_por_tipo:
            ultimas_compras_por_tipo[compra.tipo_id] = compra

    # Pre-cargar tipos de consumibles para mapeo nombre -> id
    tipos_consumible_dict = {tipo.nombre.upper(): tipo for tipo in TipoConsumible.objects.all()}


    for factura in facturas:
        orden = factura.orden
        if not orden or not orden.vehiculo: continue

        # Costes asociados a través de los gastos del vehículo (usando prefetch)
        gastos_orden_qs = orden.vehiculo.gasto_set.filter(categoria__in=['Repuestos', 'Otros']) if hasattr(orden.vehiculo, 'gasto_set') else Gasto.objects.none()
        coste_piezas_externos_factura = gastos_orden_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')


        total_cobrado_piezas_externos = Decimal('0.00')
        ganancia_servicios = Decimal('0.00')
        coste_consumibles_factura = Decimal('0.00') # Calcular coste de consumibles para esta factura

        # Usar las líneas precargadas
        for linea in factura.lineas.all():
            if linea.tipo in ['Repuesto', 'Externo']:
                total_cobrado_piezas_externos += linea.total_linea
            elif linea.tipo in ['Mano de Obra', 'Consumible']:
                coste_linea = Decimal('0.00')
                if linea.tipo == 'Consumible':
                    tipo_obj = tipos_consumible_dict.get(linea.descripcion.upper())
                    if tipo_obj and tipo_obj.id in ultimas_compras_por_tipo:
                         compra_relevante = ultimas_compras_por_tipo[tipo_obj.id]
                         # Asegurarse que la compra es anterior o igual a la fecha de factura
                         if compra_relevante.fecha_compra <= factura.fecha_emision:
                             coste_linea = (compra_relevante.coste_por_unidad or Decimal('0.00')) * linea.cantidad
                             coste_consumibles_factura += coste_linea # Acumular coste consumible
                # Para Mano de Obra, coste directo es 0
                ganancia_servicios += (linea.total_linea - coste_linea) # Ganancia = PVP - Coste (0 para MO)

        # Ganancia bruta del trabajo = Base cobrada (sin IVA) - Costes directos (piezas/externos + consumibles)
        coste_total_directo = coste_piezas_externos_factura + coste_consumibles_factura

        # Calcular ganancia basada en si es factura (usar subtotal) o recibo (usar total_final)
        base_cobrada = factura.subtotal if factura.es_factura else factura.total_final
        ganancia_total_orden = base_cobrada - coste_total_directo


        ganancia_trabajos += ganancia_total_orden
        reporte.append({'orden': orden, 'factura': factura, 'ganancia_total': ganancia_total_orden})

    ganancia_grua_total = ingresos_grua.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    ganancia_otras_total = otras_ganancias.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia_general = ganancia_trabajos + ganancia_grua_total + ganancia_otras_total

    ganancias_directas_desglose = sorted(
        list(ingresos_grua) + list(otras_ganancias),
        key=lambda x: x.fecha,
        reverse=True
    )

    context = {
        'reporte': reporte,
        'ganancia_trabajos': ganancia_trabajos,
        'ganancia_grua': ganancia_grua_total,
        'ganancia_otras': ganancia_otras_total,
        'ganancias_directas_desglose': ganancias_directas_desglose,
        'total_ganancia_general': total_ganancia_general,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/informe_rentabilidad.html', context)


# --- DETALLE GANANCIA ORDEN (MODIFICADO PARA AGRUPAR) ---
def detalle_ganancia_orden(request, orden_id):
    orden = get_object_or_404(OrdenDeReparacion.objects.select_related('vehiculo', 'cliente'), id=orden_id)
    try:
        factura = Factura.objects.prefetch_related('lineas', 'orden__ingreso_set').get(orden=orden)
    except Factura.DoesNotExist:
         return redirect('detalle_orden', orden_id=orden.id)

    # --- Lógica de agrupación y cálculo de ganancia (sin cambios) ---
    # ... (código de cálculo de desglose omitido para brevedad)...
    desglose_agrupado = {}
    gastos_usados_ids = set()
    gastos_asociados = Gasto.objects.filter(
        vehiculo=orden.vehiculo,
        categoria__in=['Repuestos', 'Otros']
    ).order_by('id')
    compras_consumibles = CompraConsumible.objects.filter(
        fecha_compra__lte=factura.fecha_emision
    ).order_by('tipo_id', '-fecha_compra')
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
        desglose_agrupado.setdefault(key, {
            'descripcion': f"{linea.get_tipo_display()}: {linea.descripcion}",
            'coste': Decimal('0.00'),
            'pvp': Decimal('0.00')
        })
        desglose_agrupado[key]['pvp'] += pvp_linea
        # ... (cálculo de coste_linea) ...
        if linea.tipo in ['Repuesto', 'Externo']:
            categoria_gasto = 'Repuestos' if linea.tipo == 'Repuesto' else 'Otros'
            gasto_encontrado = None
            for gasto in gastos_asociados:
                if (gasto.id not in gastos_usados_ids and
                        gasto.categoria == categoria_gasto and
                        gasto.descripcion.strip().upper() == descripcion_limpia):
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
            # ... (lógica para añadir costes no facturados) ...
             descripcion_limpia = gasto.descripcion.strip().upper()
             tipo_gasto_map = {'Repuestos': 'Repuesto', 'Otros': 'Externo'}
             tipo_para_key = tipo_gasto_map.get(gasto.categoria, 'Externo')
             key = (tipo_para_key, descripcion_limpia)
             desglose_agrupado.setdefault(key, {
                 'descripcion': f"{gasto.get_categoria_display()}: {gasto.descripcion}",
                 'coste': Decimal('0.00'), 'pvp': Decimal('0.00')
             })
             desglose_agrupado[key]['coste'] += gasto.importe or Decimal('0.00')

    desglose_final_list = []
    ganancia_total_calculada = Decimal('0.00')
    for item_agrupado in desglose_agrupado.values():
        ganancia = item_agrupado['pvp'] - item_agrupado['coste']
        item_agrupado['ganancia'] = ganancia
        desglose_final_list.append(item_agrupado)
        ganancia_total_calculada += ganancia
    desglose_final_list.sort(key=lambda x: x['descripcion'])
    # --- FIN Lógica de agrupación ---

    # --- Calcular Abonos y Saldo del Cliente ---
    abonos = sum(ing.importe for ing in factura.orden.ingreso_set.all()) if hasattr(factura.orden, 'ingreso_set') else Decimal('0.00')
    saldo_cliente = abonos - factura.total_final
    saldo_cliente_abs = abs(saldo_cliente) # <-- NUEVO: Calculamos valor absoluto

    context = {
        'orden': orden,
        'factura': factura,
        'desglose': desglose_final_list,
        'ganancia_total': ganancia_total_calculada,
        'abonos_totales': abonos,
        'saldo_cliente': saldo_cliente,
        'saldo_cliente_abs': saldo_cliente_abs, # <-- NUEVO: Pasar valor absoluto al contexto
    }
    return render(request, 'taller/detalle_ganancia_orden.html', context)


# --- INFORME GASTOS ---
def informe_gastos(request):
    gastos_qs = Gasto.objects.select_related('empleado', 'vehiculo') # Optimizar
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

    if ano_seleccionado:
        try: gastos_qs = gastos_qs.filter(fecha__year=int(ano_seleccionado))
        except (ValueError, TypeError): ano_seleccionado = None
    if mes_seleccionado:
        try:
            mes = int(mes_seleccionado)
            if 1 <= mes <= 12: gastos_qs = gastos_qs.filter(fecha__month=mes)
            else: mes_seleccionado = None
        except (ValueError, TypeError): mes_seleccionado = None

    # Totales por categoría (sobre queryset filtrado)
    totales_por_categoria_query = gastos_qs.values('categoria').annotate(total=Sum('importe')).order_by('categoria')
    categoria_display_map = dict(Gasto.CATEGORIA_CHOICES)
    resumen_categorias = {}
    for item in totales_por_categoria_query:
         clave_interna = item['categoria']
         nombre_legible = categoria_display_map.get(clave_interna, clave_interna)
         # Asegurarse que el total no es None
         total_categoria = item['total'] or Decimal('0.00')
         resumen_categorias[clave_interna] = {'display_name': nombre_legible, 'total': total_categoria}


    # Desglose de Sueldos (sobre queryset filtrado)
    desglose_sueldos_query = gastos_qs.filter(categoria='Sueldos', empleado__isnull=False).values('empleado__nombre').annotate(total=Sum('importe')).order_by('empleado__nombre')
    desglose_sueldos = {item['empleado__nombre']: item['total'] or Decimal('0.00') for item in desglose_sueldos_query if item['empleado__nombre']}

    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None
    mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None

    context = {
        'totales_por_categoria': resumen_categorias, 'desglose_sueldos': desglose_sueldos,
        'anos_disponibles': anos_disponibles, 'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int,
        'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/informe_gastos.html', context)


# --- INFORME GASTOS DESGLOSE ---
def informe_gastos_desglose(request, categoria, empleado_nombre=None):
    gastos_qs = Gasto.objects.select_related('vehiculo__cliente', 'empleado') # Optimizar relaciones
    categoria_map = dict(Gasto.CATEGORIA_CHOICES)
    categoria_interna = categoria # Viene de URL

    if empleado_nombre:
        empleado_nombre_limpio = empleado_nombre.replace('_', ' ')
        gastos_qs = gastos_qs.filter(categoria='Sueldos', empleado__nombre__iexact=empleado_nombre_limpio)
        titulo = f"Desglose de Sueldos: {empleado_nombre_limpio.upper()}"
    else:
        gastos_qs = gastos_qs.filter(categoria__iexact=categoria_interna)
        titulo_categoria = categoria_map.get(categoria_interna, categoria_interna)
        titulo = f"Desglose de Gastos: {titulo_categoria}"

    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
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
    gastos_desglose = gastos_qs.order_by('-fecha', '-id') # Orden secundario

    context = {
        'titulo': titulo, 'gastos_desglose': gastos_desglose, 'total_desglose': total_desglose,
        'ano_seleccionado': ano_seleccionado, 'mes_seleccionado': mes_seleccionado,
        'categoria_original_url': categoria
    }
    return render(request, 'taller/informe_gastos_desglose.html', context)


# --- INFORME INGRESOS ---
def informe_ingresos(request):
    ingresos_qs = Ingreso.objects.all()
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

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
    resumen_categorias = {
        item['categoria']: {'display_name': categoria_display_map.get(item['categoria'], item['categoria']), 'total': item['total'] or Decimal('0.00')}
        for item in totales_por_categoria_query
    }

    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None
    mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None

    context = {
        'totales_por_categoria': resumen_categorias, 'anos_disponibles': anos_disponibles,
        'ano_seleccionado': ano_sel_int, 'mes_seleccionado': mes_sel_int,
        'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/informe_ingresos.html', context)

# --- INFORME INGRESOS DESGLOSE ---
def informe_ingresos_desglose(request, categoria):
    ingresos_qs = Ingreso.objects.select_related('orden__vehiculo')
    categoria_display_map = dict(Ingreso.CATEGORIA_CHOICES)
    categoria_interna = categoria # Viene de URL
    titulo = f"Desglose de Ingresos: {categoria_display_map.get(categoria_interna, categoria_interna)}"
    ingresos_qs = ingresos_qs.filter(categoria__iexact=categoria_interna)

    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')
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

    context = {
        'titulo': titulo, 'ingresos_desglose': ingresos_desglose, 'total_desglose': total_desglose,
        'ano_seleccionado': ano_seleccionado, 'mes_seleccionado': mes_seleccionado,
        'categoria_original_url': categoria
    }
    return render(request, 'taller/informe_ingresos_desglose.html', context)


# --- VISTA CONTABILIDAD ---
def contabilidad(request):
    periodo = request.GET.get('periodo', 'mes')
    hoy = timezone.now().date()
    ingresos_qs = Ingreso.objects.all()
    gastos_qs = Gasto.objects.all()

    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        ingresos_qs = ingresos_qs.filter(fecha__gte=inicio_semana)
        gastos_qs = gastos_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        ingresos_qs = ingresos_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        gastos_qs = gastos_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)

    total_ingresado = ingresos_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastado = gastos_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_ganancia = total_ingresado - total_gastado # Beneficio Bruto

    context = {
        'total_ingresado': total_ingresado, 'total_gastado': total_gastado,
        'total_ganancia': total_ganancia, 'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/contabilidad.html', context)


# --- VISTA CUENTAS POR COBRAR ---
def cuentas_por_cobrar(request):
    anos_y_meses_data = get_anos_y_meses_con_datos()
    anos_disponibles = sorted(anos_y_meses_data.keys(), reverse=True)
    ano_seleccionado = request.GET.get('ano')
    mes_seleccionado = request.GET.get('mes')

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

    facturas_pendientes = []
    total_pendiente = Decimal('0.00')

    for factura in facturas_qs.order_by('fecha_emision', 'id'):
        # Usar los ingresos precargados
        abonos = sum(ing.importe for ing in factura.orden.ingreso_set.all()) if hasattr(factura.orden, 'ingreso_set') and factura.orden.ingreso_set.exists() else Decimal('0.00')
        pendiente = factura.total_final - abonos
        if pendiente > Decimal('0.01'):
            facturas_pendientes.append({
                'factura': factura, 'orden': factura.orden, 'cliente': factura.orden.cliente,
                'vehiculo': factura.orden.vehiculo, 'pendiente': pendiente,
            })
            total_pendiente += pendiente

    ano_sel_int = int(ano_seleccionado) if ano_seleccionado else None
    mes_sel_int = int(mes_seleccionado) if mes_seleccionado else None

    context = {
        'facturas_pendientes': facturas_pendientes, 'total_pendiente': total_pendiente,
        'anos_disponibles': anos_disponibles, 'ano_seleccionado': ano_sel_int,
        'mes_seleccionado': mes_sel_int, 'meses_del_ano': range(1, 13)
    }
    return render(request, 'taller/cuentas_por_cobrar.html', context)


# --- VISTA INFORME TARJETA ---
def informe_tarjeta(request):
    periodo = request.GET.get('periodo', 'mes')
    hoy = timezone.now().date()
    ingresos_tpv_qs = Ingreso.objects.filter(es_tpv=True)
    gastos_tarjeta_qs = Gasto.objects.filter(pagado_con_tarjeta=True)

    if periodo == 'semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        ingresos_tpv_qs = ingresos_tpv_qs.filter(fecha__gte=inicio_semana)
        gastos_tarjeta_qs = gastos_tarjeta_qs.filter(fecha__gte=inicio_semana)
    elif periodo == 'mes':
        ingresos_tpv_qs = ingresos_tpv_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)
        gastos_tarjeta_qs = gastos_tarjeta_qs.filter(fecha__month=hoy.month, fecha__year=hoy.year)

    total_ingresos_tpv = ingresos_tpv_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    total_gastos_tarjeta = gastos_tarjeta_qs.aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance_tarjeta = total_ingresos_tpv - total_gastos_tarjeta

    movimientos_tarjeta = sorted(
        list(ingresos_tpv_qs) + list(gastos_tarjeta_qs),
        key=lambda mov: (mov.fecha, -mov.id if hasattr(mov, 'id') else 0),
        reverse=True
    )

    context = {
        'total_ingresos_tpv': total_ingresos_tpv, 'total_gastos_tarjeta': total_gastos_tarjeta,
        'balance_tarjeta': balance_tarjeta, 'movimientos_tarjeta': movimientos_tarjeta,
        'periodo_seleccionado': periodo,
    }
    return render(request, 'taller/informe_tarjeta.html', context)

# --- VISTA VER PRESUPUESTO PDF ---
def ver_presupuesto_pdf(request, presupuesto_id):
    # Optimizar la carga de datos relacionados
    presupuesto = get_object_or_404(
        Presupuesto.objects.select_related('cliente', 'vehiculo')
                           .prefetch_related('lineas'), # Cargar líneas
        id=presupuesto_id
    )
    lineas = presupuesto.lineas.all() # Usar líneas precargadas

    context = {
        'presupuesto': presupuesto,
        'lineas': lineas,
        'STATIC_URL': settings.STATIC_URL,
        'logo_path': os.path.join(settings.BASE_DIR, 'taller', 'static', 'taller', 'images', 'logo.jpg') # Aunque no se use, el callback lo necesita
    }
    template_path = 'taller/plantilla_presupuesto.html'
    template = get_template(template_path)
    html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    # Definir nombre de archivo
    matricula_filename = presupuesto.vehiculo.matricula if presupuesto.vehiculo else presupuesto.matricula_nueva if presupuesto.matricula_nueva else 'SIN_VEHICULO'
    # Limpiar nombre de cliente para nombre de archivo (más robusto)
    cliente_filename = "".join(c if c.isalnum() else "_" for c in presupuesto.cliente.nombre)
    nombre_archivo = f"presupuesto_{presupuesto.id}_{cliente_filename}_{matricula_filename}.pdf"
    response['Content-Disposition'] = f'inline; filename="{nombre_archivo}"' # Usar inline para previsualizar

    # Callback para encontrar recursos estáticos (igual que en ver_factura_pdf)
    def link_callback(uri, rel):
        logo_uri_abs = context.get('logo_path')
        if logo_uri_abs: logo_uri_abs = logo_uri_abs.replace("\\", "/") # Normalizar
        if uri == logo_uri_abs: return logo_uri_abs

        if uri.startswith(settings.STATIC_URL):
            path = uri.replace(settings.STATIC_URL, "", 1)
            # Buscar en STATICFILES_DIRS
            for static_dir in settings.STATICFILES_DIRS:
                file_path = os.path.join(static_dir, path)
                if os.path.exists(file_path): return file_path
            # Fallback a STATIC_ROOT
            if hasattr(settings, 'STATIC_ROOT') and settings.STATIC_ROOT:
                 file_path = os.path.join(settings.STATIC_ROOT, path)
                 if os.path.exists(file_path): return file_path

        if uri.startswith("http://") or uri.startswith("https://"): return uri
        print(f"WARN: Could not resolve URI '{uri}' in PDF generation.")
        return None

    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    if pisa_status.err: return HttpResponse('Error al generar PDF: <pre>' + html + '</pre>')
    return response