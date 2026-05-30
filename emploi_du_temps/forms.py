from django import forms
from django.core.exceptions import ValidationError

from .models import Cours, Creneau, EmploiDuTemps, Utilisateur


class EmploiDuTempsForm(forms.ModelForm):

    class Meta:
        model = EmploiDuTemps
        fields = ["semaine", "option"]
        widgets = {
            "semaine": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class CreneauForm(forms.ModelForm):

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
        self.fields["cours"].queryset = Cours.objects.filter(
            option=emploi_du_temps.option
        )
        self.fields["enseignant"].queryset = Utilisateur.objects.filter(
            role=Utilisateur.Role.ENSEIGNANT
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned_data = super().clean()
        jour = cleaned_data.get("jour")
        heure_debut = cleaned_data.get("heureDebut")
        heure_fin = cleaned_data.get("heureFin")
        enseignant = cleaned_data.get("enseignant")
        salle = cleaned_data.get("salle")

        if not all([jour, heure_debut, heure_fin, enseignant, salle]):
            return cleaned_data

        if heure_debut >= heure_fin:
            raise ValidationError("L'heure de début doit être avant l'heure de fin.")

        chevauchements = Creneau.objects.filter(
            emploiDuTemps__semaine=self.emploi_du_temps.semaine,
            jour=jour,
            heureDebut__lt=heure_fin,
            heureFin__gt=heure_debut,
        ).exclude(pk=self.instance.pk)

        if chevauchements.filter(salle=salle).exists():
            raise ValidationError("Cette salle est déjà occupée sur ce créneau.")
        if chevauchements.filter(enseignant=enseignant).exists():
            raise ValidationError("Cet enseignant est déjà affecté sur ce créneau.")
        if chevauchements.filter(option=self.emploi_du_temps.option).exists():
            raise ValidationError("Cette option a déjà un cours sur ce créneau.")

        return cleaned_data

    def save(self, commit=True):
        creneau = super().save(commit=False)
        creneau.emploiDuTemps = self.emploi_du_temps
        creneau.option = self.emploi_du_temps.option
        if commit:
            creneau.save()
        return creneau