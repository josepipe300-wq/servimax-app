# taller/models.py
from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum
from django.contrib.auth.models import User

class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20, unique=True)
    
    TIPO_DOCUMENTO_CHOICES = [
        ('DNI', 'DNI'),
        ('NIE', 'NIE'),
        ('NIF', 'NIF (Empresas)'),
    ]
    tipo_documento = models.CharField(max_length=10, choices=TIPO_DOCUMENTO_CHOICES, default='DNI', null=True, blank=True)
    documento_fiscal = models.CharField(max_length=20, null=True, blank=True, help_text="Número de DNI, NIE o NIF")
    direccion_fiscal = models.CharField(max_length=255, null=True, blank=True, help_text="Calle, Número, Piso, Puerta")
    codigo_postal_fiscal = models.CharField(max_length=10, null=True, blank=True)
    ciudad_fiscal = models.CharField(max_length=100, null=True, blank=True)
    provincia_fiscal = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        self.nombre = self.nombre.upper()
        if self.documento_fiscal: self.documento_fiscal = self.documento_fiscal.upper()
        if self.direccion_fiscal: self.direccion_fiscal = self.direccion_fiscal.upper()
        if self.ciudad_fiscal: self.ciudad_fiscal = self.ciudad_fiscal.upper()
        if self.provincia_fiscal: self.provincia_fiscal = self.provincia_fiscal.upper()
        super(Cliente, self).save(*args, **kwargs)

class Vehiculo(models.Model):
    matricula = models.CharField(max_length=20, unique=True)
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    kilometraje = models.IntegerField(default=0)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.matricula})"
        
    def save(self, *args, **kwargs):
        self.matricula = self.matricula.upper()
        self.marca = self.marca.upper()
        self.modelo = self.modelo.upper()
        super(Vehiculo, self).save(*args, **kwargs)

class Presupuesto(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True)
    matricula_nueva = models.CharField(max_length=20, blank=True, null=True)
    marca_nueva = models.CharField(max_length=50, blank=True, null=True)
    modelo_nuevo = models.CharField(max_length=50, blank=True, null=True)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    problema_o_trabajo = models.TextField()
    ESTADO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Aceptado', 'Aceptado'),
        ('Rechazado', 'Rechazado'),
        ('Convertido', 'Convertido a Orden'),
    ]
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Pendiente')
    aplicar_iva = models.BooleanField(default=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_estimado = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Presupuesto #{self.id} - {self.cliente.nombre}"

    def save(self, *args, **kwargs):
        if self.matricula_nueva: self.matricula_nueva = self.matricula_nueva.upper()
        if self.marca_nueva: self.marca_nueva = self.marca_nueva.upper()
        if self.modelo_nuevo: self.modelo_nuevo = self.modelo_nuevo.upper()
        self.problema_o_trabajo = self.problema_o_trabajo.upper()
        super(Presupuesto, self).save(*args, **kwargs)

class OrdenDeReparacion(models.Model):
    ESTADO_CHOICES = [
        ('Recibido', 'Recibido'),
        ('En Diagnostico', 'En Diagnóstico'),
        ('Esperando Piezas', 'Esperando Piezas'),
        ('En Reparacion', 'En Reparación'),
        ('Listo para Recoger', 'Listo para Recoger'),
        ('Entregado', 'Entregado'),
    ]
    
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    presupuesto_origen = models.ForeignKey('Presupuesto', null=True, blank=True, on_delete=models.SET_NULL)
    problema = models.TextField()
    estado = models.CharField(max_length=50, choices=ESTADO_CHOICES, default='Recibido')
    fecha_entrada = models.DateTimeField(auto_now_add=True)
    trabajo_interno = models.BooleanField(default=False, verbose_name="Vehículo del Taller")

    @property
    def dias_en_taller(self):
        if self.fecha_entrada:
            return (timezone.now().date() - self.fecha_entrada.date()).days
        return 0

    def __str__(self):
        return f"Orden #{self.id} - {self.vehiculo.matricula}"

class Empleado(models.Model):
    nombre = models.CharField(max_length=100)
    
    def __str__(self):
        return self.nombre
        
    def save(self, *args, **kwargs):
        self.nombre = self.nombre.upper()
        super(Empleado, self).save(*args, **kwargs)

class DeudaTaller(models.Model):
    acreedor = models.CharField(max_length=150, help_text="A quién se le debe (Ej: Hermano, Cliente X)")
    motivo = models.CharField(max_length=255)
    importe_inicial = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_creacion = models.DateField(default=timezone.now)
    
    # --- NUEVA LÍNEA AÑADIDA AQUÍ ---
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.SET_NULL, null=True, blank=True, help_text="Orden de trabajo asociada")

    @property
    def importe_pagado(self):
    # ... (el resto del código sigue igual)
        total = self.gastos_pagados.aggregate(total=Sum('importe'))['total']
        return total or Decimal('0.00')

    @property
    def importe_pendiente(self):
        return self.importe_inicial - self.importe_pagado

    @property
    def estado(self):
        if self.importe_pendiente <= 0: return "Pagada"
        return "Pendiente"

    def __str__(self):
        return f"{self.acreedor} - Resta: {self.importe_pendiente}€"

    def save(self, *args, **kwargs):
        self.acreedor = self.acreedor.upper()
        self.motivo = self.motivo.upper()
        super(DeudaTaller, self).save(*args, **kwargs)

class Gasto(models.Model):
    CATEGORIA_CHOICES = [
        ('Repuestos', 'Repuestos'),
        ('Sueldos', 'Sueldos'),
        ('Herramientas', 'Herramientas'),
        ('Suministros', 'Suministros (Agua, Café, etc.)'), # <-- Modificado para que tu hermano lo vea claro
        ('Gasolina/Diesel', 'Gasolina/Diesel'),
        ('Otros', 'Otros'),
        ('Compra de Consumibles', 'Compra de Consumibles (Stock Taller)'), # <-- Modificado
        ('COMISIONES_INTERESES', 'Comisiones e Intereses Bancarios'),
        ('Pago de Deuda', 'Pago de Deuda (Taller)'),
    ]
    
    METODO_PAGO_CHOICES = [
        ('EFECTIVO', 'Efectivo (Caja)'),
        ('CUENTA_TALLER', 'Cuenta Taller (Banco)'),
        ('TARJETA_1', 'Tarjeta 1 (Visa 2000€)'),
        ('TARJETA_2', 'Tarjeta 2 (Visa 1000€)'),
        ('CUENTA_ERIKA', 'Cuenta Erika (Antigua)'),
        ('COMPENSACION', '🤝 Compensación (Trueque / Sin dinero)'), # <-- LÍNEA NUEVA
    ]
    metodo_pago = models.CharField(max_length=20, choices=METODO_PAGO_CHOICES, default='EFECTIVO')
    
    fecha = models.DateField(default=timezone.now)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    importe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    descripcion = models.CharField(max_length=255, null=True, blank=True)
    
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.SET_NULL, null=True, blank=True, related_name='gastos')
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True)
    empleado = models.ForeignKey(Empleado, on_delete=models.SET_NULL, null=True, blank=True)
    deuda_asociada = models.ForeignKey(DeudaTaller, on_delete=models.SET_NULL, null=True, blank=True, related_name='gastos_pagados')
    pagado_con_tarjeta = models.BooleanField(default=False)

    def __str__(self):
        display_importe = self.importe if self.importe is not None else 0
        return f"{self.fecha} - {self.get_categoria_display()} - {display_importe}€"

    def save(self, *args, **kwargs):
        if self.descripcion: self.descripcion = self.descripcion.upper()
        if self.metodo_pago in ['TARJETA_1', 'TARJETA_2']: self.pagado_con_tarjeta = True
        super(Gasto, self).save(*args, **kwargs)

class Ingreso(models.Model):
    CATEGORIA_CHOICES = [
        ('Taller', 'Pago de Cliente (Taller)'),
        ('Grua', 'Servicio de Grúa'),
        ('Otras Ganancias', 'Otras Ganancias'),
        ('ABONO_TARJETA', 'Abono/Pago a Tarjeta'),
        ('Otros', 'Otros Ingresos'),
    ]
    METODO_PAGO_CHOICES = Gasto.METODO_PAGO_CHOICES 
    metodo_pago = models.CharField(max_length=20, choices=METODO_PAGO_CHOICES, default='EFECTIVO')
    fecha = models.DateField(default=timezone.now)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    importe = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.CharField(max_length=255)
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.SET_NULL, null=True, blank=True)
    es_tpv = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.fecha} - {self.get_categoria_display()} - {self.importe}€ [{self.get_metodo_pago_display()}]"

    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(Ingreso, self).save(*args, **kwargs)

class Factura(models.Model):
    orden = models.OneToOneField(OrdenDeReparacion, on_delete=models.CASCADE)
    fecha_emision = models.DateField(auto_now_add=True)
    es_factura = models.BooleanField(default=True)
    numero_factura = models.IntegerField(null=True, blank=True, unique=True, editable=False)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_final = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    notas_cliente = models.TextField(null=True, blank=True, help_text="Notas adicionales para el cliente")

    def __str__(self):
        if self.es_factura: return f"Factura Nº {self.numero_factura} para Orden #{self.orden.id}"
        return f"Recibo #{self.id} para Orden #{self.orden.id}"

    def save(self, *args, **kwargs):
        if self.notas_cliente: self.notas_cliente = self.notas_cliente.upper()
        super(Factura, self).save(*args, **kwargs)

class LineaFactura(models.Model):
    factura = models.ForeignKey(Factura, related_name='lineas', on_delete=models.CASCADE)
    TIPO_CHOICES = [
        ('Repuesto', 'Repuesto'),
        ('Consumible', 'Consumible'),
        ('Externo', 'Trabajo Externo'),
        ('Mano de Obra', 'Mano de Obra'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descripcion = models.CharField(max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    
    @property
    def total_linea(self): return (self.cantidad or 0) * (self.precio_unitario or 0)
        
    def __str__(self): return f"Línea de {self.tipo} para Factura #{self.factura.id}"
        
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(LineaFactura, self).save(*args, **kwargs)


# =========================================================
# --- MODULO DE INVENTARIO Y CONSUMIBLES (ACTUALIZADO) ---
# =========================================================

class TipoConsumible(models.Model):
    nombre = models.CharField(max_length=100)
    unidad_medida = models.CharField(max_length=20)
    nivel_minimo_stock = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # NUEVO: Aquí guardaremos el Precio Medio Ponderado para la rentabilidad exacta
    precio_coste_medio = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000, help_text="Se calcula automáticamente con cada compra")
    
    @property
    def stock_actual(self):
        total_comprado = CompraConsumible.objects.filter(tipo=self).aggregate(total=Sum('cantidad'))['total'] or Decimal('0.00')
        total_usado_ordenes = UsoConsumible.objects.filter(tipo=self).aggregate(total=Sum('cantidad_usada'))['total'] or Decimal('0.00')
        total_ajustado = AjusteStockConsumible.objects.filter(tipo=self).aggregate(total=Sum('cantidad_ajustada'))['total'] or Decimal('0.00')
        return (total_comprado - total_usado_ordenes + total_ajustado).quantize(Decimal('0.01'))

    @property
    def alerta_stock(self):
        if self.nivel_minimo_stock is not None and self.stock_actual <= self.nivel_minimo_stock: return "⚠️ BAJO"
        return "✅ OK" if self.nivel_minimo_stock is not None else "N/A"

    def __str__(self):
        return self.nombre
        
    def save(self, *args, **kwargs):
        self.nombre = self.nombre.upper()
        self.unidad_medida = self.unidad_medida.upper()
        super(TipoConsumible, self).save(*args, **kwargs)

class CompraConsumible(models.Model):
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE)
    fecha_compra = models.DateField()
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    coste_total = models.DecimalField(max_digits=10, decimal_places=2)
    coste_por_unidad = models.DecimalField(max_digits=10, decimal_places=4, editable=False)
    
    def save(self, *args, **kwargs):
        es_nuevo = self.pk is None # Verificamos si es una compra nueva
        
        if self.cantidad and self.cantidad > 0 and self.coste_total is not None:
            self.coste_por_unidad = self.coste_total / self.cantidad
        else:
            self.coste_por_unidad = Decimal('0.0000')
            
        # --- CÁLCULO DEL PRECIO MEDIO PONDERADO (PMP) ---
        if es_nuevo:
            tipo_asociado = self.tipo
            stock_previo = tipo_asociado.stock_actual
            precio_medio_previo = tipo_asociado.precio_coste_medio
            
            if stock_previo <= 0:
                # Si no había stock, el nuevo precio es directamente a lo que lo compramos hoy
                nuevo_precio_medio = self.coste_por_unidad
            else:
                # Fórmula de las grandes empresas: (Valor Almacén + Valor Nueva Compra) / (Stock Total)
                valor_inventario_previo = stock_previo * precio_medio_previo
                valor_nueva_compra = self.coste_total
                nuevo_stock_total = stock_previo + self.cantidad
                nuevo_precio_medio = (valor_inventario_previo + valor_nueva_compra) / nuevo_stock_total
            
            tipo_asociado.precio_coste_medio = nuevo_precio_medio
            tipo_asociado.save()
        # ------------------------------------------------

        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"Compra de {self.cantidad} {self.tipo.unidad_medida}"

class UsoConsumible(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.CASCADE)
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE)
    cantidad_usada = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_uso = models.DateField(default=timezone.now)
    
    def __str__(self): return f"Uso de {self.cantidad_usada} {self.tipo.unidad_medida}"

class AjusteStockConsumible(models.Model):
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE)
    cantidad_ajustada = models.DecimalField(max_digits=10, decimal_places=2, help_text="Usa negativo para restar (Ej: -5) y positivo para sumar (Ej: 5)")
    motivo = models.CharField(max_length=255)
    fecha_ajuste = models.DateField(default=timezone.now)
    
    class Meta:
        ordering = ['-fecha_ajuste', '-id']
        
    def save(self, *args, **kwargs):
        self.motivo = self.motivo.upper()
        super().save(*args, **kwargs)

# Modelo Proxy para mantener compatibilidad en el Panel de Admin si lo usabas
class TipoConsumibleStock(TipoConsumible):
    class Meta:
        proxy = True
        verbose_name = "Stock de Consumible"
        verbose_name_plural = "Stocks de Consumibles"

# =========================================================

class FotoVehiculo(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, related_name='fotos', on_delete=models.CASCADE)
    imagen = models.ImageField(upload_to='fotos_vehiculos/')
    descripcion = models.CharField(max_length=50)
    
    def __str__(self): return f"Foto {self.descripcion} para Orden #{self.orden.id}"
        
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(FotoVehiculo, self).save(*args, **kwargs)

class LineaPresupuesto(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, related_name='lineas', on_delete=models.CASCADE)
    TIPO_CHOICES = LineaFactura.TIPO_CHOICES
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descripcion = models.CharField(max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    precio_unitario_estimado = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def total_linea_estimado(self): return (self.cantidad or 0) * (self.precio_unitario_estimado or 0)

    def __str__(self): return f"Línea ({self.tipo}) para Presupuesto #{self.presupuesto.id}"

    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(LineaPresupuesto, self).save(*args, **kwargs)


class CierreTarjeta(models.Model):
    TARJETA_CHOICES = [
        ('TARJETA_1', 'Tarjeta 1 (Visa 2000€)'),
        ('TARJETA_2', 'Tarjeta 2 (Visa 1000€)'),
    ]
    fecha_cierre = models.DateField(default=timezone.now)
    tarjeta = models.CharField(max_length=20, choices=TARJETA_CHOICES)
    pago_cuota = models.DecimalField(max_digits=10, decimal_places=2, help_text="Los 150€ o el pago total")
    saldo_deuda_banco = models.DecimalField(max_digits=10, decimal_places=2, help_text="Deuda real que dice el banco")
    intereses_calculados = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self): return f"Cierre {self.tarjeta} - {self.fecha_cierre}"

class NotaTablon(models.Model):
    autor = models.ForeignKey(User, on_delete=models.CASCADE)
    texto = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    completada = models.BooleanField(default=False)

    def __str__(self): return f"{self.autor.username} - {self.texto[:20]}"

class NotaInternaOrden(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, related_name='notas_internas', on_delete=models.CASCADE)
    autor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    imagen = models.ImageField(upload_to='notas_internas/', null=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']

    def __str__(self): return f"Nota interna en Orden #{self.orden.id}"

# --- SEÑALES AUTOMÁTICAS PARA EL INVENTARIO ---
from django.db.models.signals import pre_delete
from django.dispatch import receiver

@receiver(pre_delete, sender=CompraConsumible)
def revertir_stock_al_borrar_compra(sender, instance, **kwargs):
    pass # Ya no necesitamos la señal de restar stock manual porque se lee todo en tiempo real con aggregates.

@receiver(pre_delete, sender=UsoConsumible)
def revertir_stock_al_borrar_uso(sender, instance, **kwargs):
    pass