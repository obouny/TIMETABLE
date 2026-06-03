from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import Cours, Creneau, EmploiDuTemps, Option, Salle, Utilisateur
from .grille import PLAGES_HORAIRES, JOURS_EDT, trouver_plage


class CoursModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        ue_label = obj.ue.intituleUE if getattr(obj, "ue", None) else "UE non renseignée"
        return f"{obj.codeCours} — {obj.intitule} — UE : {ue_label} ({obj.option.nom})"


class UtilisateurRoleCreationForm(forms.ModelForm):
    """Création d'un utilisateur métier avec rôle imposé par la vue."""

    password = forms.CharField(
        label="Mot de passe",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Utilisateur
        fields = ["nom", "prenom", "email", "username", "option"]

    def __init__(self, *args, role: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role
        self.fields["option"].queryset = Option.objects.all()
        self.fields["option"].required = role == Utilisateur.Role.ETUDIANT
        if role != Utilisateur.Role.ETUDIANT:
            self.fields.pop("option")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            password_validation.validate_password(password, self.instance)
        return password

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if Utilisateur.objects.filter(email__iexact=email).exists():
            raise ValidationError("Cet email est déjà utilisé.")
        return email

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if Utilisateur.objects.filter(username__iexact=username).exists():
            raise ValidationError("Ce nom d'utilisateur est déjà pris.")
        return username

    def save(self, commit=True):
        utilisateur = super().save(commit=False)
        utilisateur.role = self.role
        if self.role != Utilisateur.Role.ETUDIANT:
            utilisateur.option = None
        utilisateur.set_password(self.cleaned_data["password"])
        if commit:
            utilisateur.full_clean()
            utilisateur.save()
        return utilisateur


class UtilisateurRoleModificationForm(forms.ModelForm):
    """Modification des informations métier d'un utilisateur sans changer son rôle."""

    class Meta:
        model = Utilisateur
        fields = ["nom", "prenom", "email", "option", "is_active"]

    def __init__(self, *args, role: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role
        self.fields["option"].queryset = Option.objects.all()
        self.fields["option"].required = role == Utilisateur.Role.ETUDIANT
        if role != Utilisateur.Role.ETUDIANT:
            self.fields.pop("option")
        self.fields["is_active"].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        qs = Utilisateur.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Cet email est déjà utilisé.")
        return email

    def save(self, commit=True):
        utilisateur = super().save(commit=False)
        utilisateur.role = self.role
        if self.role != Utilisateur.Role.ETUDIANT:
            utilisateur.option = None
        if commit:
            utilisateur.full_clean()
            utilisateur.save()
        return utilisateur


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
        self.fields["cours"].queryset = Cours.objects.select_related("ue", "option").all()
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
    cours      = CoursModelChoiceField(queryset=Cours.objects.none(), label="Cours")
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
        self.fields["cours"].queryset = Cours.objects.select_related("ue", "option").all()

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
