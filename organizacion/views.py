from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import F
from rest_framework import status, viewsets
from rest_framework.decorators import action
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
            equipo_id = int(request.data['equipoId'])
            cliente.equipos.create(
                equipo_id=equipo_id,
                contador_uso=request.data['contadorUso'],
                alias=request.data.get('alias', '')
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
            return Response({'success': True}, status=201)

        if request.method == 'DELETE':
            cliente = self.get_object()
            equipo_id = request.data.get('equipoId')

            if not equipo_id:
                return Response(
                    {'detail': 'equipoId es requerido.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                equipo_cliente = cliente.equipos.get(equipo_id=equipo_id)
            except EquipoCliente.DoesNotExist:
                return Response(
                    {'detail': 'El cliente no tiene este equipo asignado.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            equipo_id = int(equipo_id)
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
            equipo_id = request.data.get('equipoId')

            if not equipo_id:
                return Response(
                    {'detail': 'equipoId es requerido.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                equipo_cliente = cliente.equipos.get(equipo_id=equipo_id)
            except EquipoCliente.DoesNotExist:
                return Response(
                    {'detail': 'El cliente no tiene este equipo asignado.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if 'alias' in request.data:
                equipo_cliente.alias = request.data['alias']
            if 'contador_uso' in request.data:
                equipo_cliente.contador_uso = request.data['contador_uso']
            equipo_cliente.save()

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
        equipo_id = request.data.get('equipoId')
        cantidad = request.data.get('cantidad')

        if not equipo_id or not cantidad:
            return Response(
                {'detail': 'equipoId y cantidad son requeridos.'},
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

        try:
            equipo_cliente = cliente.equipos.select_related('equipo').get(equipo_id=equipo_id)
        except EquipoCliente.DoesNotExist:
            return Response(
                {'detail': 'El cliente no tiene este equipo asignado.'},
                status=status.HTTP_404_NOT_FOUND,
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
