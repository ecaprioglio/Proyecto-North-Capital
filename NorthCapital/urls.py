from django.contrib import admin
from django.urls import path
from NorthCapitalApp import views

urlpatterns = [
    path('admin/', admin.site.urls),

    path('', views.home, name='index'),
    path('login/', views.login_view, name='login'),
    path('login/administrador/', views.login_view, {'perfil': 'administrador'}, name='login_admin'),
    path('salir/', views.logout_view, name='logout'),
    path('registro/', views.registro, name='registro'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('panel-admin/', views.panel_admin, name='panel_admin'),
    path('panel-admin/usuarios/', views.usuarios, name='admin_usuarios'),
]

paginas = ['empresas', 'empresa', 'comparar', 'favoritos', 'sectores']
urlpatterns += [
    path(f'{n}/', views.pagina, {'template': f'{n}.html'}, name=n) for n in paginas
]

# # Los enlaces antiguos .html también pasan por las mismas comprobaciones.
# urlpatterns += [
#     path('index.html', views.home),
#     path('login.html', views.login_view),
#     path('registro.html', views.registro),
#     path('dashboard.html', views.dashboard),
#     path('admin.html', views.panel_admin),
#     path('admin-usuarios.html', views.usuarios),
# ]
# urlpatterns += [
#     path(f'{n}.html', views.pagina, {'template': f'{n}.html'}) for n in paginas
# ]
