from django.db.models import Count, Sum, Q, F
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import Categoría, Marca, Proveedor, Equipo, Unidad
from .serializers import *
from movimiento.models import Movimiento, MovimientoItem
from organizacion.models import Cliente, EquipoCliente
from productos.queries import lotes_queryset, productos_queryset, rendimiento_data, reorden_data
from utils.exports import xlsx_response
from utils.mixins import ActivityLogMixin

__all__ = [
    'ProductoViewSet',
    'LoteViewSet',
    'UnidadViewSet',
    'CategoriaViewSet',
    'MarcaViewSet',
    'EquipoViewSet',
    'ProveedorViewSet',
    'dashboard_view',
    'rendimiento_view',
    'reorden_view',
    'exportar_existencias_view',
    'exportar_rendimiento_view',
    'exportar_reorden_view',
]


class ProductoViewSet(ActivityLogMixin, viewsets.ModelViewSet):
    serializer_class = ProductoSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ['sku', 'categoria', 'equipos__marca', 'equipos']

    def get_queryset(self):
        return productos_queryset(self.request.branch_id)
    
    def update(self, request, *args, **kwargs):
        try:
            return super().update(request, *args, **kwargs)
        except Exception as e:  
            return Response({'detail': str(e)}, status=500)

    # Se sobreescribe perform_update para detectar soft-delete
    # (status activo → inactivo) y registrarlo como 'delete' en lugar de 'update'.
    def perform_update(self, serializer):
        old_status = serializer.instance.status
        instance = serializer.save()
        action = 'delete' if old_status == 'activo' and instance.status == 'inactivo' else 'update'
        self.log(instance, action)


class LoteViewSet(ActivityLogMixin, viewsets.ModelViewSet):
    serializer_class = LoteSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ['producto', 'codigo_lote']

    def get_queryset(self):
        return lotes_queryset(sucursal_id=self.request.branch_id)


class UnidadViewSet(viewsets.ModelViewSet):
    serializer_class = UnidadSerializer

    def get_queryset(self):
        return Unidad.objects.exclude(lote__producto__status='inactivo').filter(
            lote__sucursal=self.request.branch_id
        ).select_related('lote')


class CategoriaViewSet(ActivityLogMixin, viewsets.ModelViewSet):
    queryset = Categoría.objects.all()
    serializer_class = CategoriaSerializer


class MarcaViewSet(ActivityLogMixin, viewsets.ModelViewSet):
    queryset = Marca.objects.filter(activo=True)
    serializer_class = MarcaSerializer


class EquipoViewSet(ActivityLogMixin, viewsets.ModelViewSet):
    queryset = (
        Equipo.objects.filter(activo=True, marca__activo=True)
        .order_by('marca__nombre', 'nombre')
        .select_related('marca')
    )
    serializer_class = EquipoSerializer

    @action(detail=True, methods=['get'])
    def clientes(self, request, pk=None):
        equipo = self.get_object()
        qs = EquipoCliente.objects.filter(
            equipo=equipo,
            cliente__activo=True,
            cliente__sucursal=request.branch_id
        ).select_related('equipo__marca', 'cliente', 'equipo')

        serializer = EquipoClienteSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        equipo = self.get_object()
        
        instalaciones = EquipoCliente.objects.filter(
            equipo=equipo,
            cliente__activo=True,
            cliente__sucursal=request.branch_id
        )
        total_instalaciones = instalaciones.count()
        uso_total = instalaciones.aggregate(total=Sum('contador_uso'))['total'] or 0
        total_movimientos = MovimientoItem.objects.filter(
            equipo_cliente__equipo=equipo,
            movimiento__aprobado=True,
            movimiento__sucursal=request.branch_id
        ).count()

        return Response({
            'total_productos': equipo.producto_set.filter(status='activo').count(),
            'total_instalaciones': total_instalaciones,
            'uso_total': uso_total,
            'uso_promedio': round(uso_total / total_instalaciones) if total_instalaciones else 0,
            'total_movimientos': total_movimientos,
        })


class ProveedorViewSet(ActivityLogMixin, viewsets.ModelViewSet):
    queryset = Proveedor.objects.filter(activo=True)
    serializer_class = ProveedorSerializer


@api_view()
def dashboard_view(request):
    branch_id = request.branch_id
    productos = productos_queryset(sucursal_id=branch_id)
    categorias = Categoría.objects.all()

    hace_30_dias = (timezone.now() - timezone.timedelta(days=30)).date()

    movs_filter = Q(
        movimientoitem__movimiento__creado__date__gte=hace_30_dias,
        movimientoitem__movimiento__aprobado=True,
        movimientoitem__movimiento__sucursal=branch_id,
    )

    return Response(
        {
            'stats': {
                'productos': productos.count(),
                'lotes': lotes_queryset(sucursal_id=branch_id).filter(cantidad_restante__gt=0).count(),
                'categorias': categorias.count(),
                'proveedores': Proveedor.objects.filter(activo=True).count(),
                'clientes': Cliente.objects.filter(activo=True, sucursal=branch_id).count(),
            },
            'categoriasChart': (
                categorias.values('nombre').annotate(
                    cantidad=Count('producto', filter=Q(producto__status='activo'))
                )
                .filter(cantidad__gt=0)
            ),
            'movimientosChart': (
                Movimiento.objects.filter(
                    creado__date__gte=hace_30_dias, aprobado=True, sucursal=branch_id
                )
                .values(fecha_creado=F('creado__date'))
                .annotate(
                    entradas=Count('id', filter=Q(tipo='entrada')),
                    salidas=Count('id', filter=Q(tipo='salida'))
                )
            ),
            'topProductosChart': (
                productos.values('id', 'codigo_interno')
                .annotate(
                    total_movimientos=Count('movimientoitem__movimiento', distinct=True, filter=movs_filter)
                )
                .filter(total_movimientos__gt=0)
                .order_by('-total_movimientos')[:10]
            ),
            'productosBajos': (
                productos.filter(cantidad_disponible__lt=F('min_stock'))
                .order_by('-cantidad_disponible')
                .values('id', 'descripcion', 'categoria__nombre', 'cantidad_disponible', 'min_stock')
            ),
        }
    )


@api_view()
def rendimiento_view(request):
    fecha_inicio = request.query_params.get('fechaInicio')
    fecha_fin = request.query_params.get('fechaFin')
    data = rendimiento_data(
        sucursal_id=request.branch_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )
    return Response(data)


@api_view()
def reorden_view(request):
    data = reorden_data(sucursal_id=request.branch_id)
    return Response(data)


@api_view()
def exportar_reorden_view(request):
    grupos = reorden_data(sucursal_id=request.branch_id)
    headers = [
        'Proveedor', 'Código', 'Descripción', 'Disponible', 'Mínimo',
        'Consumo mensual', 'Días cobertura', 'Cantidad sugerida',
    ]
    rows = []
    for grupo in grupos:
        for p in grupo['productos']:
            rows.append([
                grupo['proveedor_nombre'],
                p['codigo_interno'],
                p['descripcion'],
                p['cantidad_disponible'],
                p['min_stock'],
                p['consumo_mensual'],
                p['dias_cobertura'],
                p['cantidad_sugerida'],
            ])
    return xlsx_response(headers, rows, 'reorden.xlsx', sheet_title='Reorden')


@api_view()
def exportar_existencias_view(request):
    productos = productos_queryset(request.branch_id).order_by('codigo_interno')
    headers = ['Código', 'Descripción', 'Categoría', 'Disponible', 'Mínimo']
    rows = [
        [
            p.codigo_interno,
            p.descripcion,
            p.categoria.nombre,
            p.cantidad_disponible,
            p.min_stock,
        ]
        for p in productos
    ]
    return xlsx_response(headers, rows, 'existencias.xlsx', sheet_title='Existencias')


@api_view()
def exportar_rendimiento_view(request):
    data = rendimiento_data(
        sucursal_id=request.branch_id,
        fecha_inicio=request.query_params.get('fechaInicio'),
        fecha_fin=request.query_params.get('fechaFin'),
    )
    headers = [
        'Código', 'Descripción',
        'Vida útil (unid)', 'Ciclos', 'Uso promedio', 'Ratio',
        'Vida útil (días)', 'Ciclos días', 'Días promedio', 'Ratio días',
    ]
    rows = [
        [
            r['codigo_interno'],
            r['descripcion'],
            r['vida_util_unidades'],
            r['ciclos'],
            r['uso_promedio'],
            r['ratio'],
            r['vida_util_dias'],
            r['ciclos_dias'],
            r['dias_promedio'],
            r['ratio_dias'],
        ]
        for r in data
    ]
    return xlsx_response(headers, rows, 'rendimiento.xlsx', sheet_title='Rendimiento')
