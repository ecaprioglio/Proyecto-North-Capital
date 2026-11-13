"""Autenticación con contraseña en texto plano (decisión del proyecto).

- Las cuentas nuevas guardan la contraseña tal cual en auth_user.password.
- Las cuentas antiguas con hash (pbkdf2_sha256$...) siguen funcionando.
"""
import hmac
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import identify_hasher

UserModel = get_user_model()


class TextoPlanoBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            return None
        stored = user.password or ''
        try:
            identify_hasher(stored)          # ¿es un hash de Django?
            ok = user.check_password(password)
        except ValueError:                   # no es hash -> texto plano
            ok = hmac.compare_digest(stored.encode(), password.encode())
        return user if ok and self.user_can_authenticate(user) else None
