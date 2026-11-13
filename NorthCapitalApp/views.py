from functools import wraps
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from collections import Counter
from datetime import datetime, time, timedelta
from urllib.parse import urlencode
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import (Avg, Count, DateTimeField, Exists, ExpressionWrapper, F, FloatField,
                              Max, Min, OuterRef, Q, Sum)
from django.utils import timezone

from .models import Empresa, PrecioDiario, Sesion


def home(request):
    return render(request, 'index.html')


@never_cache
# 1.0
# def login_view(request, perfil='usuario'):
#     """perfil='usuario' -> /login/ ; perfil='administrador' -> /login/administrador/"""
#     if request.user.is_authenticated:
#         return redirect('panel_admin' if request.user.is_staff else 'dashboard')
#     error = ''
#     if request.method == 'POST':
#         user = authenticate(request,
#                             username=request.POST.get('username', ''),
#                             password=request.POST.get('password', ''))

#         # El perfil elegido debe coincidir con el tipo de cuenta (is_staff).
#         if user is not None and user.is_staff == (perfil == 'administrador'):
#             login(request, user)
#             return redirect('panel_admin' if user.is_staff else 'dashboard')
#         error = 'No se pudo iniciar sesión. Revisa tus credenciales y el perfil seleccionado.'
#     return render(request, 'login.html', {'perfil': perfil, 'error': error})


#2.0
def login_view(request):
    if request.user.is_authenticated:
        return redirect('panel_admin' if request.user.is_staff else 'dashboard')
    error = ''
    if request.method == 'POST':
        user = authenticate(request,
                            username=request.POST.get('username', ''),
                            password=request.POST.get('password', ''))
        if user is not None:
            login(request, user)
            return redirect('panel_admin' if user.is_staff else 'dashboard')
        error = 'Usuario o contraseña incorrectos.'
    return render(request, 'login.html', {'error': error})



@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


# @never_cache
def registro(request):
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        user.password = form.cleaned_data['password1']
        user.is_staff = False
        user.is_superuser = False
        user.save()
        login(request, user)
        return redirect('dashboard')
    return render(request, 'registro.html', {'form': form})



def staff_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden('Tu perfil no tiene acceso a este panel.')
        return view(request, *args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Centro de control: datos reales para la cuadrícula de calidad y el embudo
# ---------------------------------------------------------------------------
def _num(n):
    """1520 -> '1.520'"""
    return f'{n:,}'.replace(',', '.')


def _pct(x):
    """98.55 -> '98,6%'"""
    return f'{x:.1f}'.replace('.', ',') + '%'


def _pct_exacto(parte, todo):
    """Porcentaje con 1 decimal que nunca muestra 100% ni 0% si no lo son de verdad.

    450.841 de 450.869 es 99,994%: redondeado a 1 decimal daría '100,0%', engañoso
    porque faltan 28 registros. Aquí se muestra '99,9%'.
    """
    if not todo:
        return '0%'
    if parte == todo:
        return '100%'
    if parte == 0:
        return '0%'
    p = parte / todo * 100
    redondeado = round(p, 1)
    if redondeado >= 100:
        return '99,9%'
    if redondeado <= 0:
        return '<0,1%'
    return _pct(redondeado)


def _calidad_empresas():
    """Una celda por empresa: completa, o con al menos un registro incompleto."""
    con_faltantes = PrecioDiario.objects.filter(empresa=OuterRef('pk'), registro_completo=False)
    empresas = list(
        Empresa.objects.select_related('sector')
        .annotate(incompleta=Exists(con_faltantes))
        .order_by('incompleta', 'sector__nombre', 'ticker')   # las incompletas quedan al final
    )
    total = len(empresas)
    faltantes = [e.ticker for e in empresas if e.incompleta]
    completas = total - len(faltantes)
    return {
        'empresas': empresas,
        'total': _num(total),
        'hay_datos': total > 0,
        'completas': _num(completas),
        'completas_pct': _pct_exacto(completas, total),
        'incompletas': _num(len(faltantes)),
        'incompletas_pct': _pct_exacto(len(faltantes), total),
        'revisar': faltantes[:12],
        'revisar_mas': max(len(faltantes) - 12, 0),
    }


def _embudo_usuarios():
    """Registrados -> volvieron a iniciar sesión -> activos en los últimos 30 días.

    Se excluye al personal (is_staff). 'Volvieron' = su último inicio de sesión fue
    al menos 1 día después de crear la cuenta (el registro ya inicia sesión solo,
    por eso last_login no vacío no sirve para medir esto).
    """
    usuarios = get_user_model().objects.filter(is_staff=False)
    un_dia_despues = ExpressionWrapper(F('date_joined') + timedelta(days=1),
                                       output_field=DateTimeField())
    volvieron = usuarios.filter(last_login__gte=un_dia_despues)
    hace_30 = timezone.now() - timedelta(days=30)
    cifras = [
        ('Registrados', usuarios.count()),
        ('Volvieron a iniciar sesión', volvieron.count()),
        ('Activos este mes', volvieron.filter(last_login__gte=hace_30).count()),
    ]
    base = cifras[0][1]
    ancho = [400 * valor / base if base else 0 for _, valor in cifras]
    colores = ['#1D4ED8', '#2563EB', '#3B82F6']
    etapas = []
    for i, (nombre, valor) in enumerate(cifras):
        arriba = ancho[i]
        abajo = ancho[i + 1] if i < 2 else arriba * 0.94
        puntos = (f'{200 - arriba / 2:.1f},0 {200 + arriba / 2:.1f},0 '
                  f'{200 + abajo / 2:.1f},36 {200 - abajo / 2:.1f},36')
        perdidos = valor - cifras[i + 1][1] if i < 2 else 0
        etapas.append({
            'nombre': nombre,
            'valor': _num(valor),
            'pct': '100%' if i == 0 else _pct_exacto(valor, base),
            'puntos': puntos,
            'color': colores[i],
            'perdidos': _num(perdidos) if perdidos > 0 else '',
        })
    return {'hay_datos': base > 0, 'etapas': etapas}


# ---------------------------------------------------------------------------
# Centro de control: "Uso semanal" y "Estado de los datos"
# ---------------------------------------------------------------------------
_DIAS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
_MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def _fecha(d):
    """date(2025, 12, 31) -> '31 dic 2025'"""
    return f'{d.day} {_MESES[d.month - 1]} {d.year}'


def _actividad_semanal():
    """Sesiones (inicios de sesión) de los últimos 7 días, con la semana anterior como referencia."""
    hoy = timezone.localdate()
    desde = datetime.combine(hoy - timedelta(days=13), time.min)
    if settings.USE_TZ:
        desde = timezone.make_aware(desde)

    # Se agrupa en Python (solo 14 días de datos): no depende de las tablas de zona horaria de MySQL.
    por_dia = Counter()
    for f in Sesion.objects.filter(fecha__gte=desde).values_list('fecha', flat=True):
        por_dia[(timezone.localtime(f) if timezone.is_aware(f) else f).date()] += 1

    dias = [hoy - timedelta(days=i) for i in range(6, -1, -1)]
    valores = [por_dia[d] for d in dias]
    total = sum(valores)
    anterior = sum(por_dia[hoy - timedelta(days=i)] for i in range(7, 14))
    maximo = max(valores)

    columnas = []
    for d, n in zip(dias, valores):
        columnas.append({
            'etiqueta': 'Hoy' if d == hoy else _DIAS[d.weekday()],
            'detalle': f'{_fecha(d)}: {_num(n)} sesiones',
            'valor': _num(n),
            'alto': f'height:{n / maximo * 100:.1f}%' if n else 'height:2px',
            'vacio': n == 0,
            'hoy': d == hoy,
        })

    if anterior:
        cambio = (total - anterior) / anterior * 100
        variacion = f"{'↑' if cambio >= 0 else '↓'} {_pct(abs(cambio))} vs. los 7 días anteriores"
        variacion_clase = 'text-green-600' if cambio >= 0 else 'text-red-500'
    else:
        variacion, variacion_clase = 'Sin datos de los 7 días anteriores', 'text-slate-400'

    return {
        'hay_datos': (total + anterior) > 0,
        'columnas': columnas,
        'total': _num(total),
        'variacion': variacion,
        'variacion_clase': variacion_clase,
    }


def _calidad_datos():
    """Resumen de calidad de la tabla de precios diarios."""
    r = PrecioDiario.objects.aggregate(
        total=Count('id'),
        completos=Count('id', filter=Q(registro_completo=True)),
        con_precio=Count('id', filter=Q(close__isnull=False, volumen__isnull=False)),
        primera=Min('fecha'),
        ultima=Max('fecha'),
    )
    total = r['total']
    if not total:
        return {'hay_datos': False}
    empresas = Empresa.objects.count()
    empresas_con_precios = Empresa.objects.filter(
        Exists(PrecioDiario.objects.filter(empresa=OuterRef('pk')))).count()

    def barra(nombre, parte, todo, unidad):
        pct = parte / todo * 100 if todo else 0
        ok = pct >= 98
        return {
            'nombre': nombre, 'pct': _pct_exacto(parte, todo), 'ancho': f'{pct:.2f}', 'pct_num': pct,
            'detalle': f'{_num(parte)} de {_num(todo)} {unidad}',
            'color': 'bg-green-500' if ok else 'bg-amber-400',
            'texto': 'text-green-600' if ok else 'text-amber-600',
        }

    barras = [
        barra('Registros completos', r['completos'], total, 'registros'),
        barra('Con precio de cierre y volumen', r['con_precio'], total, 'registros'),
        barra('Empresas con precios', empresas_con_precios, empresas, 'empresas'),
    ]
    estable = all(b['pct_num'] >= 98 for b in barras)
    return {
        'hay_datos': True,
        'barras': barras,
        'estado': 'Estable' if estable else 'Revisar',
        'estado_clase': 'bg-green-50 text-green-700' if estable else 'bg-amber-50 text-amber-700',
        'rango': f"{_fecha(r['primera'])} – {_fecha(r['ultima'])}",
    }


# ---------------------------------------------------------------------------
# Centro de control: "Usuarios recientes"
# ---------------------------------------------------------------------------
_COLORES_AVATAR = ['bg-lime-100', 'bg-sky-100', 'bg-violet-100', 'bg-amber-100', 'bg-rose-100']


def _hace(momento):
    """Tiempo transcurrido en español: 'Hace 12 min', 'Ayer', 'Hace 3 días', 'Nunca'."""
    if momento is None:
        return 'Nunca'
    delta = timezone.now() - momento
    seg = max(int(delta.total_seconds()), 0)
    if seg < 60:
        return 'Ahora mismo'
    if seg < 3600:
        return f'Hace {seg // 60} min'
    if seg < 86400:
        return f'Hace {seg // 3600} h'
    if delta.days == 1:
        return 'Ayer'
    if delta.days < 30:
        return f'Hace {delta.days} días'
    return _fecha(timezone.localtime(momento).date() if timezone.is_aware(momento) else momento.date())


def _fila_usuario(u):
    """Datos de un usuario listos para mostrar en una fila de tabla."""
    nombre = u.get_full_name().strip() or u.get_username()
    partes = nombre.split()
    iniciales = (partes[0][0] + partes[1][0]) if len(partes) > 1 else nombre[:2]
    return {
        'nombre': nombre,
        'email': u.email,
        'iniciales': iniciales.upper(),
        'color': _COLORES_AVATAR[u.pk % len(_COLORES_AVATAR)],
        'rol': 'Administrador' if u.is_staff else 'Usuario',
        'ultima_sesion': _hace(u.last_login),
        'activo': u.is_active,
    }


def _usuarios_recientes(limite=5):
    """Los usuarios con la sesión más reciente (los que nunca entraron, al final)."""
    usuarios = get_user_model().objects.order_by(F('last_login').desc(nulls_last=True), '-date_joined')[:limite]
    return [_fila_usuario(u) for u in usuarios]


# ---------------------------------------------------------------------------
# Centro de control: las cuatro tarjetas de indicadores
# ---------------------------------------------------------------------------
def _decimal(x):
    """3.8 -> '3,8'"""
    return f'{x:.1f}'.replace('.', ',')


def _kpis(calidad_datos):
    """Cuatro indicadores. Sin administradores (is_staff) en los datos de usuarios."""
    hace_30 = timezone.now() - timedelta(days=30)
    usuarios = get_user_model().objects.filter(is_staff=False)

    # 1) Usuarios registrados, y cuántos son nuevos en los últimos 30 días
    total = usuarios.count()
    nuevos = usuarios.filter(date_joined__gte=hace_30).count()
    antes = total - nuevos
    if nuevos and antes:
        detalle1 = f'↑ {_pct(nuevos / antes * 100)} este mes · +{_num(nuevos)} nuevos'
        clase1 = 'text-green-600'
    elif nuevos:
        detalle1, clase1 = f'+{_num(nuevos)} nuevos en 30 días', 'text-green-600'
    else:
        detalle1, clase1 = 'Sin registros nuevos en 30 días', 'text-slate-400'

    # 2) Usuarios activos: con inicio de sesión en los últimos 30 días
    activos = usuarios.filter(last_login__gte=hace_30).count()
    if total:
        detalle2, clase2 = f'{_pct_exacto(activos, total)} de los registrados', 'text-slate-500'
    else:
        detalle2, clase2 = 'Sin usuarios registrados', 'text-slate-400'

    # 3) Sesiones (inicios de sesión) de los últimos 30 días, de la tabla Sesion
    s = Sesion.objects.filter(fecha__gte=hace_30, usuario__is_staff=False).aggregate(
        n=Count('id'), u=Count('usuario', distinct=True))
    if s['n']:
        detalle3, clase3 = f"{_decimal(s['n'] / s['u'])} por usuario", 'text-slate-500'
    else:
        detalle3, clase3 = 'Sin sesiones registradas', 'text-slate-400'

    # 4) Disponibilidad de datos = registros de precios completos
    if calidad_datos.get('hay_datos'):
        b = calidad_datos['barras'][0]
        valor4, detalle4, clase4, vacio4 = b['pct'], b['detalle'] + ' completos', b['texto'], False
    else:
        valor4, detalle4, clase4, vacio4 = '—', 'Sin precios cargados', 'text-slate-400', True

    return [
        {'etiqueta': 'Usuarios registrados', 'valor': _num(total), 'detalle': detalle1, 'clase': clase1, 'vacio': False},
        {'etiqueta': 'Usuarios activos', 'valor': _num(activos), 'detalle': detalle2, 'clase': clase2, 'vacio': False},
        {'etiqueta': 'Sesiones (30 días)', 'valor': _num(s['n']), 'detalle': detalle3, 'clase': clase3, 'vacio': False},
        {'etiqueta': 'Disponibilidad de datos', 'valor': valor4, 'detalle': detalle4, 'clase': clase4, 'vacio': vacio4},
    ]


# ---------------------------------------------------------------------------
# Dashboard: velas del índice S&P 500
# ---------------------------------------------------------------------------
_CLAVE_INDICE = 'indice_sp500_velas_v1'


def _filas_indice(filtrar_saltos=True):
    """Filas de PrecioDiario utilizables para construir el índice."""
    filas = PrecioDiario.objects.filter(
        cierre_anterior__gt=0, open__isnull=False, high__isnull=False,
        low__isnull=False, close__isnull=False)
    if filtrar_saltos:
        for campo in ('open', 'high', 'low', 'close'):
            filas = filas.filter(**{campo + '__gt': F('cierre_anterior') * 0.5,
                                    campo + '__lt': F('cierre_anterior') * 2})
    return filas


def _calcular_indice_sp500(filtrar_saltos=True, solo_completos=False):

    def razon(campo):
        return ExpressionWrapper(F(campo) / F('cierre_anterior'), output_field=FloatField())

    filas = _filas_indice(filtrar_saltos)
    if solo_completos:
        filas = filas.filter(registro_completo=True)
    miembros = filas.filter(miembro_sp500=True)
    if miembros.exists():
        filas = miembros

    diario = (filas.values('fecha')
              .annotate(o=Avg(razon('open')), h=Avg(razon('high')), l=Avg(razon('low')),
                        c=Avg(razon('close')), v=Sum('volumen'), n=Count('id'))
              .order_by('fecha'))

    salida = {k: [] for k in ('fecha', 'open', 'high', 'low', 'close', 'volumen', 'empresas')}
    nivel = 100.0
    for f in diario:
        previo = nivel
        nivel = previo * f['c']
        salida['fecha'].append(f['fecha'].isoformat())
        salida['open'].append(round(previo * f['o'], 4))
        salida['high'].append(round(previo * f['h'], 4))
        salida['low'].append(round(previo * f['l'], 4))
        salida['close'].append(round(nivel, 4))
        salida['volumen'].append(int(f['v'] or 0))
        salida['empresas'].append(f['n'])
    return salida if salida['fecha'] else {}


# def _indice_sp500():
#     """Con caché de 1 hora: recorre ~450 mil filas, no conviene repetirlo en cada visita."""
#     datos = cache.get(_CLAVE_INDICE)
#     if datos is None:
#         datos = _calcular_indice_sp500()
#         if datos:
#             cache.set(_CLAVE_INDICE, datos, 3600)
#     return datos

def _indice_sp500():
    return _calcular_indice_sp500()


# Páginas del prototipo original (sin cambios de contenido), ahora protegidas.
# @never_cache
@login_required
def dashboard(request):
    # El administrador también puede ver el panel de usuario ("Vista usuario").
    return render(request, 'dashboard.html', {'indice': _indice_sp500()})


# @never_cache
@staff_required
def panel_admin(request):
    calidad_datos = _calidad_datos()
    return render(request, 'admin.html', {
        'calidad': _calidad_empresas(),
        'embudo': _embudo_usuarios(),
        'actividad': _actividad_semanal(),
        'calidad_datos': calidad_datos,
        'kpis': _kpis(calidad_datos),
        'usuarios_recientes': _usuarios_recientes(),
    })


# @never_cache
@staff_required
def usuarios(request):
    q = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', '')
    lista = get_user_model().objects.all()
    for palabra in q.split():   # cada palabra debe aparecer en el usuario, nombre, apellido o correo
        lista = lista.filter(Q(username__icontains=palabra) | Q(first_name__icontains=palabra) |
                             Q(last_name__icontains=palabra) | Q(email__icontains=palabra))
    if estado == 'activo':
        lista = lista.filter(is_active=True)
    elif estado == 'inactivo':
        lista = lista.filter(is_active=False)
    else:
        estado = ''
    lista = lista.order_by(F('last_login').desc(nulls_last=True), '-date_joined')
    pagina = Paginator(lista, 15).get_page(request.GET.get('page'))
    return render(request, 'admin-usuarios.html', {
        'filas': [_fila_usuario(u) for u in pagina],
        'pagina': pagina,
        'q': q,
        'estado': estado,
        'hay_filtros': bool(q or estado),
        'filtros': urlencode({k: val for k, val in (('q', q), ('estado', estado)) if val}),
        'total': _num(pagina.paginator.count),
        'desde': _num(pagina.start_index()),
        'hasta': _num(pagina.end_index()),
    })


# @login_required
def pagina(request, template):
    return render(request, template)
