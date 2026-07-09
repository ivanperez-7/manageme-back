from unittest.mock import patch
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.serializers import ValidationError
from rest_framework.test import APITestCase, APIRequestFactory
from rest_framework import status

from organizacion.models import Cliente, EquipoCliente, PerfilUsuario, Sucursal
from productos.models import Categoría, Equipo, Lote, Marca, Producto, Proveedor, Unidad
from .models import DetalleEntrada, DetalleSalida, Movimiento, MovimientoItem
from .serializers import MovimientoSerializer


def _create_admin():
    user = User.objects.create_user(username='admin', password='pass')
    PerfilUsuario.objects.create(usuario=user, rol='admin')
    return user


def _create_operativo():
    user = User.objects.create_user(username='oper', password='pass')
    PerfilUsuario.objects.create(usuario=user, rol='operativo')
    return user


def _create_producto(codigo='P001', vida_util_unidades=5, vida_util_dias=None):
    categoria, _ = Categoría.objects.get_or_create(nombre=f'TestCat-{codigo}')
    proveedor, _ = Proveedor.objects.get_or_create(nombre=f'TestProv-{codigo}')
    return Producto.objects.create(
        codigo_interno=codigo,
        descripcion='Test Producto',
        categoria=categoria,
        unidad_medida='pieza',
        sku=f'SKU-{codigo}',
        min_stock=10,
        proveedor=proveedor,
        vida_util_unidades=vida_util_unidades,
        vida_util_dias=vida_util_dias,
    )


# ── Model Tests ──────────────────────────────────────────────────────


class MovimientoModelTest(TestCase):
    def setUp(self):
        self.admin = _create_admin()
        self.admin.profile.sucursales.add(1)
        self.producto = _create_producto()
        self.movimiento = Movimiento.objects.create(
            tipo='entrada', creado_por=self.admin, sucursal_id=1
        )

    def test_str(self):
        self.assertIn('Movimiento', str(self.movimiento))
        self.assertIn(str(self.movimiento.id), str(self.movimiento))

    def test_approve_entrada_rejects_non_admin(self):
        oper = _create_operativo()
        MovimientoItem.objects.create(
            movimiento=self.movimiento, producto=self.producto, cantidad=5
        )
        with self.assertRaises(PermissionError):
            self.movimiento.approve(oper)

    def test_approve_rejects_duplicate(self):
        detalle = DetalleEntrada.objects.create(
            movimiento=self.movimiento,
            numero_factura='F001',
            recibido_por=self.admin,
        )
        MovimientoItem.objects.create(
            movimiento=self.movimiento, producto=self.producto, cantidad=5
        )
        self.movimiento.aprobado = True
        self.movimiento.save()
        with self.assertRaises(ValueError):
            self.movimiento.approve(self.admin)

    @patch('movimiento.models.validar_factura_entrada')
    @patch('movimiento.models.MovimientoItem.crear_lote')
    def test_approve_entrada_calls_crear_lote(self, mock_crear_lote, mock_val):
        mock_val.return_value = True
        DetalleEntrada.objects.create(
            movimiento=self.movimiento,
            numero_factura='F001',
            recibido_por=self.admin,
        )
        MovimientoItem.objects.create(
            movimiento=self.movimiento, producto=self.producto, cantidad=5
        )
        self.movimiento.approve(self.admin)
        mock_crear_lote.assert_called_once()

    def test_approve_salida_calls_asignar_unidades(self):
        producto = _create_producto(codigo='P002')
        lote = Lote.objects.create(
            producto=producto, codigo_lote='L-APR', cantidad_inicial=10, sucursal_id=1
        )
        for _ in range(10):
            Unidad.objects.create(lote=lote)

        sucursal = Sucursal.objects.create(nombre='Suc Test')
        cliente = Cliente.objects.create(nombre='TestCliente', sucursal=sucursal)
        equipo = Equipo.objects.create(nombre='EQ-TEST', marca=Marca.objects.create(nombre='M'))
        equipo_cliente = EquipoCliente.objects.create(
            equipo=equipo, cliente=cliente, alias='EQ1', contador_uso=100
        )
        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        DetalleSalida.objects.create(movimiento=movimiento, cliente=cliente, subtipo='venta')
        item = MovimientoItem.objects.create(
            movimiento=movimiento,
            producto=producto,
            cantidad=3,
            lote=lote,
            equipo_cliente=equipo_cliente,
        )

        movimiento.approve(self.admin)

        self.assertTrue(movimiento.aprobado)
        self.assertEqual(
            Unidad.objects.filter(lote=lote, status='retirada').count(), 3
        )
        # Venta no chequea contadores → no se guarda snapshot.
        item.refresh_from_db()
        self.assertIsNone(item.contador_uso_snapshot)

    def test_approve_salida_renta_sets_snapshot(self):
        producto = _create_producto(codigo='P002R')
        lote = Lote.objects.create(
            producto=producto, codigo_lote='L-RENTA', cantidad_inicial=10, sucursal_id=1
        )
        for _ in range(10):
            Unidad.objects.create(lote=lote)

        sucursal = Sucursal.objects.create(nombre='Suc Renta')
        cliente = Cliente.objects.create(nombre='ClienteRenta', sucursal=sucursal)
        equipo = Equipo.objects.create(nombre='EQ-R', marca=Marca.objects.create(nombre='MR'))
        equipo_cliente = EquipoCliente.objects.create(
            equipo=equipo, cliente=cliente, alias='EQR', contador_uso=100
        )
        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        DetalleSalida.objects.create(movimiento=movimiento, cliente=cliente, subtipo='renta')
        item = MovimientoItem.objects.create(
            movimiento=movimiento,
            producto=producto,
            cantidad=1,
            lote=lote,
            equipo_cliente=equipo_cliente,
        )

        movimiento.approve(self.admin)

        # Renta SÍ chequea contadores y guarda el snapshot del contador_uso.
        item.refresh_from_db()
        self.assertEqual(item.contador_uso_snapshot, 100)

    def test_approve_salida_venta_skips_vida_util_check(self):
        producto = _create_producto(codigo='P002V', vida_util_unidades=999)
        lote = Lote.objects.create(
            producto=producto, codigo_lote='L-VENTA', cantidad_inicial=10, sucursal_id=1
        )
        for _ in range(10):
            Unidad.objects.create(lote=lote)

        sucursal = Sucursal.objects.create(nombre='Suc Venta')
        cliente = Cliente.objects.create(nombre='ClienteVenta', sucursal=sucursal)
        equipo = Equipo.objects.create(nombre='EQ-V', marca=Marca.objects.create(nombre='MV'))
        equipo_cliente = EquipoCliente.objects.create(
            equipo=equipo, cliente=cliente, alias='EQV', contador_uso=51
        )
        # Entrega previa de renta con snapshot=50: uso=1 < vida_util=999 ⇒ una RENTA
        # fallaría aquí. Como es venta, no se chequea y aprueba sin error.
        prev_mov = Movimiento.objects.create(
            tipo='salida', creado_por=self.admin,
            creado=timezone.now() - timezone.timedelta(days=30),
            aprobado=True, sucursal_id=1,
        )
        DetalleSalida.objects.create(movimiento=prev_mov, cliente=cliente, subtipo='renta')
        MovimientoItem.objects.create(
            movimiento=prev_mov, producto=producto, cantidad=1,
            lote=lote, equipo_cliente=equipo_cliente, contador_uso_snapshot=50,
        )

        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        DetalleSalida.objects.create(movimiento=movimiento, cliente=cliente, subtipo='venta')
        MovimientoItem.objects.create(
            movimiento=movimiento, producto=producto, cantidad=1,
            lote=lote, equipo_cliente=equipo_cliente,
        )

        movimiento.approve(self.admin)
        self.assertTrue(movimiento.aprobado)

    def test_approve_salida_rejects_insufficient_units(self):
        producto = _create_producto(codigo='P003')
        lote = Lote.objects.create(
            producto=producto, codigo_lote='L-SHORT', cantidad_inicial=2, sucursal_id=1
        )
        for _ in range(2):
            Unidad.objects.create(lote=lote)

        sucursal = Sucursal.objects.create(nombre='Suc Test2')
        cliente = Cliente.objects.create(nombre='Cliente2', sucursal=sucursal)
        equipo = Equipo.objects.create(nombre='EQ2', marca=Marca.objects.create(nombre='M2'))
        equipo_cliente = EquipoCliente.objects.create(
            equipo=equipo, cliente=cliente, alias='EQ2', contador_uso=50
        )
        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        DetalleSalida.objects.create(movimiento=movimiento, cliente=cliente)
        MovimientoItem.objects.create(
            movimiento=movimiento,
            producto=producto,
            cantidad=5,
            lote=lote,
            equipo_cliente=equipo_cliente,
        )

        with self.assertRaises(ValueError):
            movimiento.approve(self.admin)


class MovimientoItemModelTest(TestCase):
    def setUp(self):
        self.admin = _create_admin()
        self.producto = _create_producto(vida_util_unidades=3)
        self.movimiento = Movimiento.objects.create(tipo='entrada', creado_por=self.admin, sucursal_id=1)

    def test_str(self):
        item = MovimientoItem.objects.create(
            movimiento=self.movimiento, producto=self.producto, cantidad=10
        )
        self.assertIn('P001', str(item))

    def test_crear_lote_creates_unidades(self):
        item = MovimientoItem.objects.create(
            movimiento=self.movimiento, producto=self.producto, cantidad=7
        )
        lote = item.crear_lote()
        self.assertEqual(lote.cantidad_inicial, 7)
        self.assertEqual(Unidad.objects.filter(lote=lote).count(), 7)

    def test_save_validates_lote_producto_match(self):
        otro_producto = _create_producto(codigo='P-OTHER')
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-MATCH', cantidad_inicial=5, sucursal_id=1
        )
        item = MovimientoItem(
            movimiento=self.movimiento, producto=otro_producto, cantidad=1, lote=lote
        )
        with self.assertRaises(ValueError):
            item.save()

    def test_asignar_unidades_marks_as_retirada(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-ASIGN', cantidad_inicial=10, sucursal_id=1
        )
        for _ in range(10):
            Unidad.objects.create(lote=lote)

        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        item = MovimientoItem.objects.create(
            movimiento=movimiento, producto=self.producto, cantidad=4, lote=lote
        )

        asignadas = item.asignar_unidades()
        self.assertEqual(len(asignadas), 4)
        self.assertEqual(
            Unidad.objects.filter(lote=lote, status='retirada').count(), 4
        )

    def test_asignar_unidades_raises_if_not_enough(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-LOW', cantidad_inicial=1, sucursal_id=1
        )
        Unidad.objects.create(lote=lote)

        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        item = MovimientoItem.objects.create(
            movimiento=movimiento, producto=self.producto, cantidad=10, lote=lote
        )

        with self.assertRaises(ValueError):
            item.asignar_unidades()

    def test_asignar_unidades_raises_if_no_lote(self):
        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        item = MovimientoItem.objects.create(
            movimiento=movimiento, producto=self.producto, cantidad=1
        )
        with self.assertRaises(ValueError):
            item.asignar_unidades()

    def test_verificar_vida_util_raises_if_no_equipo_cliente(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-VU', cantidad_inicial=5, sucursal_id=1
        )
        for _ in range(5):
            Unidad.objects.create(lote=lote)

        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        item = MovimientoItem.objects.create(
            movimiento=movimiento, producto=self.producto, cantidad=1, lote=lote
        )
        with self.assertRaises(ValueError):
            item.verificar_vida_util()

    def test_verificar_vida_util_passes_with_sufficient_usage(self):
        sucursal = Sucursal.objects.create(nombre='Suc VU')
        cliente = Cliente.objects.create(nombre='Cliente VU', sucursal=sucursal)
        equipo = Equipo.objects.create(nombre='EQ-VU', marca=Marca.objects.create(nombre='MVU'))
        eq_cli = EquipoCliente.objects.create(
            equipo=equipo, cliente=cliente, alias='EQ-VU', contador_uso=100
        )
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-VU2', cantidad_inicial=5, sucursal_id=1
        )
        for _ in range(5):
            Unidad.objects.create(lote=lote)

        # Simulate a previous delivery with snapshot at 50
        prev_mov = Movimiento.objects.create(
            tipo='salida', creado_por=self.admin,
            creado=timezone.now() - timezone.timedelta(days=30),
            aprobado=True, sucursal_id=1,
        )
        DetalleSalida.objects.create(movimiento=prev_mov, cliente=cliente)
        prev_item = MovimientoItem.objects.create(
            movimiento=prev_mov,
            producto=self.producto,
            cantidad=1,
            lote=lote,
            equipo_cliente=eq_cli,
            contador_uso_snapshot=50,
        )

        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        DetalleSalida.objects.create(movimiento=movimiento, cliente=cliente)
        item = MovimientoItem.objects.create(
            movimiento=movimiento,
            producto=self.producto,
            cantidad=1,
            lote=lote,
            equipo_cliente=eq_cli,
        )

        # contador_uso=100, last snapshot=50 → usage=50, vida_util=3 → enough
        result = item.verificar_vida_util()
        self.assertIsNone(result)  # completes without error
        self.assertEqual(item.contador_uso_snapshot, 100)

    def test_verificar_vida_util_raises_if_insufficient_usage(self):
        sucursal = Sucursal.objects.create(nombre='Suc VU2')
        cliente = Cliente.objects.create(nombre='Cliente VU2', sucursal=sucursal)
        equipo = Equipo.objects.create(nombre='EQ-VU2', marca=Marca.objects.create(nombre='MVU2'))
        eq_cli = EquipoCliente.objects.create(
            equipo=equipo, cliente=cliente, alias='EQ-VU2', contador_uso=52
        )
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-VU3', cantidad_inicial=5, sucursal_id=1
        )
        for _ in range(5):
            Unidad.objects.create(lote=lote)

        # contador_uso=52, last snapshot at 50 → usage=2, vida_util=3 → not enough
        prev_mov = Movimiento.objects.create(
            tipo='salida', creado_por=self.admin,
            creado=timezone.now() - timezone.timedelta(days=30),
            aprobado=True, sucursal_id=1,
        )
        DetalleSalida.objects.create(movimiento=prev_mov, cliente=cliente)
        prev_item = MovimientoItem.objects.create(
            movimiento=prev_mov,
            producto=self.producto,
            cantidad=1,
            lote=lote,
            equipo_cliente=eq_cli,
            contador_uso_snapshot=50,
        )

        movimiento = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        DetalleSalida.objects.create(movimiento=movimiento, cliente=cliente)
        item = MovimientoItem.objects.create(
            movimiento=movimiento,
            producto=self.producto,
            cantidad=1,
            lote=lote,
            equipo_cliente=eq_cli,
        )

        with self.assertRaises(ValueError):
            item.verificar_vida_util()

    def _setup_dias(self, vida_util_dias, vida_util_unidades, dias_prev):
        """Crea producto por-tiempo, entrega previa 'dias_prev' días atrás y una
        entrega actual (hoy). contador_uso no cambia (uso=0) para aislar el eje días."""
        producto = _create_producto(
            codigo=f'PD{dias_prev}-{vida_util_dias}',
            vida_util_unidades=vida_util_unidades, vida_util_dias=vida_util_dias,
        )
        cliente = Cliente.objects.create(
            nombre=f'Cli D{dias_prev}', sucursal=Sucursal.objects.create(nombre=f'Suc D{dias_prev}')
        )
        equipo = Equipo.objects.create(nombre=f'EQ-D{dias_prev}', marca=Marca.objects.create(nombre=f'MD{dias_prev}'))
        eq_cli = EquipoCliente.objects.create(equipo=equipo, cliente=cliente, alias='A', contador_uso=50)
        lote = Lote.objects.create(producto=producto, codigo_lote=f'LD{dias_prev}', cantidad_inicial=5, sucursal_id=1)
        for _ in range(5):
            Unidad.objects.create(lote=lote)

        prev_mov = Movimiento.objects.create(
            tipo='salida', creado_por=self.admin, aprobado=True, sucursal_id=1,
            creado=timezone.now() - timezone.timedelta(days=dias_prev),
        )
        DetalleSalida.objects.create(movimiento=prev_mov, cliente=cliente, subtipo='renta')
        MovimientoItem.objects.create(
            movimiento=prev_mov, producto=producto, cantidad=1,
            lote=lote, equipo_cliente=eq_cli, contador_uso_snapshot=50,
        )
        mov = Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal_id=1)
        DetalleSalida.objects.create(movimiento=mov, cliente=cliente, subtipo='renta')
        return MovimientoItem.objects.create(
            movimiento=mov, producto=producto, cantidad=1, lote=lote, equipo_cliente=eq_cli,
        )

    def test_vida_util_passes_by_dias_when_units_insufficient(self):
        # unidades=1000 (uso=0, nunca alcanza), dias=30, entrega previa hace 40 días → agotado por días
        item = self._setup_dias(vida_util_dias=30, vida_util_unidades=1000, dias_prev=40)
        item.verificar_vida_util()  # no lanza
        item.refresh_from_db()
        self.assertEqual(item.contador_uso_snapshot, 50)

    def test_vida_util_raises_when_neither_threshold_reached(self):
        # unidades=1000 (uso=0) y dias=30 pero solo pasaron 10 días → ninguno alcanzado
        item = self._setup_dias(vida_util_dias=30, vida_util_unidades=1000, dias_prev=10)
        with self.assertRaises(ValueError):
            item.verificar_vida_util()


class DetalleEntradaModelTest(TestCase):
    def test_str(self):
        admin = _create_admin()
        mov = Movimiento.objects.create(tipo='entrada', creado_por=admin, sucursal_id=1)
        detalle = DetalleEntrada.objects.create(
            movimiento=mov, numero_factura='F001', recibido_por=admin
        )
        self.assertIn(str(mov.id), str(detalle))


class DetalleSalidaModelTest(TestCase):
    def test_str(self):
        admin = _create_admin()
        sucursal = Sucursal.objects.create(nombre='Suc DS')
        cliente = Cliente.objects.create(nombre='Cliente DS', sucursal=sucursal)
        mov = Movimiento.objects.create(tipo='salida', creado_por=admin, sucursal_id=1)
        detalle = DetalleSalida.objects.create(movimiento=mov, cliente=cliente)
        self.assertIn(str(mov.id), str(detalle))


# ── Serializer Tests ─────────────────────────────────────────────────


class MovimientoSerializerTest(APITestCase):
    def setUp(self):
        self.admin = _create_admin()
        self.factory = APIRequestFactory()
        self.request = self.factory.post('/')
        self.request.user = self.admin
        self.request.branch_id = 1
        self.producto = _create_producto()

    def test_validate_items_rejects_empty(self):
        data = {
            'tipo': 'entrada',
            'items': [],
            'detalle_entrada': {'numero_factura': 'F001', 'recibido_por_id': self.admin.pk},
        }
        serializer = MovimientoSerializer(data=data, context={'request': self.request})
        self.assertFalse(serializer.is_valid())
        self.assertIn('items', serializer.errors)

    @patch('movimiento.models.validar_factura_entrada')
    def test_validate_entrada_requires_detalle_entrada(self, mock_val):
        mock_val.return_value = True
        data = {
            'tipo': 'entrada',
            'items': [{'producto_id': self.producto.pk, 'cantidad': 5}],
        }
        serializer = MovimientoSerializer(data=data, context={'request': self.request})
        self.assertFalse(serializer.is_valid())
        self.assertIn('El detalle de entrada es requerido', str(serializer.errors))

    def test_validate_salida_requires_detalle_salida(self):
        data = {
            'tipo': 'salida',
            'items': [{'producto_id': self.producto.pk, 'cantidad': 5}],
        }
        serializer = MovimientoSerializer(data=data, context={'request': self.request})
        self.assertFalse(serializer.is_valid())
        self.assertIn('El detalle de salida es requerido', str(serializer.errors))

    def test_validate_salida_checks_unidad_availability(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-SER', cantidad_inicial=1, sucursal_id=1
        )
        Unidad.objects.create(lote=lote)

        sucursal = Sucursal.objects.create(nombre='Suc Ser')
        cliente = Cliente.objects.create(nombre='CSer', sucursal=sucursal)

        data = {
            'tipo': 'salida',
            'items': [
                {
                    'producto_id': self.producto.pk,
                    'cantidad': 99,
                    'lote_id': lote.pk,
                }
            ],
            'detalle_salida': {'cliente_id': cliente.pk, 'tecnico': 'Tec'},
        }
        serializer = MovimientoSerializer(data=data, context={'request': self.request})
        self.assertFalse(serializer.is_valid())

    def test_validate_salida_renta_requires_equipo_cliente(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-RENTAV', cantidad_inicial=5, sucursal_id=1
        )
        for _ in range(5):
            Unidad.objects.create(lote=lote)
        sucursal = Sucursal.objects.create(nombre='Suc RentaV')
        cliente = Cliente.objects.create(nombre='CRentaV', sucursal=sucursal)

        data = {
            'tipo': 'salida',
            'items': [{'producto_id': self.producto.pk, 'cantidad': 1, 'lote_id': lote.pk}],
            'detalle_salida': {'cliente_id': cliente.pk, 'subtipo': 'renta'},
        }
        serializer = MovimientoSerializer(data=data, context={'request': self.request})
        self.assertFalse(serializer.is_valid())
        self.assertIn('equipo_cliente', str(serializer.errors))

    def test_validate_salida_venta_rejects_cambio_anticipado(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-VENTAV', cantidad_inicial=5, sucursal_id=1
        )
        for _ in range(5):
            Unidad.objects.create(lote=lote)
        sucursal = Sucursal.objects.create(nombre='Suc VentaV')
        cliente = Cliente.objects.create(nombre='CVentaV', sucursal=sucursal)

        data = {
            'tipo': 'salida',
            'items': [{
                'producto_id': self.producto.pk, 'cantidad': 1, 'lote_id': lote.pk,
                'cambio_anticipado': True, 'motivo_cambio': 'x',
            }],
            'detalle_salida': {'cliente_id': cliente.pk, 'subtipo': 'venta'},
        }
        serializer = MovimientoSerializer(data=data, context={'request': self.request})
        self.assertFalse(serializer.is_valid())
        self.assertIn('cambio_anticipado', str(serializer.errors))

    def test_validate_salida_venta_succeeds_without_equipo_cliente(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-VENTAOK', cantidad_inicial=5, sucursal_id=1
        )
        for _ in range(5):
            Unidad.objects.create(lote=lote)
        sucursal = Sucursal.objects.create(nombre='Suc VentaOK')
        cliente = Cliente.objects.create(nombre='CVentaOK', sucursal=sucursal)

        data = {
            'tipo': 'salida',
            'items': [{'producto_id': self.producto.pk, 'cantidad': 1, 'lote_id': lote.pk}],
            'detalle_salida': {'cliente_id': cliente.pk, 'subtipo': 'venta'},
        }
        serializer = MovimientoSerializer(data=data, context={'request': self.request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_validate_entrada_success(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-SER2', cantidad_inicial=10, sucursal_id=1
        )
        for _ in range(10):
            Unidad.objects.create(lote=lote)

        data = {
            'tipo': 'entrada',
            'items': [{'producto_id': self.producto.pk, 'cantidad': 5}],
            'detalle_entrada': {
                'numero_factura': 'F-VALID',
                'recibido_por_id': self.admin.pk,
            },
        }
        serializer = MovimientoSerializer(data=data, context={'request': self.request})
        self.assertTrue(serializer.is_valid(), serializer.errors)


# ── ViewSet Tests ────────────────────────────────────────────────────


class MovimientoViewSetTest(APITestCase):
    def setUp(self):
        self.admin = _create_admin()
        self.sucursal = Sucursal.objects.create(nombre='Suc ViewSet')
        self.admin.profile.sucursales.add(self.sucursal)
        self.client.force_login(self.admin)
        self.producto = _create_producto()

    def _post(self, url, data):
        return self.client.post(url, data, format='json',
                                HTTP_X_BRANCH_ID=self.sucursal.id)

    def _get(self, url):
        return self.client.get(url, HTTP_X_BRANCH_ID=self.sucursal.id)

    def test_create_entrada(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-VIEW', cantidad_inicial=10, sucursal=self.sucursal
        )
        for _ in range(10):
            Unidad.objects.create(lote=lote)

        url = reverse('movimientos-list')
        data = {
            'tipo': 'entrada',
            'items': [{'producto_id': self.producto.pk, 'cantidad': 5}],
            'detalle_entrada': {
                'numero_factura': 'F-VIEW',
                'recibido_por_id': self.admin.pk,
            },
        }
        response = self._post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_salida(self):
        lote = Lote.objects.create(
            producto=self.producto, codigo_lote='L-VIEW2', cantidad_inicial=10, sucursal=self.sucursal
        )
        for _ in range(10):
            Unidad.objects.create(lote=lote)

        cliente = Cliente.objects.create(nombre='CView', sucursal=self.sucursal)

        url = reverse('movimientos-list')
        data = {
            'tipo': 'salida',
            'items': [
                {
                    'producto_id': self.producto.pk,
                    'cantidad': 3,
                    'lote_id': lote.pk,
                }
            ],
            'detalle_salida': {'cliente_id': cliente.pk, 'tecnico': 'Tec', 'subtipo': 'venta'},
        }
        response = self._post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('movimiento.models.validar_factura_entrada')
    def test_aprobar_endpoint_success(self, mock_val):
        mock_val.return_value = True
        movimiento = Movimiento.objects.create(tipo='entrada', creado_por=self.admin, sucursal=self.sucursal)
        DetalleEntrada.objects.create(
            movimiento=movimiento, numero_factura='F-APR', recibido_por=self.admin
        )
        MovimientoItem.objects.create(
            movimiento=movimiento, producto=self.producto, cantidad=5
        )

        url = reverse('movimientos-aprobar', kwargs={'pk': movimiento.pk})
        response = self._post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'status': 'aprobado'})
        movimiento.refresh_from_db()
        self.assertTrue(movimiento.aprobado)

    def test_aprobar_endpoint_rejects_non_admin(self):
        oper = _create_operativo()
        oper.profile.sucursales.add(self.sucursal)
        self.client.force_login(oper)

        movimiento = Movimiento.objects.create(tipo='entrada', creado_por=self.admin, sucursal=self.sucursal)
        DetalleEntrada.objects.create(
            movimiento=movimiento, numero_factura='F-REJ', recibido_por=self.admin
        )
        MovimientoItem.objects.create(
            movimiento=movimiento, producto=self.producto, cantidad=5
        )

        url = reverse('movimientos-aprobar', kwargs={'pk': movimiento.pk})
        response = self._post(url, {})
        self.assertEqual(response.status_code, 403)
        self.assertIn('Solo administradores', str(response.data['detail']))

    def test_aprobar_endpoint_rejects_duplicate(self):
        movimiento = Movimiento.objects.create(
            tipo='entrada', creado_por=self.admin, aprobado=True, sucursal=self.sucursal
        )
        DetalleEntrada.objects.create(
            movimiento=movimiento, numero_factura='F-DUP', recibido_por=self.admin
        )
        MovimientoItem.objects.create(
            movimiento=movimiento, producto=self.producto, cantidad=5
        )

        url = reverse('movimientos-aprobar', kwargs={'pk': movimiento.pk})
        response = self._post(url, {})
        self.assertEqual(response.status_code, 400)
        self.assertIn('ya aprobado', str(response.data['detail']))

    @patch('movimiento.models.validar_factura_entrada')
    def test_aprobar_endpoint_rejects_invalid_factura(self, mock_val):
        mock_val.side_effect = ValidationError('Factura invalida')
        movimiento = Movimiento.objects.create(tipo='entrada', creado_por=self.admin, sucursal=self.sucursal)
        DetalleEntrada.objects.create(
            movimiento=movimiento, numero_factura='F-BAD', recibido_por=self.admin
        )
        MovimientoItem.objects.create(
            movimiento=movimiento, producto=self.producto, cantidad=5
        )

        url = reverse('movimientos-aprobar', kwargs={'pk': movimiento.pk})
        response = self._post(url, {})
        self.assertEqual(response.status_code, 500)
        self.assertIn('Factura invalida', str(response.data['detail']))
        movimiento.refresh_from_db()
        self.assertFalse(movimiento.aprobado)

    def test_list_returns_movimientos(self):
        Movimiento.objects.create(tipo='entrada', creado_por=self.admin, sucursal=self.sucursal)
        Movimiento.objects.create(tipo='salida', creado_por=self.admin, sucursal=self.sucursal)
        url = reverse('movimientos-list')
        response = self._get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_list_filters_by_date(self):
        old = Movimiento.objects.create(
            tipo='entrada', creado_por=self.admin, sucursal=self.sucursal,
            creado=timezone.now() - timezone.timedelta(days=60),
        )
        recent = Movimiento.objects.create(
            tipo='entrada', creado_por=self.admin, sucursal=self.sucursal,
        )
        url = reverse('movimientos-list')
        today = timezone.now().date()
        response = self._get(f'{url}?fechaInicio={today.isoformat()}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], recent.pk)

    def test_get_oldest_returns_date(self):
        Movimiento.objects.create(
            tipo='entrada', creado_por=self.admin, sucursal=self.sucursal,
            creado=timezone.now() - timezone.timedelta(days=100),
        )
        url = reverse('movimientos-get-oldest')
        response = self._get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, (timezone.now() - timezone.timedelta(days=100)).date())

    def test_retrieve_returns_movimiento(self):
        movimiento = Movimiento.objects.create(tipo='entrada', creado_por=self.admin, sucursal=self.sucursal)
        url = reverse('movimientos-detail', kwargs={'pk': movimiento.pk})
        response = self._get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], movimiento.pk)

    def test_exportar_xlsx(self):
        import io
        from openpyxl import load_workbook

        movimiento = Movimiento.objects.create(tipo='entrada', creado_por=self.admin, sucursal=self.sucursal)
        MovimientoItem.objects.create(movimiento=movimiento, producto=self.producto, cantidad=7)

        url = reverse('movimientos-exportar')
        response = self._get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        ws = load_workbook(io.BytesIO(response.content)).active
        self.assertEqual(
            [c.value for c in ws[1]],
            ['ID', 'Tipo', 'Fecha', 'Aprobado', 'Producto', 'Cantidad'],
        )
        fila = [c.value for c in ws[2]]
        self.assertEqual(fila[0], movimiento.pk)
        self.assertEqual(fila[4], self.producto.codigo_interno)
        self.assertEqual(fila[5], 7)
