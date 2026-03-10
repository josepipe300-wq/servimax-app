# taller/ai_tools.py
from django.urls import reverse
from django.core.signing import Signer
from django.utils import timezone
from django.db.models import Sum
from urllib.parse import quote
from decimal import Decimal
from collections import Counter
from .models import (
    Vehiculo, OrdenDeReparacion, Factura, Presupuesto, LineaPresupuesto,
    TipoConsumible, Ingreso, Gasto, CompraConsumible, 
    UsoConsumible, AjusteStockConsumible, NotaTablon, Cliente
)

def obtener_factura_por_matricula(matricula, enviar_whatsapp=False):
    """Busca la última factura de un coche probando con y sin espacios."""
    matricula_upper = matricula.upper().strip()
    matricula_limpia = matricula_upper.replace(" ", "")
    
    vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_limpia).first()
    if not vehiculo:
        vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_upper).first()
    
    if not vehiculo:
        return {"status": "error", "mensaje": f"No encuentro ningún coche con la matrícula {matricula_upper}."}
        
    orden = OrdenDeReparacion.objects.filter(vehiculo=vehiculo).order_by('-id').first()
    if not orden:
        return {"status": "error", "mensaje": f"El {vehiculo.marca} no tiene ninguna orden registrada."}
        
    try:
        factura = orden.factura
        
        if not enviar_whatsapp:
            url_pdf = reverse('ver_factura_pdf', args=[factura.id])
            return {
                "status": "success", 
                "mensaje": f"Aquí tienes la factura del {vehiculo.marca} ({matricula_upper}). Abriendo en pantalla...",
                "accion_pantalla": "abrir_pdf",
                "url": url_pdf
            }
            
        else:
            cliente = orden.cliente
            telefono = cliente.telefono
            if not telefono:
                return {"status": "error", "mensaje": f"El cliente {cliente.nombre} no tiene número de teléfono guardado para enviarle el WhatsApp."}
                
            telefono_limpio = "".join(filter(str.isdigit, telefono))
            if not telefono_limpio.startswith('34') and len(telefono_limpio) == 9:
                telefono_limpio = '34' + telefono_limpio
                
            signer = Signer()
            signed_id = signer.sign(factura.id)
            url_path = reverse('ver_factura_publica', args=[signed_id])
            
            dominio_taller = "http://127.0.0.1:8000" 
            enlace_magico = f"{dominio_taller}{url_path}"
                
            tipo_doc = "factura" if factura.es_factura else "recibo"
            mensaje = f"Hola {cliente.nombre}, somos de ServiMax. Aquí tienes el enlace para descargar tu {tipo_doc} del taller correspondiente a tu {vehiculo.marca}:\n\n{enlace_magico}\n\n¡Gracias por confiar en nosotros!"
            
            mensaje_encoded = quote(mensaje)
            whatsapp_url = f"https://wa.me/{telefono_limpio}?text={mensaje_encoded}"
            
            return {
                "status": "success",
                "mensaje": f"Preparando el WhatsApp para enviar la {tipo_doc} a {cliente.nombre}...",
                "accion_pantalla": "abrir_pdf", 
                "url": whatsapp_url
            }
            
    except Factura.DoesNotExist:
        return {"status": "error", "mensaje": f"El {vehiculo.marca} tiene una orden abierta, pero aún no se le ha generado la factura."}

def enviar_presupuesto_whatsapp(id_presupuesto):
    try:
        presupuesto = Presupuesto.objects.get(id=id_presupuesto)
        telefono = presupuesto.cliente.telefono
        
        if not telefono:
            return {"status": "error", "mensaje": f"El cliente {presupuesto.cliente.nombre} no tiene número de teléfono guardado."}
            
        telefono_limpio = "".join(filter(str.isdigit, telefono))
        if not telefono_limpio.startswith('34') and len(telefono_limpio) == 9:
            telefono_limpio = '34' + telefono_limpio
            
        signer = Signer()
        signed_id = signer.sign(presupuesto.id)
        url_path = reverse('ver_presupuesto_publico', args=[signed_id])
        
        dominio_taller = "http://127.0.0.1:8000" 
        enlace_magico = f"{dominio_taller}{url_path}"
            
        vehiculo_texto = f"su {presupuesto.vehiculo.marca}" if presupuesto.vehiculo else "su vehículo"
        mensaje = f"Hola {presupuesto.cliente.nombre}, somos de ServiMax. Aquí tienes el presupuesto de {vehiculo_texto}. Puedes verlo y descargarlo directamente en este enlace: {enlace_magico} Díganos si le parece bien para proceder."
        
        mensaje_encoded = quote(mensaje)
        whatsapp_url = f"https://wa.me/{telefono_limpio}?text={mensaje_encoded}"
        
        return {
            "status": "success",
            "mensaje": f"Preparando el WhatsApp para {presupuesto.cliente.nombre}. Enviando enlace mágico...",
            "accion_pantalla": "abrir_pdf", 
            "url": whatsapp_url
        }
    except Presupuesto.DoesNotExist:
        return {"status": "error", "mensaje": f"No encuentro ningún presupuesto con el número {id_presupuesto}."}

def consultar_estado_vehiculo(matricula):
    matricula_upper = matricula.upper().strip()
    matricula_limpia = matricula_upper.replace(" ", "")
    
    vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_limpia).first()
    if not vehiculo:
        vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_upper).first()
    
    if not vehiculo:
        return {"status": "error", "mensaje": f"No encuentro la matrícula {matricula_upper}."}
        
    orden = OrdenDeReparacion.objects.filter(vehiculo=vehiculo).exclude(estado='Entregado').first()
    if orden:
        return {"status": "success", "mensaje": f"El {vehiculo.marca} está actualmente en estado: {orden.get_estado_display()}."}
    else:
        return {"status": "success", "mensaje": f"El {vehiculo.marca} no está en el taller ahora mismo. Su última reparación ya fue entregada."}

def consultar_stock(articulo):
    articulo_limpio = articulo.strip().lower()
    consumible = TipoConsumible.objects.filter(nombre__icontains=articulo_limpio).first()
    
    if consumible:
        total_comprado = CompraConsumible.objects.filter(tipo=consumible).aggregate(total=Sum('cantidad'))['total'] or Decimal('0.00')
        total_usado = UsoConsumible.objects.filter(tipo=consumible).aggregate(total=Sum('cantidad_usada'))['total'] or Decimal('0.00')
        total_ajustado = AjusteStockConsumible.objects.filter(tipo=consumible).aggregate(total=Sum('cantidad_ajustada'))['total'] or Decimal('0.00')
        
        stock_real = total_comprado - total_usado + total_ajustado
        minimo = consumible.nivel_minimo_stock or Decimal('0.00')

        if stock_real <= minimo:
            return {"status": "success", "mensaje": f"Nos quedan solo {stock_real} unidades de {consumible.nombre}. Deberíamos pedir más porque estamos en el nivel mínimo."}
        else:
            return {"status": "success", "mensaje": f"Sí, tenemos {stock_real} unidades de {consumible.nombre} en el taller."}
    else:
        return {"status": "error", "mensaje": f"He mirado en el almacén y no encuentro nada registrado como {articulo}."}

def resumen_caja_hoy():
    hoy = timezone.now().date()
    ingresos = Ingreso.objects.filter(fecha=hoy).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    gastos = Gasto.objects.filter(fecha=hoy).aggregate(total=Sum('importe'))['total'] or Decimal('0.00')
    balance = ingresos - gastos
    
    mensaje = f"Hoy han entrado {ingresos} euros y hemos gastado {gastos} euros. "
    if balance > 0:
        mensaje += f"Llevamos un beneficio limpio de {balance} euros."
    elif balance < 0:
        mensaje += f"De momento hoy vamos en negativo con {-balance} euros."
    else:
        mensaje += "Estamos a cero, la caja está equilibrada."
        
    return {"status": "success", "mensaje": mensaje}

def clientes_deudores():
    facturas = Factura.objects.select_related('orden__cliente', 'orden__vehiculo').prefetch_related('orden__ingreso_set')
    total_deuda = Decimal('0.00')
    facturas_pendientes = 0
    
    for f in facturas:
        abonos = sum(ing.importe for ing in f.orden.ingreso_set.all()) if f.orden.ingreso_set.exists() else Decimal('0.00')
        pendiente = f.total_final - abonos
        if pendiente > Decimal('0.01'):
            total_deuda += pendiente
            facturas_pendientes += 1
            
    if facturas_pendientes == 0:
        return {"status": "success", "mensaje": "¡Excelentes noticias! Ningún cliente nos debe dinero ahora mismo. Todas las cuentas están al día."}
    
    url_deudores = reverse('cuentas_por_cobrar')
    return {
        "status": "success", 
        "mensaje": f"Atención: Tenemos {facturas_pendientes} facturas pendientes de cobro. Hay un total de {total_deuda} euros en la calle. Te abro la pantalla de morosos para que lo revises.",
        "accion_pantalla": "abrir_pdf",
        "url": url_deudores
    }

def coches_en_taller():
    ordenes = OrdenDeReparacion.objects.exclude(estado='Entregado')
    total = ordenes.count()
    
    if total == 0:
        return {"status": "success", "mensaje": "El taller está completamente vacío ahora mismo. No hay órdenes activas."}
        
    estados = [o.estado for o in ordenes]
    conteo = Counter(estados)
    desglose = ", ".join([f"{count} en '{estado}'" for estado, count in conteo.items()])
    
    return {
        "status": "success", 
        "mensaje": f"Tenemos {total} vehículos en el taller en este momento. El desglose es: {desglose}."
    }

def historial_vehiculo(matricula):
    matricula_upper = matricula.upper().strip()
    matricula_limpia = matricula_upper.replace(" ", "")
    
    vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_limpia).first()
    if not vehiculo:
        vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_upper).first()
    
    if not vehiculo:
        return {"status": "error", "mensaje": f"No tenemos registrado ningún vehículo con la matrícula {matricula_upper} en nuestra base de datos."}
        
    ordenes_pasadas = OrdenDeReparacion.objects.filter(vehiculo=vehiculo, estado='Entregado').order_by('-id')
    visitas = ordenes_pasadas.count()
    
    if visitas == 0:
        return {"status": "success", "mensaje": f"El {vehiculo.marca} ({matricula_upper}) está registrado, pero todavía no le hemos terminado ninguna reparación histórica."}
        
    ultima_orden = ordenes_pasadas.first()
    mensaje = f"El {vehiculo.marca} con matrícula {matricula_upper} ha venido {visitas} veces al taller. "
    mensaje += f"Su última reparación fue por: '{ultima_orden.problema}'. "
    
    try:
        if ultima_orden.factura:
            mensaje += f"La factura de esa última visita fue de {ultima_orden.factura.total_final} euros."
    except Factura.DoesNotExist:
        pass
        
    return {"status": "success", "mensaje": mensaje}

def tareas_pendientes():
    notas = NotaTablon.objects.filter(completada=False).order_by('-fecha_creacion')
    total = notas.count()
    
    if total == 0:
        return {"status": "success", "mensaje": "¡Genial! El tablón está limpio. No hay tareas ni avisos pendientes."}
        
    mensajes = [f"- {nota.texto} (por {nota.autor.username.title()})" for nota in notas[:5]]
    texto_lista = "\n".join(mensajes)
    
    if total > 5:
        texto_lista += f"\n...y {total - 5} tareas más."
        
    return {"status": "success", "mensaje": f"Tienes {total} avisos pendientes en el tablón:\n\n{texto_lista}"}

def contacto_cliente(matricula):
    matricula_upper = matricula.upper().strip()
    matricula_limpia = matricula_upper.replace(" ", "")
    
    vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_limpia).first()
    if not vehiculo:
        vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_upper).first()
    
    if not vehiculo:
        return {"status": "error", "mensaje": f"No encuentro ningún coche con la matrícula {matricula_upper}."}
        
    cliente = vehiculo.cliente
    if not cliente.telefono:
        return {"status": "success", "mensaje": f"El dueño del {vehiculo.marca} es {cliente.nombre}, pero no nos dejó ningún teléfono de contacto."}
        
    return {"status": "success", "mensaje": f"El dueño del {vehiculo.marca} ({matricula_upper}) es {cliente.nombre}. Su teléfono es: {cliente.telefono}."}

def coches_listos_para_entregar():
    ordenes = OrdenDeReparacion.objects.filter(estado='Listo para Recoger')
    total = ordenes.count()
    
    if total == 0:
        return {"status": "success", "mensaje": "Ahora mismo no hay ningún coche terminado esperando a ser recogido."}
        
    lista_coches = [f"🚗 {o.vehiculo.marca} ({o.vehiculo.matricula})" for o in ordenes]
    texto_lista = "\n".join(lista_coches)
    
    return {"status": "success", "mensaje": f"Tenemos {total} coches listos para entregar y facturar:\n\n{texto_lista}"}

def tiempo_en_taller(id_orden):
    try:
        orden = OrdenDeReparacion.objects.get(id=id_orden)
    except OrdenDeReparacion.DoesNotExist:
        return {"status": "error", "mensaje": f"No encuentro ninguna orden de reparación con el número #{id_orden}."}
        
    vehiculo = orden.vehiculo
    fecha_ingreso = orden.fecha_entrada.date()
    hoy = timezone.now().date()
    dias = (hoy - fecha_ingreso).days
    
    if orden.estado == 'Entregado':
        return {
            "status": "success", 
            "mensaje": f"La Orden #{orden.id} del {vehiculo.marca} ({vehiculo.matricula}) ya fue entregada. Todo el proceso duró {dias} días en total. ¿Quieres que te desglose el tiempo por fases?"
        }
    else:
        if dias == 0:
            return {"status": "success", "mensaje": f"La Orden #{orden.id} del {vehiculo.marca} entró hoy y está en la fase: '{orden.get_estado_display()}'."}
        else:
            return {"status": "success", "mensaje": f"La Orden #{orden.id} del {vehiculo.marca} lleva {dias} días en el taller. Está en la fase: '{orden.get_estado_display()}'."}

def desglose_fases_vehiculo(id_orden):
    try:
        orden = OrdenDeReparacion.objects.get(id=id_orden)
    except OrdenDeReparacion.DoesNotExist:
        return {"status": "error", "mensaje": f"No encuentro la orden #{id_orden}."}
        
    vehiculo = orden.vehiculo
    historial = orden.historial_estados.all().order_by('id')
    
    if not historial.exists():
        return {"status": "success", "mensaje": f"Lo siento, la Orden #{orden.id} no tiene un registro guardado paso a paso de sus fases."}
        
    lineas = []
    fechas = list(historial)
    
    def obtener_fecha(objeto):
        for campo in objeto._meta.get_fields():
            if campo.get_internal_type() in ['DateTimeField', 'DateField']:
                return getattr(objeto, campo.name)
        return None

    for i in range(len(fechas)):
        estado_fase = fechas[i].estado
        fecha_inicio = obtener_fecha(fechas[i])
        
        if not fecha_inicio:
            lineas.append(f"- {estado_fase}: (El sistema no guardó la hora en este paso)")
            continue
            
        if i < len(fechas) - 1:
            fecha_fin = obtener_fecha(fechas[i+1])
            if fecha_fin:
                diferencia = fecha_fin - fecha_inicio
                dias = diferencia.days
                segundos = diferencia.seconds
                horas = segundos // 3600
                minutos = (segundos % 3600) // 60
                
                if dias > 0:
                    tiempo_str = f"{dias} días"
                elif horas > 0:
                    tiempo_str = f"{horas} horas"
                else:
                    tiempo_str = f"{minutos} minutos"
                    
                lineas.append(f"- {estado_fase}: Estuvo aquí {tiempo_str}")
            else:
                lineas.append(f"- {estado_fase}: (Error al leer fin)")
        else:
            if orden.estado != 'Entregado':
                diferencia = timezone.now() - fecha_inicio
                dias = diferencia.days
                if dias > 0:
                    lineas.append(f"- {estado_fase} (Actual): Lleva {dias} días")
                else:
                    lineas.append(f"- {estado_fase} (Actual): Entró hoy mismo")
            else:
                lineas.append(f"- {estado_fase}: Fase finalizada con éxito.")
                
    texto = "\n".join(lineas)
    return {"status": "success", "mensaje": f"Aquí tienes el informe de tiempos paso a paso de la Orden #{orden.id} ({vehiculo.marca}):\n\n{texto}"}

def vehiculos_entregados_reporte():
    ordenes = OrdenDeReparacion.objects.filter(estado='Entregado').order_by('-fecha_entrada')
    
    if not ordenes.exists():
        return {"status": "success", "mensaje": "Todavía no tenemos registros de vehículos entregados."}
        
    reporte = {}
    for o in ordenes:
        if o.fecha_entrada:
            mes = o.fecha_entrada.strftime("%B %Y").capitalize()
            semana = o.fecha_entrada.isocalendar()[1]
            clave = f"📅 {mes} (Semana {semana} del año)"
            
            if clave not in reporte:
                reporte[clave] = []
            reporte[clave].append(f"  - Orden #{o.id}: {o.vehiculo.marca} ({o.vehiculo.matricula})")
            
    texto_final = "Aquí tienes el listado de vehículos entregados agrupado por fechas:\n\n"
    for periodo, lista in reporte.items():
        texto_final += f"{periodo}\n" + "\n".join(lista) + "\n\n"
        
    return {"status": "success", "mensaje": texto_final.strip()}

def coches_atascados():
    hace_una_semana = timezone.now() - timezone.timedelta(days=7)
    ordenes = OrdenDeReparacion.objects.filter(fecha_entrada__lte=hace_una_semana).exclude(estado='Entregado')
    total = ordenes.count()
    
    if total == 0:
        return {"status": "success", "mensaje": "¡Buen ritmo de trabajo! No tenemos ningún coche que lleve más de una semana atascado en el taller."}
        
    lista = [f"🚗 {o.vehiculo.marca} ({o.vehiculo.matricula}): Lleva {(timezone.now().date() - o.fecha_entrada.date()).days} días (Estado: {o.estado})" for o in ordenes]
    texto = "\n".join(lista)
    
    return {"status": "success", "mensaje": f"Atención, tenemos {total} vehículos que llevan más de 7 días aquí dentro:\n\n{texto}"}

def rentabilidad_vehiculo(matricula=None, id_orden=None, solo_orden=False):
    vehiculo = None
    orden_especifica = None
    
    if id_orden:
        try:
            orden_especifica = OrdenDeReparacion.objects.get(id=id_orden)
            vehiculo = orden_especifica.vehiculo
        except OrdenDeReparacion.DoesNotExist:
            return {"status": "error", "mensaje": f"No encuentro ninguna orden con el número #{id_orden}."}
            
    elif matricula:
        matricula_limpia = str(matricula).upper().replace(" ", "")
        for v in Vehiculo.objects.all():
            if v.matricula.upper().replace(" ", "") == matricula_limpia:
                vehiculo = v
                break
        if not vehiculo:
            return {"status": "error", "mensaje": f"No encuentro la matrícula '{matricula}' registrada en el taller."}
    else:
        return {"status": "error", "mensaje": "Necesito una matrícula o un número de orden para poder calcular la rentabilidad."}

    if id_orden and solo_orden:
        try:
            factura = Factura.objects.get(orden=orden_especifica)
            ganancia_orden = factura.total_final
            mensaje = f"La Orden #{orden_especifica.id} del {vehiculo.marca} ({vehiculo.matricula}) nos dejó una ganancia de {ganancia_orden} euros.\n\n¿Quieres que te muestre el historial completo de ganancias de todas las veces que ha venido este vehículo al taller?"
        except Factura.DoesNotExist:
            mensaje = f"La Orden #{orden_especifica.id} del {vehiculo.marca} ({vehiculo.matricula}) no tiene una factura generada todavía (0 euros registrados).\n\n¿Quieres que te muestre el historial completo de ganancias de este vehículo?"
        
        return {"status": "success", "mensaje": mensaje}

    ordenes_vehiculo = OrdenDeReparacion.objects.filter(vehiculo=vehiculo).order_by('fecha_entrada')
    total_gastado = Decimal('0.00')
    lineas_historial = []
    
    for ord_veh in ordenes_vehiculo:
        fecha_str = ord_veh.fecha_entrada.strftime('%d/%m/%Y') if ord_veh.fecha_entrada else "Fecha desconocida"
        try:
            factura = Factura.objects.get(orden=ord_veh)
            ganancia = factura.total_final
            total_gastado += ganancia
            lineas_historial.append(f"  - Orden #{ord_veh.id} ({fecha_str}): {ganancia} €")
        except Factura.DoesNotExist:
            lineas_historial.append(f"  - Orden #{ord_veh.id} ({fecha_str}): (Aún sin facturar)")
            
    if total_gastado == 0:
        return {"status": "success", "mensaje": f"El {vehiculo.marca} ({vehiculo.matricula}) ha venido {ordenes_vehiculo.count()} veces, pero aún no nos ha generado ingresos facturados en ninguna de sus visitas."}
        
    texto_desglose = "\n".join(lineas_historial)
    return {"status": "success", "mensaje": f"Aquí tienes el historial de ganancias del {vehiculo.marca} ({vehiculo.matricula}):\n\n{texto_desglose}\n\n💸 **Ganancia Total Histórica:** {total_gastado} euros."}

def extraer_datos_presupuesto(reparacion, modelo=""):
    if not reparacion:
        return "No se especificó reparación."
        
    ordenes = OrdenDeReparacion.objects.filter(problema__icontains=reparacion, factura__isnull=False).order_by('-id')[:15]
    
    if modelo:
        ordenes_modelo = ordenes.filter(vehiculo__marca__icontains=modelo)
        if ordenes_modelo.exists():
            ordenes = ordenes_modelo
            
    if not ordenes.exists():
        return "NO_HAY_DATOS"
        
    datos = []
    for o in ordenes:
        datos.append(f"- Orden #{o.id} ({o.vehiculo.marca}): Cobrado {o.factura.total_final}€. Problema escrito por el mecánico: '{o.problema}'")
        
    return "\n".join(datos)

def crear_borrador_presupuesto(matricula=None, nombre_cliente=None, descripcion=None, precio=None):
    if not descripcion or not precio:
        return {"status": "error", "mensaje": "Para crear un borrador necesito saber al menos de qué es la reparación y un precio estimado."}

    cliente = None
    vehiculo = None

    if matricula:
        matricula_limpia = str(matricula).upper().replace(" ", "")
        vehiculo = Vehiculo.objects.filter(matricula__icontains=matricula_limpia).first()
        if vehiculo:
            cliente = vehiculo.cliente

    if not cliente and nombre_cliente:
        # Buscamos si ya existe
        cliente = Cliente.objects.filter(nombre__icontains=nombre_cliente).first()
        
        # --- EL ARREGLO PARA EL TELÉFONO DUPLICADO ---
        if not cliente:
            try:
                # Intentamos crearlo forzando el teléfono a "None" (Vacío real) 
                # para que la base de datos no lo cuente como un "texto vacío duplicado"
                cliente = Cliente.objects.create(
                    nombre=nombre_cliente.title(),
                    telefono=None 
                )
            except Exception:
                # PLAN B INFALIBLE: Si la base de datos sigue quejándose, 
                # le generamos un teléfono temporal falso y único para que te deje trabajar.
                import time
                cliente = Cliente.objects.create(
                    nombre=nombre_cliente.title(),
                    telefono=f"FALTA-{int(time.time())}"[-12:]
                )
                
    if not cliente:
        return {"status": "error", "mensaje": "No he entendido bien el nombre del cliente ni la matrícula para poder crear el borrador."}
        
    try:
        precio_total = Decimal(str(precio).replace(',', '.'))
    except:
        return {"status": "error", "mensaje": "El precio que me has dado no es un número válido."}
        
    subtotal = (precio_total / Decimal('1.21')).quantize(Decimal('0.01'))
    iva = precio_total - subtotal
    
    try:
        presupuesto = Presupuesto.objects.create(
            cliente=cliente,
            vehiculo=vehiculo, 
            problema_o_trabajo=f"[BORRADOR IA] - {descripcion}".upper(),
            estado='Pendiente',
            aplicar_iva=True,
            subtotal=subtotal,
            iva=iva,
            total_estimado=precio_total
        )
        
        LineaPresupuesto.objects.create(
            presupuesto=presupuesto,
            tipo='Mano de Obra',
            descripcion=descripcion.upper(),
            cantidad=Decimal('1.00'),
            precio_unitario_estimado=subtotal
        )
        
        try:
            url_edicion = reverse('editar_presupuesto', args=[presupuesto.id])
        except Exception:
            url_edicion = f"/admin/taller/presupuesto/{presupuesto.id}/change/"
            
        texto_extra = f" para su {vehiculo.marca}" if vehiculo else " (sin vehículo asignado todavía)"
        
        return {
            "status": "success",
            "mensaje": f"¡Borrador creado con éxito! He generado el Presupuesto #{presupuesto.id} a nombre de {cliente.nombre}{texto_extra} por un total de {precio_total}€. Te abro la pestaña para que lo termines.",
            "accion_pantalla": "abrir_pdf", 
            "url": url_edicion
        }
    except Exception as e:
        return {"status": "error", "mensaje": f"No he podido guardarlo. Es posible que tu base de datos obligue estrictamente a que todo presupuesto tenga un coche. Error técnico: {str(e)}"}

def crear_nota_tablon(texto, usuario):
    if not texto:
        return {"status": "error", "mensaje": "No me ha quedado claro qué es exactamente lo que quieres que apunte en el tablón."}
    
    if not usuario or not usuario.is_authenticated:
        return {"status": "error", "mensaje": "No sé quién está conectado ahora mismo, no puedo firmar la nota en el tablón."}
        
    nota = NotaTablon.objects.create(
        autor=usuario,
        texto=texto.capitalize()
    )
    
    return {
        "status": "success", 
        "mensaje": f"✅ Listo. He apuntado esto en el tablón a tu nombre:\n\n📌 *'{nota.texto}'*"
    }

def clientes_para_revision(reparacion="aceite"):
    """Busca clientes para revisión, genera enlace a la orden en la app y a WhatsApp."""
    if not reparacion:
        reparacion = "aceite"
        
    hace_11_meses = timezone.now() - timezone.timedelta(days=330)
    hace_13_meses = timezone.now() - timezone.timedelta(days=395)
    
    ordenes = OrdenDeReparacion.objects.filter(
        fecha_entrada__range=[hace_13_meses, hace_11_meses],
        problema__icontains=reparacion
    ).order_by('-fecha_entrada')
    
    if not ordenes.exists():
        return {
            "status": "success", 
            "mensaje": f"He revisado el archivo de hace un año y no encuentro a nadie que viniera por '{reparacion}'.",
            "mensaje_voz": "He revisado el archivo y no tenemos clientes atrasados con esa reparación."
        }
        
    lista_clientes = []
    coches_procesados = set()
    
    for o in ordenes:
        vehiculo = o.vehiculo
        cliente = o.cliente
        
        if vehiculo.id in coches_procesados:
            continue
        coches_procesados.add(vehiculo.id)
        
        telefono = cliente.telefono
        
        try:
            url_orden = reverse('detalle_orden', args=[o.id])
        except Exception:
            url_orden = f"/admin/taller/ordendereparacion/{o.id}/change/"
        
        if telefono:
            telefono_limpio = "".join(filter(str.isdigit, telefono))
            if not telefono_limpio.startswith('34') and len(telefono_limpio) == 9:
                telefono_limpio = '34' + telefono_limpio
                
            mensaje_wa = f"Hola {cliente.nombre}, somos del taller ServiMax. Revisando nuestro historial, hemos visto que hace ya un año que le hicimos el mantenimiento de '{reparacion}' a tu {vehiculo.marca}. Te escribimos para recordarte que seguramente le toque su revisión anual para que siga yendo como la seda. ¿Quieres que te busquemos un hueco esta semana? ¡Un saludo!"
            
            whatsapp_url = f"https://api.whatsapp.com/send?phone={telefono_limpio}&text={quote(mensaje_wa)}"
            
            lista_clientes.append(f"👤 <a href='{url_orden}' target='_blank' style='color: #3b82f6; text-decoration: none;'><b>{cliente.nombre}</b> - {vehiculo.marca} ({vehiculo.matricula})</a><br>📲 <a href='{whatsapp_url}' target='_blank' style='color: #25D366; font-weight: bold; text-decoration: underline;'>Clic aquí para enviar WhatsApp</a>")
        else:
            lista_clientes.append(f"👤 <a href='{url_orden}' target='_blank' style='color: #3b82f6; text-decoration: none;'><b>{cliente.nombre}</b> - {vehiculo.marca} ({vehiculo.matricula})</a><br>❌ (No tiene teléfono guardado)")
            
    texto_final = "<br><br>".join(lista_clientes)
    
    return {
        "status": "success", 
        "mensaje": f"🎯 <b>Campaña Automática: Recordatorio de '{reparacion}'</b><br><br>He rastreado la base de datos de hace justo un año. Estos son los clientes a los que ya les toca volver. Tienes los enlaces preparados para contactarles:<br><br>{texto_final}",
        "mensaje_voz": "Aquí están los enlaces para enviar."
    }

    # Asegúrate de importar Q arriba del todo en tu ai_tools.py si no lo tienes:
# from django.db.models import Q

def buscar_movimiento(termino):
    from django.urls import reverse
    from urllib.parse import quote
    
    if not termino:
        return {"status": "error", "mensaje": "Dime qué gasto o ingreso estás buscando exactamente."}
        
    termino_str = str(termino).strip()
    
    try:
        # Buscamos la URL de tu historial de movimientos
        url_base = reverse('historial_movimientos')
        # Le pegamos la palabra que ha escuchado J.A.R.V.I.S. al final del enlace
        url_filtrada = f"{url_base}?buscar={quote(termino_str)}"
    except Exception:
        return {"status": "error", "mensaje": "No encuentro la ruta del historial de movimientos en tu sistema."}
        
    return {
        "status": "success", 
        "mensaje": f"🔍 <b>Buscando: '{termino_str}'</b><br><br>Te abro el historial de movimientos filtrado directamente en pantalla.",
        "mensaje_voz": "Abriendo el historial filtrado.",
        "accion_pantalla": "abrir_pdf", # Usamos este comando de tu JS para que abra la pestaña
        "url": url_filtrada
    }

def crear_cita_agenda(cliente, motivo, vehiculo, fecha, hora):
    from django.utils import timezone
    from datetime import datetime
    from django.urls import reverse
    from .models import Cita, Presupuesto
    import unicodedata
    
    # MAGIA ANTI-TILDES
    def normalizar_texto(texto):
        if not texto: return ""
        return ''.join(c for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) != 'Mn').lower()
    
    if not cliente or not motivo or not fecha or not hora:
        return {"status": "error", "mensaje": "Me faltan datos, jefe. Necesito el nombre, el motivo, el día y la hora exacta."}
        
    try:
        fecha_str = f"{fecha} {hora}"
        fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
        fecha_aware = timezone.make_aware(fecha_obj)
    except Exception:
        return {"status": "error", "mensaje": "No he entendido bien el día o la hora."}
        
    # BÚSQUEDA DEL PRESUPUESTO A PRUEBA DE TILDES Y MAYÚSCULAS
    presupuestos_pendientes = Presupuesto.objects.filter(estado='Pendiente').order_by('-fecha_creacion')
    cliente_buscado = normalizar_texto(cliente)
    
    presupuesto_asociado = None
    for p in presupuestos_pendientes:
        if p.cliente and cliente_buscado in normalizar_texto(p.cliente.nombre):
            presupuesto_asociado = p
            break
            
    try:
        Cita.objects.create(
            nombre_cliente=cliente.title(),
            vehiculo_info=vehiculo if vehiculo else "Sin especificar",
            motivo=motivo.capitalize(),
            fecha_hora=fecha_aware,
            estado='Pendiente',
            presupuesto=presupuesto_asociado # Lo asociamos mágicamente
        )
        
        try:
            url_agenda = reverse('agenda')
        except Exception:
            url_agenda = "/agenda/"
            
        texto_presupuesto = f"<br>📎 <i>Le he grapado automáticamente el Presupuesto #{presupuesto_asociado.id} que tenía pendiente.</i>" if presupuesto_asociado else ""
            
        return {
            "status": "success",
            "mensaje": f"✅ <b>Cita Guardada:</b><br>👤 {cliente}<br>🔧 {motivo}.<br>🗓️ <b>Día:</b> {fecha_aware.strftime('%d/%m/%Y')} a las {hora}.{texto_presupuesto}<br><br>Abriendo la agenda...",
            "mensaje_voz": f"Cita guardada correctamente para {cliente}. Te abro la agenda.",
            "accion_pantalla": "abrir_pdf", 
            "url": url_agenda
        }
    except Exception as e:
        return {"status": "error", "mensaje": f"Error al guardar: {str(e)}"}

def actualizar_estado_cita(cliente, hora=None, estado="En taller"):
    from .models import Cita
    from django.utils import timezone
    from django.urls import reverse
    import unicodedata
    
    # --- MAGIA ANTI-TILDES ---
    def normalizar_texto(texto):
        if not texto: return ""
        return ''.join(c for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) != 'Mn').lower()

    hoy = timezone.now().date()
    
    # ¡CORRECCIÓN AQUÍ! Ahora busca citas desde HOY hacia el FUTURO (__gte = greater than or equal)
    citas_pendientes = Cita.objects.filter(fecha_hora__date__gte=hoy, estado='Pendiente').order_by('fecha_hora')
    
    cliente_buscado = normalizar_texto(cliente)
    citas_coincidentes = []
    
    # Comparamos quitando tildes
    for c in citas_pendientes:
        if cliente_buscado in normalizar_texto(c.nombre_cliente):
            citas_coincidentes.append(c)
    
    if not citas_coincidentes:
        return {"status": "error", "mensaje": f"No encuentro ninguna cita pendiente para '{cliente}'. Revisa la agenda."}
        
    # Cogemos la cita más próxima que tenga ese cliente
    cita_final = citas_coincidentes[0]
    
    # Si casualmente tiene varias citas futuras, intentamos filtrar por la hora que nos has dicho
    if len(citas_coincidentes) > 1 and hora:
        for c in citas_coincidentes:
            if c.fecha_hora.strftime("%H") == hora.split(":")[0]:
                cita_final = c
                break
                
    # Actualizamos el estado
    cita_final.estado = estado
    cita_final.save()
    
    try:
        url_agenda = reverse('agenda')
    except Exception:
        url_agenda = "/agenda/"
    
    texto_estado = "ya está en el taller 🚗" if estado == "En taller" else "ha sido cancelada ❌"
    fecha_bonita = cita_final.fecha_hora.strftime('%d/%m/%Y')
    
    return {
        "status": "success",
        "mensaje": f"✅ ¡Actualizado! He marcado que la cita de {cita_final.nombre_cliente} (del {fecha_bonita}) {texto_estado}.<br>Refrescando la agenda...",
        "mensaje_voz": f"Perfecto jefe, he marcado que la cita de {cita_final.nombre_cliente} {texto_estado}.",
        "accion_pantalla": "abrir_pdf",
        "url": url_agenda
    }

def modificar_cita_agenda(cliente, fecha=None, hora=None, motivo=None, vehiculo=None, nuevo_nombre=None):
    from .models import Cita
    from django.utils import timezone
    from datetime import datetime
    from django.urls import reverse
    import unicodedata
    
    def normalizar_texto(texto):
        if not texto: return ""
        return ''.join(c for c in unicodedata.normalize('NFD', str(texto)) if unicodedata.category(c) != 'Mn').lower()
        
    hoy = timezone.now().date()
    citas_pendientes = Cita.objects.filter(fecha_hora__date__gte=hoy, estado='Pendiente').order_by('fecha_hora')
    
    cliente_buscado = normalizar_texto(cliente)
    citas_coincidentes = [c for c in citas_pendientes if cliente_buscado in normalizar_texto(c.nombre_cliente)]
    
    if not citas_coincidentes:
        return {"status": "error", "mensaje": f"No encuentro ninguna cita pendiente para '{cliente}'. No puedo modificarla."}
        
    cita = citas_coincidentes[0] 
    modificaciones = []
    
    # --- AQUÍ CAMBIAMOS EL NOMBRE SI HACE FALTA ---
    if nuevo_nombre:
        cita.nombre_cliente = nuevo_nombre.title()
        modificaciones.append(f"el nombre a '{nuevo_nombre.title()}'")
        
    if fecha or hora:
        fecha_str = fecha if fecha else cita.fecha_hora.strftime("%Y-%m-%d")
        hora_str = hora if hora else cita.fecha_hora.strftime("%H:%M")
        try:
            nueva_fecha_str = f"{fecha_str} {hora_str}"
            fecha_obj = datetime.strptime(nueva_fecha_str, "%Y-%m-%d %H:%M")
            cita.fecha_hora = timezone.make_aware(fecha_obj)
            modificaciones.append(f"día/hora a {fecha_str} a las {hora_str}")
        except Exception:
            pass
            
    if motivo:
        cita.motivo = motivo.capitalize()
        modificaciones.append(f"el motivo a '{motivo}'")
        
    if vehiculo:
        cita.vehiculo_info = vehiculo
        modificaciones.append(f"el vehículo a '{vehiculo}'")
        
    cita.save()
    
    try:
        url_agenda = reverse('agenda')
    except Exception:
        url_agenda = "/agenda/"
        
    cambios_texto = " y ".join(modificaciones) if modificaciones else "nada, porque no me has dicho qué cambiar"
    
    return {
        "status": "success",
        "mensaje": f"✅ ¡Cita modificada! He cambiado {cambios_texto}.<br>Abriendo agenda...",
        "mensaje_voz": f"Cita modificada con éxito.",
        "accion_pantalla": "abrir_pdf",
        "url": url_agenda
    }
