from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase
from rest_framework import status

from organizacion.models import PerfilUsuario, Sucursal
from productos.models import Categoría, Producto, Proveedor
from .models import AlertaInventario, ConfiguracionSistema, RegistroActividad


# ── Model Tests ──────────────────────────────────────────────────────


class ConfiguracionSistemaModelTest(TestCase):
    def test_str(self):
        cfg = ConfiguracionSistema.objects.create(clave='MAX_ITEMS', valor='100')
        self.assertIn('MAX_ITEMS', str(cfg))
        self.assertIn('100', str(cfg))


class RegistroActividadModelTest(TestCase):
    def test_str(self):
        user = User.objects.create_user(username='logger', password='pass')
        sucursal = Sucursal.objects.create(nombre='Suc Test')
        reg = RegistroActividad.objects.create(
            usuario=user, accion='login', descripcion='Inicio de sesión',
            sucursal=sucursal,
        )
        self.assertIn('logger', str(reg))


class AlertaInventarioModelTest(TestCase):
    def test_str(self):
        cat = Categoría.objects.create(nombre='Cat Alerta')
        prov = Proveedor.objects.create(nombre='Prov Alerta')
        producto = Producto.objects.create(
            codigo_interno='P-ALERT', descripcion='Test', categoria=cat,
            unidad_medida='pieza', sku='SKU-ALERT', min_stock=5, proveedor=prov,
        )
        alerta = AlertaInventario.objects.create(
            producto=producto, tipo_alerta='low_stock', mensaje='Stock bajo', sucursal_id=1
        )
        self.assertIn('Bajo stock', str(alerta))
        self.assertIn('P-ALERT', str(alerta))


# ── Endpoint Tests ───────────────────────────────────────────────────


class SystemEndpointTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user', password='pass')
        self.sucursal = Sucursal.objects.create(nombre='Suc Sys')
        PerfilUsuario.objects.create(usuario=self.user, rol='admin')
        self.user.profile.sucursales.add(self.sucursal)

    def test_me_returns_profile(self):
        self.client.force_login(self.user)
        url = reverse('me')
        response = self.client.get(url, HTTP_X_BRANCH_ID=self.sucursal.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('username', response.data)
        self.assertEqual(response.data['username'], 'user')
        self.assertIn('profile', response.data)

    def test_me_returns_404_without_profile(self):
        no_profile_user = User.objects.create_user(username='noprofile', password='pass')
        self.client.force_login(no_profile_user)
        url = reverse('me')
        response = self.client.get(url, HTTP_X_BRANCH_ID=self.sucursal.id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_me_requires_auth(self):
        url = reverse('me')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_clears_cookie(self):
        self.client.force_login(self.user)
        url = reverse('logout')
        response = self.client.post(url, HTTP_X_BRANCH_ID=self.sucursal.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # The refresh_token cookie should be set to empty
        self.assertIn('refresh_token', response.cookies)
        self.assertEqual(response.cookies['refresh_token'].value, '')

    def test_logout_requires_auth(self):
        url = reverse('logout')
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_refresh_missing_cookie(self):
        url = reverse('token_refresh')
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('Refresh token not found', str(response.data['detail']))


# ── Configuracion ViewSet Tests ──────────────────────────────────────


class ConfiguracionViewSetTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cfguser', password='pass')
        self.sucursal = Sucursal.objects.create(nombre='Suc Cfg')
        PerfilUsuario.objects.create(usuario=self.user, rol='admin')
        self.user.profile.sucursales.add(self.sucursal)
        self.client.force_login(self.user)
        self.headers = {'HTTP_X_BRANCH_ID': self.sucursal.id}

    def test_list(self):
        ConfiguracionSistema.objects.create(clave='KEY1', valor='val1')
        ConfiguracionSistema.objects.create(clave='KEY2', valor='val2')
        url = reverse('configuracion-list')
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_create(self):
        url = reverse('configuracion-list')
        data = {'clave': 'NEW_KEY', 'valor': 'new_val'}
        response = self.client.post(url, data, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConfiguracionSistema.objects.count(), 1)


# ── Alertas ViewSet Tests ────────────────────────────────────────────


class AlertaViewSetTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='altuser', password='pass')
        self.sucursal = Sucursal.objects.create(nombre='Suc Alt')
        PerfilUsuario.objects.create(usuario=self.user, rol='admin')
        self.user.profile.sucursales.add(self.sucursal)
        self.client.force_login(self.user)
        self.headers = {'HTTP_X_BRANCH_ID': self.sucursal.id}

        cat = Categoría.objects.create(nombre='Cat Alerta')
        prov = Proveedor.objects.create(nombre='Prov Alerta')
        self.producto = Producto.objects.create(
            codigo_interno='P-ALT', descripcion='Test', categoria=cat,
            unidad_medida='pieza', sku='SKU-ALT', min_stock=5, proveedor=prov,
        )

    def test_list_returns_custom_format(self):
        AlertaInventario.objects.create(
            producto=self.producto, tipo_alerta='low_stock', mensaje='Bajo', sucursal_id=1
        )
        url = reverse('alertas-list')
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('no_leidas', response.data)
        self.assertIn('results', response.data)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['no_leidas'], 0)

    def test_create_returns_405(self):
        url = reverse('alertas-list')
        data = {'producto': self.producto.pk, 'tipo_alerta': 'low_stock', 'mensaje': 'Test'}
        response = self.client.post(url, data, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_update_returns_405(self):
        alerta = AlertaInventario.objects.create(
            producto=self.producto, tipo_alerta='low_stock', mensaje='Bajo', sucursal_id=1
        )
        url = reverse('alertas-detail', kwargs={'pk': alerta.pk})
        data = {'resuelto': True}
        response = self.client.put(url, data, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_destroy_returns_405(self):
        alerta = AlertaInventario.objects.create(
            producto=self.producto, tipo_alerta='low_stock', mensaje='Bajo', sucursal_id=1
        )
        url = reverse('alertas-detail', kwargs={'pk': alerta.pk})
        response = self.client.delete(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    @patch('system.alertas.generar_low_stock', return_value=(0, 0))
    @patch('system.alertas.generar_unusual_movement', return_value=(0, 0))
    @patch('system.alertas.generar_high_rotation', return_value=(0, 0))
    def test_refrescar_runs_all_generators(
        self, mock_hr, mock_um, mock_ls
    ):
        url = reverse('alertas-refrescar')
        response = self.client.post(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('creadas', response.data)
        self.assertIn('resueltas', response.data)
        self.assertIn('no_leidas', response.data)
        mock_ls.assert_called_once_with(sucursal_id=self.sucursal.id)
        mock_um.assert_called_once_with(sucursal_id=self.sucursal.id)
        mock_hr.assert_called_once_with(sucursal_id=self.sucursal.id)


class RegistroActividadViewSetTest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass')
        self.sucursal = Sucursal.objects.create(nombre='Suc Act')
        PerfilUsuario.objects.create(usuario=self.admin, rol='admin')
        self.admin.profile.sucursales.add(self.sucursal)
        self.client.force_login(self.admin)
        self.headers = {'HTTP_X_BRANCH_ID': self.sucursal.id}

    def _crear_registros(self):
        for i in range(3):
            RegistroActividad.objects.create(
                usuario=self.admin, accion='create',
                descripcion=f'Test #{i}',
                sucursal=self.sucursal,
            )

    def test_list_requires_admin(self):
        oper = User.objects.create_user(username='oper', password='pass')
        PerfilUsuario.objects.create(usuario=oper, rol='operativo')
        oper.profile.sucursales.add(self.sucursal)
        self.client.force_login(oper)

        self._crear_registros()
        url = reverse('actividades-list')
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_list_returns_all_for_admin(self):
        self._crear_registros()
        url = reverse('actividades-list')
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)

    def test_filter_by_accion(self):
        RegistroActividad.objects.create(
            usuario=self.admin, accion='create', descripcion='Creación',
            sucursal=self.sucursal,
        )
        RegistroActividad.objects.create(
            usuario=self.admin, accion='update', descripcion='Modificación',
            sucursal=self.sucursal,
        )
        url = reverse('actividades-list')
        response = self.client.get(f'{url}?accion=create', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_filter_by_fecha(self):
        from django.utils import timezone
        hace_un_mes = timezone.now() - timezone.timedelta(days=30)
        RegistroActividad.objects.create(
            usuario=self.admin, accion='create', descripcion='Viejo',
            creado=hace_un_mes, sucursal=self.sucursal,
        )
        RegistroActividad.objects.create(
            usuario=self.admin, accion='create', descripcion='Reciente',
            sucursal=self.sucursal,
        )
        ayer = (timezone.now() - timezone.timedelta(days=1)).date()
        url = reverse('actividades-list')
        response = self.client.get(f'{url}?fechaInicio={ayer.isoformat()}', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_serializer_includes_usuario_nombre(self):
        RegistroActividad.objects.create(
            usuario=self.admin, accion='create', descripcion='Test',
            sucursal=self.sucursal,
        )
        url = reverse('actividades-list')
        response = self.client.get(url, **self.headers)
        self.assertIn('usuario_nombre', response.data[0])
        self.assertEqual(response.data[0]['usuario_nombre'], 'admin')
