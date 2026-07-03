from django.urls import path
from . import views


urlpatterns = [
    path('', views.index, name='index'),
    path('ialogin/', views.ialoing, name='ialogin'),
    path('home/', views.home, name='home'),
    path('logout/', views.logout_view, name='logout'),
    path('home/reports/', views.iareport, name='iareport'),
    path('home/console/', views.console, name='console'),
    path('home/points/', views.statistics, name='statistics'),
    path('home/users/', views.user_privileges_list, name='users_list'),
    path('home/users/<int:user_id>/privileges/', views.manage_privileges, name='manage_privileges'),
    path('user-privileges/', views.user_privileges_list, name='user_privileges_list'),
    path('update-privilege/', views.update_privilege, name='update_privilege'),
    path('check-permission/', views.check_user_permission, name='check_user_permission'),
    path('delete-report/<int:report_id>/', views.delete_report, name='delete_report'),
    path('soft-delete-report/<int:report_id>/', views.soft_delete_report, name='soft_delete_report'),
    path('restore-report/<int:report_id>/', views.restore_report, name='restore_report'),
    path('permanent-delete-report/<int:report_id>/', views.permanent_delete_report, name='permanent_delete_report'),
]