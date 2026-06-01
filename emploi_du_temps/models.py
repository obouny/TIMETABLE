"""Modèles en français alignés sur les diagrammes fournis."""

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Utilisateur(AbstractUser):
    """Utilisateur de l'application : CD, enseignant ou étudiant."""

    class Role(models.TextChoices):
        CD = "CD", "Chef de département"
        ENSEIGNANT = "ENSEIGNANT", "Enseignant"
        ETUDIANT = "ETUDIANT", "Étudiant"

    email = models.EmailField(unique=True)
    nom = models.CharField(max_length=150)
    prenom = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=Role.choices)
    option = models.ForeignKey(
        "Option",
        on_delete=models.PROTECT,
        related_name="etudiants",
        verbose_name="option de l’étudiant",
        null=True,
        blank=True,
    )

    REQUIRED_FIELDS = ["email", "nom", "role"]

    def seConnecter(self) -> bool:
        return self.is_authenticated

    def seDeconnecter(self) -> None:
        return None

    def clean(self) -> None:
        super().clean()
        if self.role != self.Role.ETUDIANT and self.option_id:
            raise ValidationError(
                "Seuls les utilisateurs étudiants peuvent être rattachés à une option."
            )

    def consulterEmploiDuTemps(self):
        emplois = EmploiDuTemps.objects.filter(statut=EmploiDuTemps.Statut.PUBLIE)
        if self.role == self.Role.ENSEIGNANT:
            return emplois.filter(creneaux__enseignant=self).distinct()
        if self.role == self.Role.ETUDIANT and self.option_id:
            return emplois.filter(creneaux__option=self.option).distinct()
        return emplois

    def __str__(self) -> str:
        return f"{self.nom} {self.prenom} ({self.get_role_display()})"


class CD(Utilisateur):

    class Meta:
        proxy = True
        verbose_name = "chef de département"
        verbose_name_plural = "chefs de département"

    def gererRessources(self) -> bool:
        return self.role == Utilisateur.Role.CD

    def gererEmploiDuTemps(self) -> bool:
        return self.role == Utilisateur.Role.CD


class Enseignant(Utilisateur):

    class Meta:
        proxy = True
        verbose_name = "enseignant"
        verbose_name_plural = "enseignants"


class Etudiant(Utilisateur):

    class Meta:
        proxy = True
        verbose_name = "étudiant"
        verbose_name_plural = "étudiants"


class Option(models.Model):

    nom = models.CharField(max_length=150, unique=True)
    niveau = models.PositiveIntegerField()

    class Meta:
        ordering = ["niveau", "nom"]
        verbose_name = "option"
        verbose_name_plural = "options"

    def __str__(self) -> str:
        return f"{self.nom} - niveau {self.niveau}"


class Cours(models.Model):
    codeCours = models.CharField("code du cours", max_length=30, primary_key=True)
    intitule = models.CharField("intitulé", max_length=200)
    volumeHoraire = models.CharField("volume horaire", max_length=100, blank=True)
    option = models.ForeignKey(
        Option,
        on_delete=models.PROTECT,
        related_name="cours",
        verbose_name="option",
    )

    class Meta:
        ordering = ["codeCours"]
        verbose_name = "cours"
        verbose_name_plural = "cours"

    def __str__(self) -> str:
        return f"{self.codeCours} - {self.intitule}"


class Salle(models.Model):

    nom = models.CharField(max_length=100)
    capacite = models.PositiveIntegerField()
    site = models.CharField(max_length=150)

    class Meta:
        ordering = ["site", "nom"]
        constraints = [
            models.UniqueConstraint(fields=["site", "nom"], name="salle_unique_par_site"),
        ]
        verbose_name = "salle"
        verbose_name_plural = "salles"

    def __str__(self) -> str:
        return f"{self.site} - {self.nom}"


class EmploiDuTemps(models.Model):

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        PUBLIE = "PUBLIE", "Publié"
        ARCHIVE = "ARCHIVE", "Archivé"

    semaine = models.DateField()
    statut = models.CharField(
        max_length=20, choices=Statut.choices, default=Statut.BROUILLON
    )
    creePar = models.ForeignKey(
        Utilisateur, on_delete=models.PROTECT, related_name="emploisDuTempsCrees"
    )
    dateCreation = models.DateTimeField(auto_now_add=True)
    dateModification = models.DateTimeField(auto_now=True)
    datePublication = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-semaine"]
        unique_together = [["semaine"]]
        verbose_name = "emploi du temps"
        verbose_name_plural = "emplois du temps"

    def creer(self) -> None:
        self.save()

    def modifier(self) -> None:
        self.save()

    def supprimer(self) -> None:
        self.delete()

    def exporterPDF(self) -> str:
        return f"emploi-du-temps-{self.pk}.pdf"

    def __str__(self) -> str:
        return f"Semaine du {self.semaine} ({self.get_statut_display()})"

class Creneau(models.Model):
    
    class Jour(models.TextChoices):
        LUNDI = "LUNDI", "Lundi"
        MARDI = "MARDI", "Mardi"
        MERCREDI = "MERCREDI", "Mercredi"
        JEUDI = "JEUDI", "Jeudi"
        VENDREDI = "VENDREDI", "Vendredi"
        SAMEDI = "SAMEDI", "Samedi"
        
    emploiDuTemps = models.ForeignKey(
        EmploiDuTemps,
        on_delete=models.CASCADE,
        related_name="creneaux",
        verbose_name="emploi du temps",
    )
    jour = models.CharField("jour", max_length=20, choices=Jour.choices)
    heureDebut = models.TimeField("heure de début")
    heureFin = models.TimeField("heure de fin")
    cours = models.ForeignKey(
        Cours,
        on_delete=models.PROTECT,
        related_name="creneaux",
        verbose_name="cours",
    )
    enseignant = models.ForeignKey(
        Utilisateur,
        on_delete=models.PROTECT,
        related_name="creneauxEnseignes",
        limit_choices_to={"role": Utilisateur.Role.ENSEIGNANT},
        verbose_name="enseignant",
    )
    salle = models.ForeignKey(
        Salle,
        on_delete=models.PROTECT,
        related_name="creneaux",
        verbose_name="salle",
    )
    option = models.ForeignKey(
        Option,
        on_delete=models.PROTECT,
        related_name="creneaux",
        verbose_name="option",
    )
    
    class Meta:
        ordering = ["jour", "heureDebut"]
        constraints = [
            models.CheckConstraint(
                condition=Q(heureDebut__lt=models.F("heureFin")),
                name="creneau_heure_debut_avant_fin",
            ),
        ]
        verbose_name = "créneau"
        verbose_name_plural = "créneaux"

    def clean(self) -> None:
        super().clean()
        if self.heureDebut and self.heureFin and self.heureDebut >= self.heureFin:
            raise ValidationError("L'heure de début doit être avant l'heure de fin.")

        champs_requis = [
            self.emploiDuTemps_id,
            self.jour,
            self.heureDebut,
            self.heureFin,
            self.salle_id,
            self.enseignant_id,
            self.cours_id,
        ]
        if not all(champs_requis):
            return

        chevauchements = Creneau.objects.filter(
            emploiDuTemps__semaine=self.emploiDuTemps.semaine,
            jour=self.jour,
            heureDebut__lt=self.heureFin,
            heureFin__gt=self.heureDebut,
        ).exclude(pk=self.pk)

        if chevauchements.filter(salle=self.salle).exists():
            raise ValidationError("Cette salle est déjà occupée sur ce créneau.")
        if chevauchements.filter(enseignant=self.enseignant).exists():
            raise ValidationError("Cet enseignant est déjà affecté sur ce créneau.")
        option = self.option or getattr(self.cours, "option", None)
        if option and chevauchements.filter(option=option).exists():
            raise ValidationError("Cette option a déjà un cours sur ce créneau.")

    def affecter(self) -> None:
        """Affecter le créneau après validation des conflits."""
        self.full_clean()
        self.save()

    def deplacer(self, jour: str, heureDebut, heureFin) -> None:
        """Déplacer le créneau puis valider les conflits."""
        self.jour = jour
        self.heureDebut = heureDebut
        self.heureFin = heureFin
        self.affecter()

    def supprimer(self) -> None:
        """Supprimer le créneau."""
        self.delete()

    def __str__(self) -> str:
        return f"{self.jour} {self.heureDebut}-{self.heureFin} : {self.cours}"


class Conflit(models.Model):

    type = models.CharField(max_length=100)
    description = models.TextField()
    creneau = models.ForeignKey(
        Creneau,
        on_delete=models.CASCADE,
        related_name="conflits",
        null=True,
        blank=True,
    )
    dateDetection = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-dateDetection"]
        verbose_name = "conflit"
        verbose_name_plural = "conflits"

    def detecter(self) -> bool:
        return True

    def signaler(self) -> str:
        return self.description

    def __str__(self) -> str:
        return f"{self.type} - {self.description[:60]}"