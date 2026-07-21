from system.models import RegistroActividad


class ActivityLogMixin:
    """Registra automáticamente operaciones CRUD en RegistroActividad.

    Los métodos perform_* llaman a self.log() que a su vez llama
    a get_log_description() para formatear el mensaje con el artículo
    (el/la) y el verbose_name del modelo.
    """

    verbs = {'create': 'Creó', 'update': 'Modificó', 'delete': 'Eliminó'}

    # Modelos cuyo verbose_name lleva artículo femenino
    _feminine = {'categoría', 'marca', 'sucursal'}

    def _article(self, instance):
        name = instance._meta.verbose_name.lower()
        return 'la' if name in self._feminine else 'el'

    def get_log_description(self, instance, action):
        verb = self.verbs[action]
        article = self._article(instance)
        texto_objeto = str(instance)
        vname = instance._meta.verbose_name.lower()

        segmentos = [
            {"texto": f"{verb} {article} {vname} "},
            {"texto": texto_objeto, "tipo": vname, "id": instance.pk},
        ]
        return f"{verb} {article} {vname} {texto_objeto}", segmentos

    def log(self, instance, action):
        descripcion, segmentos = self.get_log_description(instance, action)
        RegistroActividad.objects.create(
            usuario=self.request.user,
            accion=action,
            descripcion=descripcion,
            segmentos=segmentos,
            sucursal_id=self.request.branch_id,
        )

    def perform_create(self, serializer):
        instance = serializer.save()
        self.log(instance, 'create')

    def perform_update(self, serializer):
        instance = serializer.save()
        self.log(instance, 'update')

    def perform_destroy(self, instance):
        self.log(instance, 'delete')
        instance.delete()
