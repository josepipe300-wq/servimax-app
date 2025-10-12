from django.db import models

class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20, unique=True)
    def __str__(self):
        return self.nombre

class Vehiculo(models.Model):
    matricula = models.CharField(max_length=20, unique=True)
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    kilometraje = models.IntegerField(default=0)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.matricula})"

class OrdenDeReparacion(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE)
    fecha_entrada = models.DateTimeField(auto_now_add=True)
    problema = models.TextField()
    ESTADO_CHOICES = [
        ('Recibido', 'Recibido'),
        ('En Diagnostico', 'En Diagnóstico'),
        ('Esperando Piezas', 'Esperando Piezas'),
        ('En Reparacion', 'En Reparación'),
        ('Listo para Recoger', 'Listo para Recoger'),
        ('Entregado', 'Entregado'),
    ]
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Recibido')
    def __str__(self):
        return f"Orden #{self.id} - {self.vehiculo.matricula} ({self.cliente.nombre})"

class Empleado(models.Model):
    nombre = models.CharField(max_length=100)
    def __str__(self):
        return self.nombre

class Gasto(models.Model):
    CATEGORIA_CHOICES = [
        ('Repuestos', 'Repuestos'),
        ('Sueldos', 'Sueldos'),
        ('Herramientas', 'Herramientas'),
        ('Suministros', 'Suministros'),
        ('Otros', 'Otros'),
        ('Compra de Consumibles', 'Compra de Consumibles'),
    ]
    fecha = models.DateField(auto_now_add=True)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    importe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    descripcion = models.CharField(max_length=255, null=True, blank=True)
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True)
    empleado = models.ForeignKey(Empleado, on_delete=models.SET_NULL, null=True, blank=True)
    def __str__(self):
        display_importe = self.importe if self.importe is not None else 0
        return f"{self.fecha} - {self.get_categoria_display()} - {display_importe}€"

class Ingreso(models.Model):
    CATEGORIA_CHOICES = [
        ('Taller', 'Pago de Cliente (Taller)'),
        ('Grua', 'Servicio de Grúa'),
        ('Otras Ganancias', 'Otras Ganancias'),
        ('Otros', 'Otros Ingresos'),
    ]
    fecha = models.DateField(auto_now_add=True)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    importe = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.CharField(max_length=255)
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.SET_NULL, null=True, blank=True)
    def __str__(self):
        return f"{self.fecha} - {self.get_categoria_display()} - {self.importe}€"

class Factura(models.Model):
    orden = models.OneToOneField(OrdenDeReparacion, on_delete=models.CASCADE)
    fecha_emision = models.DateField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_final = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    def __str__(self):
        return f"Factura #{self.id} para Orden #{self.orden.id}"

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
    def total_linea(self):
        return self.cantidad * self.precio_unitario
    def __str__(self):
        return f"Línea de {self.tipo} para Factura #{self.factura.id}"

class TipoConsumible(models.Model):
    nombre = models.CharField(max_length=100)
    unidad_medida = models.CharField(max_length=20)
    def __str__(self):
        return self.nombre

class CompraConsumible(models.Model):
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE)
    fecha_compra = models.DateField()
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    coste_total = models.DecimalField(max_digits=10, decimal_places=2)
    coste_por_unidad = models.DecimalField(max_digits=10, decimal_places=4, editable=False)
    def save(self, *args, **kwargs):
        if self.cantidad > 0:
            self.coste_por_unidad = self.coste_total / self.cantidad
        super().save(*args, **kwargs)
    def __str__(self):
        return f"Compra de {self.cantidad} {self.tipo.unidad_medida} de {self.tipo.nombre} el {self.fecha_compra}"

class UsoConsumible(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, on_delete=models.CASCADE)
    tipo = models.ForeignKey(TipoConsumible, on_delete=models.CASCADE)
    cantidad_usada = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_uso = models.DateField(auto_now_add=True)
    def __str__(self):
        return f"Uso de {self.cantidad_usada} {self.tipo.unidad_medida} en Orden #{self.orden.id}"

class FotoVehiculo(models.Model):
    orden = models.ForeignKey(OrdenDeReparacion, related_name='fotos', on_delete=models.CASCADE)
    imagen = models.ImageField(upload_to='fotos_vehiculos/')
    descripcion = models.CharField(max_length=50)
    def __str__(self):
        return f"Foto {self.descripcion} para Orden #{self.orden.id}"