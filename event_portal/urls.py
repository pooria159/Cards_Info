from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from attendees import views

urlpatterns = [
    path("admin/", admin.site.urls),

    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # staff-only
    path("dashboard/", views.dashboard, name="dashboard"),

    # UI (admin + normal users)
    path("", views.cards, name="cards"),

    # API
    path("api/selection/", views.set_selection, name="set_selection"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
