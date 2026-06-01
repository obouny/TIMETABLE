from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    CD,
    Conflit,
    Cours,
    Creneau,
    EmploiDuTemps,
    Enseignant,
    Etudiant,
    Option,
    Salle,
    Utilisateur,
)


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):

    fieldsets = UserAdmin.fieldsets + (
        ("Informations métier", {"fields": ("nom", "prenom", "role", "option")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Informations métier", {"fields": ("email", "nom", "prenom", "role", "option")}),
    )
    list_display = ("username", "email", "nom", "prenom", "role", "option", "is_staff")
    list_filter = ("role", "option", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "nom", "prenom")


@admin.register(CD)
class CDAdmin(UtilisateurAdmin):

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role=Utilisateur.Role.CD)


@admin.register(Enseignant)
class EnseignantAdmin(UtilisateurAdmin):

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role=Utilisateur.Role.ENSEIGNANT)


@admin.register(Etudiant)
class EtudiantAdmin(UtilisateurAdmin):

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role=Utilisateur.Role.ETUDIANT)


@admin.register(Option)
class OptionAdmin(admin.ModelAdmin):
    list_display = ("nom", "niveau")
    search_fields = ("nom",)
    list_filter = ("niveau",)


@admin.register(Cours)
class CoursAdmin(admin.ModelAdmin):
    list_display = ("codeCours", "intitule", "volumeHoraire", "option")
    search_fields = ("codeCours", "intitule")
    list_filter = ("option",)


@admin.register(Salle)
class SalleAdmin(admin.ModelAdmin):
    list_display = ("nom", "capacite", "site")
    search_fields = ("nom", "site")
    list_filter = ("site",)


class CreneauInline(admin.TabularInline):
    model = Creneau
    extra = 0
    fields = ("jour", "heureDebut", "heureFin", "cours", "enseignant", "salle")

    def save_new(self, form, commit=True):
        obj = super().save_new(form, commit=False)
        obj.option = obj.cours.option
        if commit:
            obj.save()
        return obj

    def save_existing(self, form, instance, commit=True):
        obj = super().save_existing(form, instance, commit=False)
        obj.option = obj.cours.option
        if commit:
            obj.save()
        return obj


@admin.register(EmploiDuTemps)
class EmploiDuTempsAdmin(admin.ModelAdmin):
    list_display = ("semaine", "statut", "creePar", "datePublication")
    list_filter = ("statut", "semaine")
    inlines = [CreneauInline]


@admin.register(Creneau)
class CreneauAdmin(admin.ModelAdmin):
    list_display = (
        "jour",
        "heureDebut",
        "heureFin",
        "cours",
        "enseignant",
        "salle",
        "option",
    )
    list_filter = ("jour", "salle", "option", "enseignant")
    search_fields = ("cours__codeCours", "cours__intitule", "salle__nom")


@admin.register(Conflit)
class ConflitAdmin(admin.ModelAdmin):
    list_display = ("type", "creneau", "dateDetection")
    search_fields = ("type", "description")