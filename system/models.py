from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from productos.models import Producto


class ConfiguracionSistema(models.Model):
    """Parámetros configurables del sistema (clave-valor)."""
    clave = models.CharField(max_length=100, unique=True)
    valor = models.TextField(blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración del sistema'
        verbose_name_plural = 'Configuraciones del sistema'

    def __str__(self):
        return f'{self.clave} = {self.valor}'

    @classmethod
    def get_int(cls, clave, default):
        """Lee una clave como entero; devuelve default si falta o no es válida."""
        try:
            return int(cls.objects.get(clave=clave).valor)
        except (cls.DoesNotExist, TypeError, ValueError):
            return default


class RegistroActividad(models.Model):
    """Historial de acciones realizadas en el sistema."""

    ACCIONES = [
        ('create', 'Creación'),
        ('update', 'Modificación'),
        ('delete', 'Eliminación'),
        ('approve', 'Aprobación'),
        ('login', 'Inicio de sesión'),
        ('export', 'Exportación de datos'),
        ('query', 'Consulta chatbot'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    accion = models.CharField(max_length=20, choices=ACCIONES)
    descripcion = models.TextField()
    segmentos = models.JSONField(default=list, blank=True)
    sucursal = models.ForeignKey(
        'organizacion.Sucursal', on_delete=models.PROTECT,
        related_name='actividades',
    )
    creado = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if self.segmentos:
            self.descripcion = "".join(s["texto"] for s in self.segmentos)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Registro de actividad'
        verbose_name_plural = 'Registros de actividad'
        ordering = ['-creado']

    def __str__(self):
        return f'{self.usuario} - {self.get_accion_display()} ({self.creado.strftime("%Y-%m-%d %H:%M")})'


class AlertaInventario(models.Model):
    """Alertas automáticas generadas por el sistema de inventario."""
    TIPOS_ALERTA = [
        ('low_stock', 'Bajo stock'),
        ('old_product', 'Producto antiguo'),
        ('unusual_movement', 'Movimiento inusual'),
        ('high_rotation', 'Alta rotación'),
    ]

    sucursal = models.ForeignKey('organizacion.Sucursal', on_delete=models.PROTECT, related_name='alertas')
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='alertas')
    tipo_alerta = models.CharField(max_length=30, choices=TIPOS_ALERTA)
    mensaje = models.TextField()
    creado = models.DateTimeField(auto_now_add=True)
    resuelto = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Alerta de inventario'
        verbose_name_plural = 'Alertas de inventario'
        ordering = ['-creado']

    def __str__(self):
        return f'{self.get_tipo_alerta_display()} - {self.producto.codigo_interno}'
