from django import forms
from django.core.exceptions import ValidationError

from .models import Cours, Creneau, EmploiDuTemps, Salle, Utilisateur
from .grille import PLAGES_HORAIRES, JOURS_EDT, trouver_plage


class EmploiDuTempsForm(forms.ModelForm):
    class Meta:
        model = EmploiDuTemps
        fields = ["semaine"]
        widgets = {"semaine": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_semaine(self):
        from datetime import timedelta

        d = self.cleaned_data.get("semaine")
        if d:
            return d - timedelta(days=d.weekday())
        return d


class CreneauForm(forms.ModelForm):
    """Formulaire créneaux lié à un EmploiDuTemps existant (éditeur officiel)."""
    class Meta:
        model = Creneau
        fields = ["jour", "heureDebut", "heureFin", "cours", "enseignant", "salle"]
        widgets = {
            "heureDebut": forms.TimeInput(attrs={"type": "time"}),
            "heureFin": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, emploi_du_temps: EmploiDuTemps, **kwargs):
        super().__init__(*args, **kwargs)
        self.emploi_du_temps = emploi_du_temps
        self.fields["cours"].queryset = Cours.objects.select_related("option").all()
        self.fields["enseignant"].queryset = Utilisateur.objects.filter(role=Utilisateur.Role.ENSEIGNANT)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cd = super().clean()
        jour = cd.get("jour")
        heure_debut = cd.get("heureDebut")
        heure_fin = cd.get("heureFin")
        enseignant = cd.get("enseignant")
        salle = cd.get("salle")
        cours = cd.get("cours")
        if not all([jour, heure_debut, heure_fin, enseignant, salle, cours]):
            return cd
        if heure_debut >= heure_fin:
            raise ValidationError("L'heure de début doit être avant l'heure de fin.")
        chevauchements = Creneau.objects.filter(
            emploiDuTemps__semaine=self.emploi_du_temps.semaine,
            jour=jour, heureDebut__lt=heure_fin, heureFin__gt=heure_debut,
        ).exclude(pk=self.instance.pk)
        if chevauchements.filter(salle=salle).exists():
            raise ValidationError("Cette salle est déjà occupée sur ce créneau.")
        if chevauchements.filter(enseignant=enseignant).exists():
            raise ValidationError("Cet enseignant est déjà affecté sur ce créneau.")
        if chevauchements.filter(option=cours.option).exists():
            raise ValidationError("Cette option a déjà un cours sur ce créneau.")
        return cd

    def save(self, commit=True):
        creneau = super().save(commit=False)
        creneau.emploiDuTemps = self.emploi_du_temps
        creneau.option = creneau.cours.option
        if commit:
            creneau.save()
        return creneau


# ── Choix pour le formulaire direct ──────────────────────────────────────────
PLAGE_CHOICES = [
    (p["id"], p["label"]) for p in PLAGES_HORAIRES if not p.get("pause")
]
JOUR_CHOICES = [(code, label) for code, label in JOURS_EDT]


class CreneauDirectForm(forms.Form):
    """Formulaire de création/modification de créneau directement depuis la grille semaine."""
    semaine    = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Semaine (lundi)")
    jour       = forms.ChoiceField(choices=[("", "— Sélectionner —")] + JOUR_CHOICES, label="Jour")
    plage      = forms.ChoiceField(choices=[("", "— Sélectionner —")] + PLAGE_CHOICES, label="Créneau horaire")
    cours      = forms.ModelChoiceField(queryset=Cours.objects.all(), label="Cours")
    enseignant = forms.ModelChoiceField(
        queryset=Utilisateur.objects.filter(role=Utilisateur.Role.ENSEIGNANT),
        label="Enseignant",
    )
    salle      = forms.ModelChoiceField(queryset=Salle.objects.all(), label="Salle")

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["cours"].queryset = Cours.objects.select_related("option").all()

    def clean_semaine(self):
        """Force la date au lundi de la semaine — sécurité côté serveur."""
        from datetime import timedelta
        d = self.cleaned_data.get('semaine')
        if d:
            return d - timedelta(days=d.weekday())  # lundi = 0
        return d

    def clean_plage(self):
        plage_id = self.cleaned_data.get("plage")
        if not trouver_plage(plage_id):
            raise ValidationError("Créneau horaire invalide.")
        return plage_id

    def clean_jour(self):
        jour = self.cleaned_data.get("jour")
        if jour not in dict(JOURS_EDT):
            raise ValidationError("Jour invalide.")
        return jour
