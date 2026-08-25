from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status

from productos.models import Equipo, Marca
from .models import Cliente, EquipoCliente, PerfilUsuario, Sucursal
from .serializers import UserSerializer


# ── Model Tests ──────────────────────────────────────────────────────


class ClienteModelTest(TestCase):
    def test_str(self):
        sucursal = Sucursal.objects.create(nombre='Suc Test')
        cliente = Cliente.objects.create(nombre='TestCliente', sucursal=sucursal)
        self.assertEqual(str(cliente), 'TestCliente')


class SucursalModelTest(TestCase):
    def test_str(self):
        sucursal = Sucursal.objects.create(nombre='Sucursal A')
        self.assertEqual(str(sucursal), 'Sucursal A')


class PerfilUsuarioModelTest(TestCase):
    def test_str(self):
        user = User.objects.create_user(username='juan', password='pass')
        perfil = PerfilUsuario.objects.create(usuario=user, rol='admin')
        self.assertIn('juan', str(perfil))
        self.assertIn('Administrador', str(perfil))


class EquipoClienteModelTest(TestCase):
    def test_str(self):
        marca = Marca.objects.create(nombre='MarcaX')
        equipo = Equipo.objects.create(nombre='EQ-100', marca=marca)
        sucursal = Sucursal.objects.create(nombre='Suc EC')
        cliente = Cliente.objects.create(nombre='Carlos', sucursal=sucursal)
        ec = EquipoCliente.objects.create(
            equipo=equipo, cliente=cliente, alias='Oficina', contador_uso=500
        )
        self.assertIn('EQ-100', str(ec))
        self.assertIn('Carlos', str(ec))
        self.assertIn('Oficina', str(ec))

    def test_unique_together(self):
        marca = Marca.objects.create(nombre='MarcaY')
        equipo = Equipo.objects.create(nombre='EQ-200', marca=marca)
        sucursal = Sucursal.objects.create(nombre='Suc UT')
        cliente = Cliente.objects.create(nombre='Ana', sucursal=sucursal)
        EquipoCliente.objects.create(
            equipo=equipo, cliente=cliente, alias='Taller', contador_uso=100
        )
        with self.assertRaises(Exception):
            EquipoCliente.objects.create(
                equipo=equipo, cliente=cliente, alias='Duplicado', contador_uso=200
            )


# ── Serializer Tests ─────────────────────────────────────────────────


class UserSerializerTest(TestCase):
    def test_full_name_uses_get_full_name(self):
        user = User.objects.create_user(
            username='testuser', password='pass',
            first_name='Juan', last_name='Perez'
        )
        serializer = UserSerializer(user)
        self.assertEqual(serializer.data['full_name'], 'Juan Perez')

    def test_full_name_falls_back_to_username(self):
        user = User.objects.create_user(username='nofirstname', password='pass')
        serializer = UserSerializer(user)
        self.assertEqual(serializer.data['full_name'], 'nofirstname')

    def test_includes_profile(self):
        user = User.objects.create_user(username='profi', password='pass')
        PerfilUsuario.objects.create(usuario=user, rol='operativo', telefono='555-0100')
        serializer = UserSerializer(user)
        self.assertIn('profile', serializer.data)
        self.assertEqual(serializer.data['profile']['rol'], 'operativo')
        self.assertEqual(serializer.data['profile']['telefono'], '555-0100')


# ── ViewSet Tests ────────────────────────────────────────────────────


class ClienteViewSetTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin', password='pass')
        self.sucursal = Sucursal.objects.create(nombre='Suc Test')
        PerfilUsuario.objects.create(usuario=self.user, rol='admin')
        self.user.profile.sucursales.add(self.sucursal)
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nombre='Pedro', sucursal=self.sucursal
        )
        self.headers = {'HTTP_X_BRANCH_ID': self.sucursal.id}

    def test_list(self):
        url = reverse('cliente-list')
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['nombre'], 'Pedro')

    def test_list_filters_by_branch(self):
        otra_suc = Sucursal.objects.create(nombre='Otra Suc')
        Cliente.objects.create(nombre='Otro', sucursal=otra_suc)
        url = reverse('cliente-list')
        response = self.client.get(url, **self.headers)
        self.assertEqual(len(response.data), 1)

    def test_search(self):
        Cliente.objects.create(
            nombre='María López', rfc='XAXX010101000',
            telefono='5512345678', sucursal=self.sucursal
        )
        url = reverse('cliente-list')
        response = self.client.get(url, {'search': 'pedro'}, **self.headers)
        self.assertEqual([c['nombre'] for c in response.data], ['Pedro'])
        response = self.client.get(url, {'search': '5512345678'}, **self.headers)
        self.assertEqual([c['nombre'] for c in response.data], ['María López'])
        # Otro cliente de otra sucursal nunca aparece en la búsqueda
        response = self.client.get(url, {'search': 'maría'}, **self.headers)
        self.assertEqual(len(response.data), 1)

    def test_filter_tipo(self):
        Cliente.objects.create(
            nombre='Empresa SA', tipo='moral', sucursal=self.sucursal
        )
        url = reverse('cliente-list')
        response = self.client.get(url, {'tipo': 'moral'}, **self.headers)
        self.assertEqual([c['nombre'] for c in response.data], ['Empresa SA'])
        response = self.client.get(url, {'tipo': 'fisica'}, **self.headers)
        self.assertEqual([c['nombre'] for c in response.data], ['Pedro'])

    def test_create(self):
        url = reverse('cliente-list')
        data = {'nombre': 'Nuevo Cliente'}
        response = self.client.post(url, data, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Cliente.objects.count(), 2)

    def test_retrieve(self):
        url = reverse('cliente-detail', kwargs={'pk': self.cliente.pk})
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['nombre'], 'Pedro')

    def test_update(self):
        url = reverse('cliente-detail', kwargs={'pk': self.cliente.pk})
        data = {'nombre': 'Pedro Actualizado'}
        response = self.client.put(url, data, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.nombre, 'Pedro Actualizado')

    def test_delete(self):
        url = reverse('cliente-detail', kwargs={'pk': self.cliente.pk})
        response = self.client.delete(url, **self.headers)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT])
        self.assertEqual(Cliente.objects.count(), 0)

    def test_equipos_get(self):
        marca = Marca.objects.create(nombre='M')
        equipo = Equipo.objects.create(nombre='E-1', marca=marca)
        EquipoCliente.objects.create(
            equipo=equipo, cliente=self.cliente, alias='EQ1', contador_uso=50
        )
        url = reverse('cliente-equipos', kwargs={'pk': self.cliente.pk})
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['alias'], 'EQ1')

    def test_equipos_post(self):
        marca = Marca.objects.create(nombre='M2')
        equipo = Equipo.objects.create(nombre='E-2', marca=marca)
        url = reverse('cliente-equipos', kwargs={'pk': self.cliente.pk})
        data = {'equipoId': equipo.pk, 'contadorUso': 100, 'alias': 'Nuevo'}
        response = self.client.post(url, data, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.cliente.equipos.count(), 1)

    def test_equipos_delete_missing_equipoId(self):
        url = reverse('cliente-equipos', kwargs={'pk': self.cliente.pk})
        response = self.client.delete(url, {}, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_equipos_delete_nonexistent(self):
        url = reverse('cliente-equipos', kwargs={'pk': self.cliente.pk})
        response = self.client.delete(
            url, {'equipoId': 9999}, format='json', **self.headers
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_equipos_delete_success(self):
        marca = Marca.objects.create(nombre='M3')
        equipo = Equipo.objects.create(nombre='E-3', marca=marca)
        ec = EquipoCliente.objects.create(
            equipo=equipo, cliente=self.cliente, alias='Del', contador_uso=10
        )
        url = reverse('cliente-equipos', kwargs={'pk': self.cliente.pk})
        response = self.client.delete(
            url, {'equipoId': equipo.pk}, format='json', **self.headers
        )
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT])
        self.assertEqual(self.cliente.equipos.count(), 0)

    def test_incrementar_contador_success(self):
        marca = Marca.objects.create(nombre='M4')
        equipo = Equipo.objects.create(nombre='E-4', marca=marca)
        ec = EquipoCliente.objects.create(
            equipo=equipo, cliente=self.cliente, alias='Cont', contador_uso=100
        )
        url = reverse('cliente-incrementar-contador', kwargs={'pk': self.cliente.pk})
        response = self.client.post(
            url, {'equipoId': equipo.pk, 'cantidad': 25}, format='json', **self.headers
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['contador_uso'], 125)

    def test_incrementar_contador_missing_params(self):
        url = reverse('cliente-incrementar-contador', kwargs={'pk': self.cliente.pk})
        response = self.client.post(url, {}, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_incrementar_contador_invalid_cantidad(self):
        marca = Marca.objects.create(nombre='M5')
        equipo = Equipo.objects.create(nombre='E-5', marca=marca)
        EquipoCliente.objects.create(
            equipo=equipo, cliente=self.cliente, alias='Inv', contador_uso=50
        )
        url = reverse('cliente-incrementar-contador', kwargs={'pk': self.cliente.pk})
        response = self.client.post(
            url, {'equipoId': equipo.pk, 'cantidad': 'abc'},
            format='json', **self.headers
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_incrementar_contador_negative(self):
        marca = Marca.objects.create(nombre='M6')
        equipo = Equipo.objects.create(nombre='E-6', marca=marca)
        EquipoCliente.objects.create(
            equipo=equipo, cliente=self.cliente, alias='Neg', contador_uso=50
        )
        url = reverse('cliente-incrementar-contador', kwargs={'pk': self.cliente.pk})
        response = self.client.post(
            url, {'equipoId': equipo.pk, 'cantidad': -5},
            format='json', **self.headers
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_incrementar_contador_nonexistent_equipo(self):
        url = reverse('cliente-incrementar-contador', kwargs={'pk': self.cliente.pk})
        response = self.client.post(
            url, {'equipoId': 9999, 'cantidad': 10},
            format='json', **self.headers
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UserViewSetTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin', password='pass')
        self.sucursal = Sucursal.objects.create(nombre='Suc User')
        PerfilUsuario.objects.create(usuario=self.user, rol='admin')
        self.user.profile.sucursales.add(self.sucursal)
        self.client.force_login(self.user)
        self.headers = {'HTTP_X_BRANCH_ID': self.sucursal.id}

    def test_list(self):
        url = reverse('usuario-list')
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_create(self):
        url = reverse('usuario-list')
        data = {'username': 'newuser', 'password': 'pass123'}
        response = self.client.post(url, data, format='json', **self.headers)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.count(), 2)

    def test_retrieve_includes_full_name(self):
        url = reverse('usuario-detail', kwargs={'pk': self.user.pk})
        response = self.client.get(url, **self.headers)
        self.assertIn('full_name', response.data)
        self.assertIn('profile', response.data)


class SucursalViewSetTest(APITestCase):
    def setUp(self):
        self.sucursal = Sucursal.objects.create(nombre='Suc A')
        Sucursal.objects.create(nombre='Suc B')
        # No auth — SucursalViewSet has permission_classes = []

    def test_list_public(self):
        url = reverse('sucursal-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 2)

    def test_create_public(self):
        url = reverse('sucursal-list')
        data = {'nombre': 'Suc C'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
