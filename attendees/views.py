import jdatetime

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from .models import DataUpload, Attendee
from .utils import load_attendees_from_upload, to_persian_digits


def upload_time_jalali(d):
    jd = jdatetime.datetime.fromgregorian(datetime=d)
    return to_persian_digits(jd.strftime("%Y/%m/%d  %H:%M"))


def login_view(request):
    # one login page for everyone (admin + normal users)
    if request.user.is_authenticated:
        return redirect("cards")

    error = ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("cards")
        error = "نام کاربری یا رمز عبور اشتباه است."

    return render(request, "login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


def staff_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_staff, login_url="login")(view_func)


@staff_required
def dashboard(request):
    msg = ""
    if request.method == "POST":
        excel = request.FILES.get("excel_file")
        zipf = request.FILES.get("photos_zip")

        if not excel or not zipf:
            msg = "هر دو فایل اکسل و زیپ عکس‌ها باید انتخاب شوند."
        else:
            DataUpload.objects.create(excel_file=excel, photos_zip=zipf)
            return redirect("cards")

    last = DataUpload.objects.first()
    last_jalali = upload_time_jalali(last.created_at) if last else None

    return render(request, "dashboard.html", {"last": last, "last_jalali": last_jalali, "msg": msg})


@login_required
def cards(request):
    upload_obj = DataUpload.objects.first()

    if not upload_obj:
        return render(request, "cards.html", {
            "attendees": [],
            "upload": None,
            "upload_time_jalali": None,
            "no_upload": True,
        })

    attendees = load_attendees_from_upload(upload_obj)
    return render(request, "cards.html", {
        "attendees": attendees,
        "upload": upload_obj,
        "upload_time_jalali": upload_time_jalali(upload_obj.created_at),
        "no_upload": False,
    })


@require_POST
@login_required
def set_selection(request):
    upload_obj = DataUpload.objects.first()
    if not upload_obj:
        return HttpResponseBadRequest("NO_UPLOAD")

    email = (request.POST.get("email") or "").strip().lower()
    selected_raw = (request.POST.get("selected") or "").strip().lower()

    if not email:
        return HttpResponseBadRequest("MISSING_EMAIL")

    # parse selected bool
    if selected_raw in ("1", "true", "yes", "on"):
        desired = True
    elif selected_raw in ("0", "false", "no", "off"):
        desired = False
    else:
        return HttpResponseBadRequest("BAD_SELECTED")

    if (not request.user.is_staff) and (desired is False):
        return HttpResponseForbidden("FORBIDDEN")

    attendee, _ = Attendee.objects.get_or_create(
        upload=upload_obj,
        email=email,
        defaults={"name": "", "tag": "PRODUCT", "selected": False},
    )

    # for normal users: only allow selecting, never unselecting
    if (not request.user.is_staff) and attendee.selected:
        return JsonResponse({"ok": True, "email": email, "selected": True})

    attendee.selected = desired
    attendee.save(update_fields=["selected", "updated_at"])

    return JsonResponse({"ok": True, "email": email, "selected": attendee.selected})
