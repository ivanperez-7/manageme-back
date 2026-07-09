from django.contrib import admin
from django.db.models import Count, Q

from .models import Marca, Categoría, Proveedor, Producto, Equipo, Lote, Unidad


class EquipoInline(admin.TabularInline):
    model = Equipo
    extra = 1


@admin.register(Marca)
class MarcaAdmin(admin.ModelAdmin):
    """Administración de marcas."""
    list_display = ('nombre', 'activo')
    search_fields = ('nombre',)
    ordering = ('nombre',)
    list_per_page = 25
    inlines = [EquipoInline]


@admin.register(Categoría)
class CategoriaAdmin(admin.ModelAdmin):
    """Administración de categorías de productos."""
    list_display = ('nombre', 'descripcion_resumida')
    search_fields = ('nombre',)
    ordering = ('nombre',)
    list_per_page = 25

    def descripcion_resumida(self, obj):
        return (obj.descripcion[:50] + '...') if obj.descripcion and len(obj.descripcion) > 50 else obj.descripcion
    descripcion_resumida.short_description = 'Descripción'


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    """Gestión de proveedores."""
    list_display = ('nombre', 'nombre_contacto', 'telefono', 'correo', 'activo')
    list_filter = ('activo',)
    search_fields = ('nombre', 'nombre_contacto', 'telefono', 'correo')
    ordering = ('nombre',)
    list_per_page = 25
    fieldsets = (
        ('Información del proveedor', {
            'fields': ('nombre', 'nombre_contacto', 'telefono', 'correo'),
        }),
        ('Detalles adicionales', {
            'fields': ('direccion', 'activo'),
        }),
    )


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    """Gestión del catálogo de productos."""
    list_display = (
        'codigo_interno',
        'descripcion',
        'categoria',
        'equipos_list',
        'sku',
        'min_stock',
        'proveedor',
        'unidad_medida',
        'status',
    )
    list_filter = ('categoria', 'equipos__marca', 'status')
    search_fields = ('codigo_interno', 'descripcion')
    list_per_page = 25
    ordering = ('codigo_interno',)
    list_select_related = ('categoria', 'proveedor')
    list_prefetch_related = ('equipos',)

    readonly_fields = ('creado', 'actualizado')

    fieldsets = (
        ('Identificación y descripción', {
            'fields': (
                'codigo_interno',
                'descripcion',
                'sku',
                'categoria',
                'equipos',
                'proveedor',
                'min_stock',
                'unidad_medida',
            )
        }),
        ('Estado y control', {
            'fields': ('status', 'creado', 'actualizado', 'vida_util_unidades', 'vida_util_dias'),
        }),
    )
    
    def equipos_list(self, obj: Producto):
        return ', '.join([equipo.nombre for equipo in obj.equipos.all()]) if obj.equipos.exists() else '-'


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = (
        'codigo_lote',
        'producto',
        'cantidad_inicial',
        'cantidad_restante',
        'fecha_entrada',
    )
    search_fields = ('codigo_lote', 'producto__codigo_interno')
    list_filter = ('producto__categoria', 'producto__equipos__marca')
    autocomplete_fields = ('producto',)
    readonly_fields = ('creado', 'actualizado')
    ordering = ('-fecha_entrada',)

    def cantidad_restante(self, obj: Lote):
        return obj.cantidad_restante
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(cantidad_restante=Count('unidades', filter=Q(unidades__status='disponible')))


@admin.register(Unidad)
class UnidadAdmin(admin.ModelAdmin):
    list_display = (
        'codigo_unidad',
        'lote',
        'producto',
        'status',
        'actualizado',
    )
    search_fields = ('codigo_unidad', 'lote__codigo_lote', 'lote__producto__codigo_interno')
    list_filter = ('status', 'lote__producto__categoria')
    autocomplete_fields = ('lote',)
    readonly_fields = ('actualizado',)

    def producto(self, obj):
        return obj.lote.producto
