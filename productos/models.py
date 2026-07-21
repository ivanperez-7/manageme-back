import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Marca(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Marca'
        verbose_name_plural = 'Marcas'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Equipo(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    marca = models.ForeignKey(Marca, on_delete=models.CASCADE, related_name='equipos')
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Equipo'
        verbose_name_plural = 'Equipos'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} ({self.marca.nombre})'


class Categoría(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Proveedor(models.Model):
    nombre = models.CharField(max_length=150)
    nombre_contacto = models.CharField(max_length=100, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    correo = models.EmailField(blank=True, null=True)
    direccion = models.TextField(blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    STATUS_CHOICES = [
        ('activo', 'Activo'),
        ('inactivo', 'Inactivo'),
    ]

    codigo_interno = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=255)
    categoria = models.ForeignKey(Categoría, on_delete=models.PROTECT)
    equipos = models.ManyToManyField(
        Equipo,
        blank=True,
        limit_choices_to={'activo': True, 'marca__activo': True}
    )
    unidad_medida = models.CharField(max_length=20, default='pieza')

    sku = models.CharField(max_length=255, unique=True)
    min_stock = models.PositiveIntegerField()
    # Vida útil medida por unidades de uso y/o por días; lo que ocurra primero.
    # default=1 en unidades para no romper altas sin especificar; poner null explícito
    # para productos medidos solo por tiempo.
    vida_util_unidades = models.PositiveIntegerField(default=1, null=True, blank=True, validators=[MinValueValidator(1)])
    vida_util_dias = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    proveedor = models.ForeignKey(Proveedor, on_delete=models.SET_NULL, null=True, blank=True)

    creado = models.DateTimeField(default=timezone.now)
    actualizado = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='activo')

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(vida_util_unidades__isnull=False) | models.Q(vida_util_dias__isnull=False),
                name='producto_vida_util_al_menos_uno',
            ),
        ]
    
    def save(self, *args, **kwargs):
        self.sku = self.sku.upper()
        if self.status == 'inactivo' and self.movimientoitem_set.exists():
            raise ValueError('No se puede desactivar producto utilizado en movimientos.')
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.codigo_interno} ({self.descripcion})'


class Lote(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='lotes')
    codigo_lote = models.CharField(max_length=100, unique=True)
    sucursal = models.ForeignKey('organizacion.Sucursal', on_delete=models.PROTECT, related_name='lotes')

    cantidad_inicial = models.PositiveIntegerField()

    fecha_entrada = models.DateTimeField(default=timezone.now)
    creado = models.DateTimeField(default=timezone.now)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Lote'
        verbose_name_plural = 'Lotes'
    
    def __str__(self):
        return self.codigo_lote


class Unidad(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, related_name='unidades')
    codigo_unidad = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    status = models.CharField(max_length=20, default='disponible')
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Unidad'
        verbose_name_plural = 'Unidades'

    def __str__(self):
        return f'Unidad de {self.lote.producto.codigo_interno}, lote {self.lote.codigo_lote}: {self.codigo_unidad}'
