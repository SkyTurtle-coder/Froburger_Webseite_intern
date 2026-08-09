from django import forms

from .models import Document, DocumentFolder, FolderScope

# SEC-004/SEC-009: allowlist of document types this library is actually used
# for (matches Document.file_icon's supported types, minus SVG/HTML - those
# stay downloadable if they already exist from before this fix, but are no
# longer accepted from new uploads, since an inline-rendered SVG can carry a
# script and there's no product requirement for uploading new ones). Content
# type and magic bytes are checked in addition to the extension so a renamed
# executable can't slip through - see clean_file() below, modeled on the
# existing obituary-PDF upload validation in accounts/forms.py.
MAX_DOCUMENT_FILE_SIZE = 20 * 1024 * 1024  # keep below nginx's client_max_body_size (25 MB) so Django's friendlier error fires first

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy binary Office (.doc/.xls/.ppt)
_ZIP_MAGIC = b"PK\x03\x04"  # OOXML (.docx/.xlsx/.pptx) - checked as a plain ZIP signature only, never unpacked

ALLOWED_DOCUMENT_EXTENSIONS = {
    "pdf": {"application/pdf"},
    "doc": {"application/msword"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xls": {"application/vnd.ms-excel"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "ppt": {"application/vnd.ms-powerpoint"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "txt": {"text/plain"},
}

# Several browsers/OSes send a generic (or no) content type for less common
# extensions - accepted for any allowed extension rather than treated as a
# mismatch, since the magic-byte check is the actual security gate here.
_GENERIC_CONTENT_TYPES = {"application/octet-stream", ""}

DOCUMENT_MAGIC_BYTES = {
    "pdf": (b"%PDF-",),
    "doc": (_OLE2_MAGIC,),
    "xls": (_OLE2_MAGIC,),
    "ppt": (_OLE2_MAGIC,),
    "docx": (_ZIP_MAGIC,),
    "xlsx": (_ZIP_MAGIC,),
    "pptx": (_ZIP_MAGIC,),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    # .txt has no reliable magic number - extension + content-type are the gate.
}


class DocumentFolderForm(forms.ModelForm):
    class Meta:
        model = DocumentFolder
        fields = ("name", "parent")
        labels = {
            "name": "Ordnername",
            "parent": "Übergeordneter Ordner",
        }

    def __init__(self, *args, scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope = scope
        self.fields["parent"].required = False
        self.fields["parent"].queryset = DocumentFolder.objects.filter(scope=scope).order_by("name")
        self.fields["parent"].label_from_instance = lambda folder: folder.path_label

    def save(self, commit=True):
        folder = super().save(commit=False)
        folder.scope = self.scope
        if commit:
            folder.save()
        return folder


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ("title", "description", "folder", "file")
        labels = {
            "title": "Titel",
            "description": "Beschreibung",
            "folder": "Ordner",
            "file": "Datei",
        }

    def __init__(self, *args, scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope = scope
        self.fields["folder"].required = False
        self.fields["folder"].queryset = DocumentFolder.objects.filter(scope=scope).order_by("name")
        self.fields["folder"].empty_label = "Ohne Ordner"
        self.fields["folder"].label_from_instance = lambda folder: folder.path_label

    def clean_folder(self):
        folder = self.cleaned_data["folder"]
        if folder is None:
            return folder
        if folder.scope != self.scope:
            raise forms.ValidationError("Ordner und Dokumenttyp passen nicht zusammen.")
        return folder

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if not upload:
            return upload

        if upload.size > MAX_DOCUMENT_FILE_SIZE:
            raise forms.ValidationError(
                f"Die Datei darf höchstens {MAX_DOCUMENT_FILE_SIZE // (1024 * 1024)} MB gross sein."
            )

        name = upload.name or ""
        if "." not in name:
            raise forms.ValidationError("Die Datei benötigt eine Dateiendung.")
        extension = name.rsplit(".", 1)[-1].lower()
        if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))
            raise forms.ValidationError(f"Dieser Dateityp ist nicht erlaubt. Erlaubt sind: {allowed}.")

        content_type = getattr(upload, "content_type", "") or ""
        acceptable_types = ALLOWED_DOCUMENT_EXTENSIONS[extension] | _GENERIC_CONTENT_TYPES
        if content_type not in acceptable_types:
            raise forms.ValidationError("Der Dateityp der Datei passt nicht zur Dateiendung.")

        magic_signatures = DOCUMENT_MAGIC_BYTES.get(extension)
        if magic_signatures:
            header = upload.read(max(len(signature) for signature in magic_signatures))
            upload.seek(0)
            if not any(header.startswith(signature) for signature in magic_signatures):
                raise forms.ValidationError("Der Inhalt der Datei passt nicht zur Dateiendung.")

        return upload

    def save(self, commit=True):
        document = super().save(commit=False)
        document.visibility = self.scope
        if commit:
            document.save()
        return document


class DocumentEditForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ("title", "description", "folder")
        labels = {
            "title": "Titel",
            "description": "Beschreibung",
            "folder": "Ordner",
        }

    def __init__(self, *args, document=None, **kwargs):
        super().__init__(*args, **kwargs)
        if document is None:
            raise ValueError("document is required")
        self.document = document
        self.fields["description"].required = False
        self.fields["folder"].required = False
        self.fields["folder"].queryset = DocumentFolder.objects.filter(scope=document.visibility).order_by("name")
        self.fields["folder"].empty_label = "Ohne Ordner"
        self.fields["folder"].label_from_instance = lambda folder: folder.path_label

    def clean_folder(self):
        folder = self.cleaned_data["folder"]
        if folder is None:
            return folder
        if folder.scope != self.document.visibility:
            raise forms.ValidationError("Ordner und Dokumenttyp passen nicht zusammen.")
        return folder
