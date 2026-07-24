from django.contrib.auth.models import User
from rest_framework import serializers

from .models import Cliente, PerfilUsuario, Sucursal


class ClienteSerializer(serializers.ModelSerializer):
    activo = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = Cliente
        fields = '__all__'
        read_only_fields = ['sucursal']

    def validate(self, attrs):
        rfc = attrs.get('rfc')
        if rfc:
            qs = Cliente.objects.filter(rfc=rfc, activo=True)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'rfc': 'Ya existe un cliente activo con ese RFC.'}
                )
        return attrs


class SucursalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sucursal
        fields = ['id', 'nombre']


class PerfilUsuarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerfilUsuario
        fields = ['rol', 'avatar', 'telefono']


class UserSerializer(serializers.ModelSerializer):
    profile = PerfilUsuarioSerializer(read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'profile', 'full_name']

    def get_full_name(self, obj: User):
        return obj.get_full_name() or obj.username
