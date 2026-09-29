from django import forms

from .models import Comment, Issue


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ("title", "description", "pdf")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "pdf": forms.FileInput(attrs={"accept": "application/pdf,.pdf"}),
        }
        help_texts = {"pdf": "Eine PDF-Datei, maximal 20 MB. Beim Bearbeiten leer lassen, um die aktuelle Ausgabe zu behalten."}

    def clean_pdf(self):
        upload = self.cleaned_data["pdf"]
        if getattr(upload, "_committed", False):
            return upload
        if not upload.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Bitte eine PDF-Datei auswählen.")
        if upload.size > 20 * 1024 * 1024:
            raise forms.ValidationError("Das PDF darf höchstens 20 MB gross sein.")
        if upload.content_type not in ("application/pdf", "application/octet-stream", ""):
            raise forms.ValidationError("Bitte eine gültige PDF-Datei auswählen.")
        header = upload.read(5)
        upload.seek(0)
        if header != b"%PDF-":
            raise forms.ValidationError("Diese Datei ist kein gültiges PDF.")
        return upload


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ("body",)
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "maxlength": 5000})}
