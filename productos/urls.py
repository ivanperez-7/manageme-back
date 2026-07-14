from django.urls import path, include
from rest_framework import routers

from .views import *


router = routers.DefaultRouter()
router.register(r'productos', ProductoViewSet, basename='producto')
router.register(r'lotes', LoteViewSet, basename='lote')
router.register(r'categorias', CategoriaViewSet)
router.register(r'marcas', MarcaViewSet)
router.register(r'equipos', EquipoViewSet)
router.register(r'proveedores', ProveedorViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', dashboard_view),
    path('rendimiento/', rendimiento_view),
    path('reorden/', reorden_view),
    path('exportar/existencias/', exportar_existencias_view),
    path('exportar/rendimiento/', exportar_rendimiento_view),
    path('exportar/reorden/', exportar_reorden_view),
]
