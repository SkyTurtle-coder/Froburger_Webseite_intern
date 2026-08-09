from django import forms

from .models import Document, DocumentFolder, FolderScope


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
