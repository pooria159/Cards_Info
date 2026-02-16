import os
import re
import ast
import json
import zipfile
import datetime as dt

import pandas as pd
import jdatetime

from django.conf import settings

ALLOWED_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
EMAIL_SAFE_RE = re.compile(r"^[A-Za-z0-9@\.\+\-_]+$")

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
ZWNJ = "\u200c"  # نیم‌فاصله

def to_persian_digits(s: str) -> str:
    return str(s).translate(PERSIAN_DIGITS)

def to_jalali_str(d: dt.datetime) -> str:
    jd = jdatetime.datetime.fromgregorian(datetime=d)
    return to_persian_digits(jd.strftime("%Y/%m/%d  %H:%M"))

def normalize_value(v):
    if pd.isna(v):
        return ""
    if isinstance(v, (pd.Timestamp,)):
        g = v.to_pydatetime()
        if isinstance(g, dt.datetime):
            return to_jalali_str(g)
        return str(v)
    return v

def maybe_parse_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        return [p for p in parts if p]
    return [s]

def format_iran_mobile(v, pretty: bool = False) -> str:
    """
    Normalize Iranian mobile numbers to 09xxxxxxxxx (no spaces).
    Supports: +98, 0098, 98, 0, 9...
    """
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    digits = re.sub(r"\D+", "", s)

    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("98"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]

    if len(digits) == 10 and digits.startswith("9"):
        normalized = "0" + digits
        if not pretty:
            return normalized
        return f"{normalized[:4]} {normalized[4:7]} {normalized[7:]}"
    return ""

def safe_extract_zip(zip_path: str, dest_dir: str):
    """
    Secure extraction (prevents zip slip)
    """
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.infolist():
            if member.is_dir():
                continue
            member_name = member.filename.replace("\\", "/")
            if member_name.startswith("/") or member_name.startswith("../") or "/../" in member_name:
                continue

            target_path = os.path.abspath(os.path.join(dest_dir, member_name))
            dest_abs = os.path.abspath(dest_dir)
            if not target_path.startswith(dest_abs + os.sep) and target_path != dest_abs:
                continue

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with z.open(member, "r") as src, open(target_path, "wb") as out:
                out.write(src.read())
                
                
def build_photo_index(extract_root: str):
    """
    returns: dict[email_lower] -> relative_path (inside extract_root)

    Supports:
      - old format: photos/<email>/<img>
      - new format: final_photo/<email>/submission_.../<...>/<img>
      - any nested structure as long as a path segment contains an email.
    """
    candidates = {}

    def is_email_segment(seg: str) -> bool:
        seg = (seg or "").strip()
        if not seg:
            return False
        if not EMAIL_SAFE_RE.match(seg):
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9\.\+\-_]+@[A-Za-z0-9\.\-_]+\.[A-Za-z]{2,}", seg))

    for root, _, files in os.walk(extract_root):
        for fn in files:
            low = fn.lower()
            if not low.endswith(ALLOWED_IMAGE_EXTS):
                continue

            full_path = os.path.join(root, fn)
            rel_path = os.path.relpath(full_path, extract_root).replace("\\", "/")
            parts = [p for p in rel_path.split("/") if p]

            email = None

            for p in parts:
                if "@" in p and is_email_segment(p.lower()):
                    email = p.lower()
                    break

            if not email:
                m = re.search(r"[A-Za-z0-9\.\+\-_]+@[A-Za-z0-9\.\-_]+\.[A-Za-z]{2,}", rel_path)
                if m:
                    em = m.group(0).lower()
                    if is_email_segment(em):
                        email = em

            if not email:
                continue

            size = 0
            try:
                size = os.path.getsize(full_path)
            except Exception:
                pass

            depth = rel_path.count("/")

            candidates.setdefault(email, []).append((depth, -size, rel_path))

    index = {}
    for email, items in candidates.items():
        items.sort()
        index[email] = items[0][2]
    return index


def normalize_interest_term(s: str) -> str:
    """
    Keep/restore Persian ZWNJ and fix common words like fintech.
    """
    s = str(s).strip()
    s = s.replace("\\u200c", ZWNJ)  # if literal in excel
    s = re.sub(r"\s+", " ", s).strip()

    # fintech => فین‌تک
    s = re.sub(r"^فین\s*تک$", f"فین{ZWNJ}تک", s)
    return s

def normalize_tag(raw_tag: str) -> str:
    """
    Normalize Tag column to AI / SOFTWARE / PRODUCT
    """
    t = (raw_tag or "").strip()
    if not t:
        return "PRODUCT"
    t_up = t.upper()

    # common variants
    if t_up in ["AI", "A.I", "A I"]:
        return "AI"
    if t_up in ["SOFTWARE", "SW"]:
        return "SOFTWARE"
    if t_up in ["PRODUCT", "PROD"]:
        return "PRODUCT"

    # fallback: if something else provided, keep uppercase
    return t_up

def load_attendees_from_upload(upload_obj):
    """
    Reads the Excel + photos zip, builds the list of attendee dicts for the UI,
    AND synchronizes a DB snapshot (Attendee model) so that `selected` persists
    across reloads and is editable in Django admin.

    Only rows with Status == 1 are shown.
    """
    import os
    import json
    import pandas as pd
    from django.utils import timezone
    from django.conf import settings
    from .models import Attendee

    excel_path = upload_obj.excel_file.path
    zip_path = upload_obj.photos_zip.path

    extract_dir = os.path.join(settings.MEDIA_ROOT, "extracted", f"upload_{upload_obj.id}")

    if not os.path.isdir(extract_dir) or not any(os.scandir(extract_dir)):
        safe_extract_zip(zip_path, extract_dir)

    photo_index = build_photo_index(extract_dir)

    df = pd.read_excel(excel_path).fillna("")
    cols = list(df.columns)

    interests_key = None
    for c in cols:
        if "NovaTech" in str(c) or "علاقه" in str(c):
            interests_key = str(c)
            break

    EMAIL_COLUMN = "User Email"
    NAME_COLUMN = "نام و نام‌خانوادگی"

    summary_keys = [
        "📍 شهر محل سکونت",
        "شماره همراه",
        "آخرین مقطع و رشته تحصیلی شما چیست؟",
        "در حال حاضر در چه موقعیت شغلی فعالیت می‌کنید؟",
    ]

    def status_is_present(val) -> bool:
        s = str(val).strip().lower()
        if s in ("1", "1.0", "true", "yes", "y", "present", "ok"):
            return True
        try:
            return float(s) == 1.0
        except Exception:
            return False

    existing = {a.email.lower(): a for a in Attendee.objects.filter(upload=upload_obj)}
    to_create = []
    to_update = []
    now = timezone.now()

    attendees = []
    for _, row in df.iterrows():
        item = {str(c): normalize_value(row[c]) for c in cols}

        status_val = item.get("Status", "")
        if not status_is_present(status_val):
            continue

        if "شماره همراه" in item:
            fm = format_iran_mobile(item["شماره همراه"], pretty=False)
            if fm:
                item["شماره همراه"] = fm

        email_raw = str(item.get(EMAIL_COLUMN, "")).strip()
        email = email_raw.lower()
        name = str(item.get(NAME_COLUMN, "")).strip() or str(item.get("User Name", "")).strip()

        tag = normalize_tag(str(item.get("Tag", "")).strip())
        item["Tag"] = tag

        interests = maybe_parse_list(item.get(interests_key, "")) if interests_key else []
        if interests_key:
            interests = [normalize_interest_term(x) for x in (interests or [])]
            interests = [x for x in interests if x]
            item[interests_key] = ", ".join(interests)

        photo_rel = photo_index.get(email)
        photo_url = (settings.MEDIA_URL + "extracted/" + f"upload_{upload_obj.id}/" + photo_rel) if photo_rel else ""

        summary = []
        for k in summary_keys:
            val = str(item.get(k, "")).strip()
            if val:
                summary.append((k, val))

        search_blob = " ".join([
            str(name or ""),
            str(email_raw or ""),
            str(item.get("📍 شهر محل سکونت", "")).strip(),
            str(item.get("آخرین مقطع و رشته تحصیلی شما چیست؟", "")).strip(),
            str(item.get("در حال حاضر در چه موقعیت شغلی فعالیت می‌کنید؟", "")).strip(),
            str(item.get("شماره همراه", "")).strip(),
            tag,
            " ".join(interests or []),
        ]).lower()

        raw_json = json.dumps(item, ensure_ascii=False)

        selected = False
        if email:
            obj = existing.get(email)
            if obj is None:
                to_create.append(Attendee(upload=upload_obj, email=email, name=name or "", tag=tag or "PRODUCT"))
            else:
                selected = bool(obj.selected)
                changed = False
                if (obj.name or "") != (name or ""):
                    obj.name = name or ""
                    changed = True
                if (obj.tag or "") != (tag or "PRODUCT"):
                    obj.tag = tag or "PRODUCT"
                    changed = True
                if changed:
                    obj.updated_at = now
                    to_update.append(obj)

        attendees.append({
            "name": name or "(بدون نام)",
            "email": email_raw,
            "photo_url": photo_url,
            "interests": interests,
            "summary": summary,
            "raw_json": raw_json,
            "search_blob": search_blob,
            "tag": tag,
            "selected": selected,
        })

    if to_create:
        Attendee.objects.bulk_create(to_create, ignore_conflicts=True)
    if to_update:
        Attendee.objects.bulk_update(to_update, ["name", "tag", "updated_at"])

    attendees.sort(key=lambda x: x["name"])
    return attendees

