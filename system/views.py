from django.conf import settings
from django.middleware.csrf import get_token
from django.urls import reverse
from langchain_core.exceptions import OutputParserException
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from utils.permissions import HasAdminRole, HasValidBranch

from .models import AlertaInventario, ConfiguracionSistema, RegistroActividad
from .serializers import (
    AlertaInventarioSerializer,
    ConfiguracionSistemaSerializer,
    RegistroActividadSerializer,
)
from organizacion.serializers import UserSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user

    if not hasattr(user, 'profile'):
        return Response({'detail': 'Perfil de usuario no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

    return Response(UserSerializer(user).data)


class CookieTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            data = response.data
            refresh = data.pop('refresh', None)

            if refresh:
                response.set_cookie(
                    key='refresh_token',
                    value=refresh,
                    httponly=True,
                    secure=not settings.DEBUG,
                    samesite='Lax' if settings.DEBUG else 'None',
                    path=reverse('token_refresh'),
                    max_age=settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']
                )
                
            csrf_token = get_token(request)
            response.set_cookie(
                key='csrftoken',
                value=csrf_token,
                httponly=False,
                secure=not settings.DEBUG,
                samesite='Lax' if settings.DEBUG else 'None'
            )
        return response


class CookieTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh = request.COOKIES.get('refresh_token')

        if refresh is None:
            return Response({'detail': 'Refresh token not found.'}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = self.get_serializer(data={'refresh': refresh})
        serializer.is_valid(raise_exception=True)

        return Response(serializer.validated_data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    response = Response({'detail': 'Sesión cerrada correctamente.'}, status=status.HTTP_200_OK)
    response.set_cookie(
        key='refresh_token',
        value='',
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax' if settings.DEBUG else 'None',
        path=reverse('token_refresh'),
    )
    return response


class ConfiguracionSistemaViewSet(viewsets.ModelViewSet):
    queryset = ConfiguracionSistema.objects.all()
    serializer_class = ConfiguracionSistemaSerializer
    permission_classes = [IsAuthenticated, HasValidBranch, HasAdminRole]


class AlertaViewSet(viewsets.ModelViewSet):
    serializer_class = AlertaInventarioSerializer
    filterset_fields = ['tipo_alerta', 'resuelto']
    http_method_names = ['get', 'patch', 'post']

    def get_queryset(self):
        return AlertaInventario.objects.select_related('producto').filter(
            sucursal=self.request.branch_id
        )

    def create(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        no_leidas = AlertaInventario.objects.filter(resuelto=False, sucursal=request.branch_id).count()
        
        return Response({
            'count': len(serializer.data),
            'no_leidas': no_leidas,
            'results': serializer.data,
        })

    @action(detail=False, methods=['post'])
    def refrescar(self, request):
        from .alertas import (
            generar_high_rotation,
            generar_low_stock,
            generar_old_product,
            generar_unusual_movement,
        )

        branch_id = request.branch_id

        total_creadas = 0
        total_resueltas = 0

        c, r = generar_low_stock(sucursal_id=branch_id)
        total_creadas += c
        total_resueltas += r

        c, r = generar_old_product(sucursal_id=branch_id)
        total_creadas += c
        total_resueltas += r

        c, r = generar_unusual_movement(sucursal_id=branch_id)
        total_creadas += c
        total_resueltas += r

        c, r = generar_high_rotation(sucursal_id=branch_id)
        total_creadas += c
        total_resueltas += r

        no_leidas = AlertaInventario.objects.filter(resuelto=False, sucursal=branch_id).count()

        return Response({
            'creadas': total_creadas,
            'resueltas': total_resueltas,
            'no_leidas': no_leidas,
        })


class RegistroActividadViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RegistroActividad.objects.select_related('usuario', 'sucursal').all()
    serializer_class = RegistroActividadSerializer
    filterset_fields = ['usuario', 'accion']

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.profile.rol != 'admin':
            return qs.none()

        qs = qs.filter(sucursal=self.request.branch_id)
        fecha_inicio = self.request.query_params.get('fechaInicio')
        fecha_fin = self.request.query_params.get('fechaFin')
        
        if fecha_inicio:
            qs = qs.filter(creado__date__gte=fecha_inicio)
        if fecha_fin:
            qs = qs.filter(creado__date__lte=fecha_fin)
        return qs


@api_view(['POST'])
def chat(request):
    from utils.chatbot import obtener_agente

    pregunta = request.data.get('pregunta')
    if not pregunta:
        return Response(
            {'detail': 'El campo "pregunta" es requerido.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        agente = obtener_agente(branch_id=request.branch_id)
        resultado = agente.invoke({"input": pregunta})
        respuesta = resultado['output']
    except OutputParserException:
        agente = obtener_agente(branch_id=request.branch_id)
        resultado = agente.invoke({
            "input": f"{pregunta}\n\nResponde en texto plano sin formato."
        })
        respuesta = resultado['output']
    except Exception as e:
        return Response({'detail': str(e)}, status=500)
    return Response({'respuesta': respuesta})
