from django.contrib.auth.models import User
from django.db import models

from productos.models import Equipo


class Cliente(models.Model):
    TIPO_PERSONA = [
        ('fisica', 'Persona Física'),
        ('moral', 'Persona Moral'),
    ]

    nombre = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10, choices=TIPO_PERSONA, default='fisica')

    rfc = models.CharField(max_length=13, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    direccion = models.TextField(blank=True, null=True)

    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    sucursal = models.ForeignKey('Sucursal', on_delete=models.CASCADE, related_name='clientes')

    class Meta:
        ordering = ['nombre']
        unique_together = ('rfc', 'activo')

    def __str__(self):
        return self.nombre


class Sucursal(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    direccion = models.CharField(max_length=200, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Sucursal'
        verbose_name_plural = 'Sucursales'

    def __str__(self):
        return self.nombre


class PerfilUsuario(models.Model):
    """Extiende la información del usuario (rol, sucursal, etc.)"""
    ROLE_CHOICES = [
        ('admin', 'Administrador'),
        ('operativo', 'Operativo'),
        ('consulta', 'Consulta'),
    ]

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    rol = models.CharField(max_length=20, choices=ROLE_CHOICES, default='operativo')
    telefono = models.CharField(max_length=20, blank=True, null=True)
    sucursales = models.ManyToManyField(Sucursal, blank=True, related_name='usuarios')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuario'

    def __str__(self):
        return f'{self.usuario.username} ({self.get_rol_display()})'


class EquipoCliente(models.Model):
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='clientes')
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='equipos')
    alias = models.CharField(max_length=100)
    contador_uso = models.PositiveIntegerField()

    class Meta:
        verbose_name = 'Equipo de cliente'
        verbose_name_plural = 'Equipos de clientes'
        unique_together = ('equipo', 'cliente')

    def __str__(self):
        return f'Equipo {self.equipo.nombre} para Cliente {self.cliente.nombre} ({self.alias})'
