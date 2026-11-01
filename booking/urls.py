from django.urls import path
from . import views

app_name = "booking"
urlpatterns = [
    path("book/", views.book, name="book"),
    path("book/<uuid:reference>/", views.confirmation, name="confirmation"),
    path("book/<uuid:reference>/cancel/", views.customer_cancel, name="customer_cancel"),
    path("staff/login/", views.staff_login, name="login"),
    path("staff/logout/", views.staff_logout, name="logout"),
    path("staff/", views.dashboard, name="dashboard"),
    path("staff/schedule/", views.schedule, name="schedule"),
    path("staff/barbers/new/", views.barber_edit, name="barber_create"),
    path("staff/barbers/<int:pk>/", views.barber_edit, name="barber_edit"),
    path("staff/barbers/<int:pk>/hours/", views.hours_edit, name="hours"),
    path("staff/appointments/<int:pk>/cancel/", views.staff_cancel, name="staff_cancel"),
    path("staff/services/", views.services, name="services"),
    path("staff/services/new/", views.service_edit, name="service_create"),
    path("staff/services/<int:pk>/", views.service_edit, name="service_edit"),
]
