from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import F
from django_filters import rest_framework as dj_filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.response import Response

from system.models import RegistroActividad
from utils.mixins import ActivityLogMixin
from utils.throttles import SucursalAnonThrottle

from .models import EquipoCliente
from .serializers import ClienteSerializer, UserSerializer, SucursalSerializer
from organizacion.models import Cliente, Sucursal
from productos.serializers import EquipoClienteSerializer

__all__ = ['ClienteViewSet', 'UserViewSet', 'SucursalViewSet']


class ClienteViewSet(ActivityLogMixin, viewsets.ModelViewSet):
    serializer_class = ClienteSerializer
    filter_backends = [dj_filters.DjangoFilterBackend, SearchFilter]
    filterset_fields = ['tipo']
    search_fields = ['nombre', 'rfc', 'telefono', 'email']

    def get_serializer_class(self):
        # La acción `equipos` serializa unidades (EquipoCliente), no clientes.
        if self.action == 'equipos':
            return EquipoClienteSerializer
        return ClienteSerializer

    def get_queryset(self):
        return Cliente.objects.filter(activo=True, sucursal=self.request.branch_id)

    def perform_create(self, serializer):
        instance = serializer.save(sucursal_id=self.request.branch_id)
        self.log(instance, 'create')

    # Se sobreescribe perform_update para detectar soft-delete
    # (activo True → False) y registrarlo como 'delete' en lugar de 'update'.
    def perform_update(self, serializer):
        old_active = serializer.instance.activo
        instance = serializer.save()
        action = 'delete' if old_active and not instance.activo else 'update'
        self.log(instance, action)

    def _get_equipo_cliente(self, cliente, data):
        """Resuelve la unidad objetivo por ``equipoClienteId`` (preferido) o
        ``equipoId`` (legacy).

        ``unique_together = (cliente, equipo, numero_serie)`` permite varias
        unidades del mismo equipo asignadas al mismo cliente: el fallback por
        ``equipoId`` solo es válido cuando existe una sola unidad.
        """
        equipo_cliente_id = data.get('equipoClienteId')
        if equipo_cliente_id:
            try:
                return cliente.equipos.get(pk=equipo_cliente_id), None
            except EquipoCliente.DoesNotExist:
                return None, Response(
                    {'detail': 'La unidad no está asignada a este cliente.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

        equipo_id = data.get('equipoId')
        if not equipo_id:
            return None, Response(
                {'detail': 'equipoId o equipoClienteId es requerido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        unidades = cliente.equipos.filter(equipo_id=equipo_id)
        if not unidades.exists():
            return None, Response(
                {'detail': 'El cliente no tiene este equipo asignado.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if unidades.count() > 1:
            return None, Response(
                {
                    'detail': (
                        'Hay varias unidades de este equipo para el cliente; '
                        'especifique equipoClienteId.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return unidades.first(), None

    @action(detail=True, methods=['get', 'post', 'patch', 'delete'])
    def equipos(self, request, pk=None):
        if request.method == 'GET':
            # Obtener datos de uso del cliente
            productos = request.query_params.getlist('productos[]')
            cliente = self.get_object()

            if productos:
                qs = cliente.equipos.filter(equipo__producto__in=productos)
            else:
                qs = cliente.equipos.all()

            qs = qs.filter(
                equipo__activo=True, equipo__marca__activo=True
            ).select_related('equipo__marca', 'equipo', 'cliente').distinct()
            
            serializer = EquipoClienteSerializer(qs, many=True)
            return Response(serializer.data)

        if request.method == 'POST':
            # Crear equipos del cliente
            cliente = self.get_object()

            try:
                equipo_id = int(request.data.get('equipoId'))
            except (TypeError, ValueError):
                return Response(
                    {'detail': 'equipoId debe ser un número entero.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                contador_uso = int(request.data.get('contadorUso'))
            except (TypeError, ValueError):
                return Response(
                    {'detail': 'contadorUso debe ser un número entero.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if contador_uso < 0:
                return Response(
                    {'detail': 'contadorUso debe ser un número positivo.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            numero_serie = (request.data.get('numeroSerie') or '').strip()
            unidades = cliente.equipos.filter(equipo_id=equipo_id)

            # (cliente, equipo, numero_serie) es único: una segunda unidad del
            # mismo equipo solo es válida si se identifica con número de serie.
            if not numero_serie and unidades.exists():
                return Response(
                    {
                        'detail': (
                            'Este equipo ya está asignado a este cliente. '
                            'Indique un número de serie para registrar otra unidad.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if numero_serie and unidades.filter(numero_serie=numero_serie).exists():
                return Response(
                    {
                        'detail': (
                            'Ya existe una unidad de este equipo con ese número '
                            'de serie para este cliente.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                equipo_cliente = cliente.equipos.create(
                    equipo_id=equipo_id,
                    contador_uso=contador_uso,
                    alias=request.data.get('alias', ''),
                    numero_serie=numero_serie,
                    comentarios=request.data.get('comentarios', ''),
                )
            except IntegrityError:
                return Response(
                    {'detail': 'Ya existe una unidad con esos datos para este cliente.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            segmentos = [
                {"texto": "Asignó "},
                {"texto": f"el equipo #{equipo_id}", "tipo": "equipo", "id": equipo_id},
                {"texto": f" al {cliente} — "},
                {"texto": str(cliente), "tipo": "cliente", "id": cliente.pk},
            ]
            RegistroActividad.objects.create(
                usuario=request.user, accion='create',
                descripcion=f'Asignó el equipo #{equipo_id} al {cliente}',
                segmentos=segmentos,
                sucursal_id=request.branch_id,
            )
            return Response({'success': True, 'id': equipo_cliente.id}, status=201)

        if request.method == 'DELETE':
            cliente = self.get_object()
            equipo_cliente, error = self._get_equipo_cliente(cliente, request.data)
            if error:
                return error

            equipo_id = equipo_cliente.equipo_id
            equipo_cliente.delete()
            segmentos = [
                {"texto": "Desasignó "},
                {"texto": f"el equipo #{equipo_id}", "tipo": "equipo", "id": equipo_id},
                {"texto": f" del {cliente} — "},
                {"texto": str(cliente), "tipo": "cliente", "id": cliente.pk},
            ]
            RegistroActividad.objects.create(
                usuario=request.user, accion='delete',
                descripcion=f'Desasignó el equipo #{equipo_id} del {cliente}',
                segmentos=segmentos,
                sucursal_id=request.branch_id,
            )
            return Response(status=status.HTTP_204_NO_CONTENT)

        if request.method == 'PATCH':
            cliente = self.get_object()
            equipo_cliente, error = self._get_equipo_cliente(cliente, request.data)
            if error:
                return error

            if 'alias' in request.data:
                equipo_cliente.alias = request.data['alias']
            if 'contador_uso' in request.data:
                try:
                    contador_uso = int(request.data['contador_uso'])
                except (TypeError, ValueError):
                    return Response(
                        {'detail': 'contador_uso debe ser un número entero.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if contador_uso < 0:
                    return Response(
                        {'detail': 'contador_uso debe ser un número positivo.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                equipo_cliente.contador_uso = contador_uso
            if 'numero_serie' in request.data:
                numero_serie = (request.data['numero_serie'] or '').strip()
                hermanas = cliente.equipos.filter(
                    equipo_id=equipo_cliente.equipo_id
                ).exclude(pk=equipo_cliente.pk)

                if not numero_serie and hermanas.exists():
                    return Response(
                        {
                            'detail': (
                                'Otra unidad de este equipo ya está asignada. '
                                'Indique un número de serie.'
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if numero_serie and hermanas.filter(numero_serie=numero_serie).exists():
                    return Response(
                        {
                            'detail': (
                                'Ya existe una unidad de este equipo con ese '
                                'número de serie.'
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                equipo_cliente.numero_serie = numero_serie
            if 'comentarios' in request.data:
                equipo_cliente.comentarios = request.data['comentarios']

            try:
                equipo_cliente.save()
            except IntegrityError:
                return Response(
                    {'detail': 'Ya existe una unidad con esos datos para este cliente.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            equipo_id = equipo_cliente.equipo_id
            RegistroActividad.objects.create(
                usuario=request.user, accion='update',
                descripcion=f'Actualizó equipo #{equipo_id} del {cliente}',
                segmentos=[
                    {"texto": "Actualizó "},
                    {"texto": f"el equipo #{equipo_id}", "tipo": "equipo", "id": equipo_id},
                    {"texto": f" del {cliente} — "},
                    {"texto": str(cliente), "tipo": "cliente", "id": cliente.pk},
                ],
                sucursal_id=request.branch_id,
            )

            serializer = EquipoClienteSerializer(equipo_cliente)
            return Response(serializer.data)

        return Response(status=405)

    @action(detail=True, methods=['post'])
    def incrementar_contador(self, request, pk=None):
        cliente = self.get_object()
        equipo_cliente, error = self._get_equipo_cliente(cliente, request.data)
        if error:
            return error

        cantidad = request.data.get('cantidad')

        if not cantidad:
            return Response(
                {'detail': 'cantidad es requerida.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            cantidad = int(cantidad)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'cantidad debe ser un número entero.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if cantidad <= 0:
            return Response(
                {'detail': 'cantidad debe ser un número positivo.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        equipo_cliente.contador_uso = F('contador_uso') + cantidad
        equipo_cliente.save(update_fields=['contador_uso'])
        equipo_cliente.refresh_from_db()

        return Response({'contador_uso': equipo_cliente.contador_uso})


class UserViewSet(ActivityLogMixin, viewsets.ModelViewSet):
    serializer_class = UserSerializer

    def get_queryset(self):
        return User.objects.filter(
            is_active=True, profile__sucursales=self.request.branch_id
        ).select_related('profile')

    def get_log_description(self, instance, action):
        segmentos = [
            {"texto": f"{self.verbs[action]} el usuario "},
            {"texto": str(instance), "tipo": "usuario", "id": instance.pk},
        ]
        return f"{self.verbs[action]} el usuario {instance}", segmentos


class SucursalViewSet(viewsets.ModelViewSet):
    """ Solo lectura de sucursales activas, sin logging ni permisos especiales."""
    queryset = Sucursal.objects.filter(activo=True)
    serializer_class = SucursalSerializer
    permission_classes = []
    http_method_names = ['get']
    throttle_classes = [SucursalAnonThrottle]

    def list(self, request, *args, **kwargs):
        data = cache.get('sucursales_list')
        if data is None:
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            data = serializer.data
            cache.set('sucursales_list', data, 600)
        return Response(data)
