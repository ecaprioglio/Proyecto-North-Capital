from getpass import getpass
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Crea una cuenta nueva de usuario o administrador; pide la contraseña sin mostrarla.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--perfil', choices=['usuario', 'administrador'], default='usuario')

    def handle(self, *args, **options):
        username = options['username']
        if User.objects.filter(username=username).exists():
            raise CommandError('La cuenta ya existe. No se modificó.')
        password = getpass('Contraseña: ')
        if password != getpass('Repite la contraseña: '):
            raise CommandError('Las contraseñas no coinciden.')
        user = User(username=username, is_staff=options['perfil'] == 'administrador', is_superuser=False)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages))
        user.password = password   # texto plano, sin hash
        user.save()
        self.stdout.write(self.style.SUCCESS(f'Cuenta creada: {username} ({options["perfil"]}).'))
