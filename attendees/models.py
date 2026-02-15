from django.db import models


class DataUpload(models.Model):
    excel_file = models.FileField(upload_to="uploads/excel/")
    photos_zip = models.FileField(upload_to="uploads/photos_zip/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Upload #{self.id} - {self.created_at:%Y-%m-%d %H:%M}"


class Attendee(models.Model):
    """
    Snapshot of attendees for a specific upload (derived from the Excel file),
    plus the admin-controlled `selected` state.
    """

    upload = models.ForeignKey(DataUpload, on_delete=models.CASCADE, related_name="attendees")

    # normalized to lowercase
    email = models.EmailField()
    name = models.CharField(max_length=255, blank=True)
    tag = models.CharField(max_length=32, default="PRODUCT", blank=True)

    # This is the state that must persist + be editable in Django admin
    selected = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "email"]
        constraints = [
            models.UniqueConstraint(fields=["upload", "email"], name="uniq_attendee_per_upload"),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}> (upload {self.upload_id})"
