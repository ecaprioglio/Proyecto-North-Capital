import logging

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.db import DatabaseError, models
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


class Sector(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre


class Empresa(models.Model):
    ticker = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=150)
    sector = models.ForeignKey(Sector, on_delete=models.PROTECT, related_name='empresas')
    subindustria = models.CharField(max_length=150, blank=True)
    fecha_ingreso_sp500 = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.ticker} - {self.nombre}"


class PrecioDiario(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='precios')
    fecha = models.DateField(db_index=True)
    miembro_sp500 = models.BooleanField(default=True)  # miembro_sp500_en_fecha (SI/NO)
    open = models.FloatField(null=True, blank=True)
    high = models.FloatField(null=True, blank=True)
    low = models.FloatField(null=True, blank=True)
    close = models.FloatField(null=True, blank=True)
    volumen = models.BigIntegerField(null=True, blank=True)
    cierre_anterior = models.FloatField(null=True, blank=True)
    variacion_intradia = models.FloatField(null=True, blank=True)
    variacion_intradia_pct = models.FloatField(null=True, blank=True)
    rango_diario = models.FloatField(null=True, blank=True)
    rango_diario_pct = models.FloatField(null=True, blank=True)
    retorno_vs_cierre_anterior_pct = models.FloatField(null=True, blank=True)
    registro_completo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'fecha'], name='unico_empresa_fecha')
        ]

    def __str__(self):
        return f"{self.empresa.ticker} {self.fecha}"


class Sesion(models.Model):
    """Un inicio de sesión. Alimenta el gráfico "Uso semanal" del Centro de control."""
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sesiones')
    fecha = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return f"{self.usuario} {self.fecha:%Y-%m-%d %H:%M}"


@receiver(user_logged_in)
def registrar_sesion(sender, user, **kwargs):
    """Guarda una fila por cada login. Si falta migrar, no bloquea el inicio de sesión."""
    try:
        Sesion.objects.create(usuario=user)
    except DatabaseError:
        logger.exception('No se pudo registrar la sesión (¿falta ejecutar migrate?)')
