from django.urls import path
from . import views

urlpatterns = [
    # ── Authentification ──────────────────────────
    path("", views.accueil, name="accueil"),
    path("connexion/", views.ConnexionView.as_view(), name="login"),
    path("deconnexion/", views.deconnexion, name="logout"),
    path("tableau-de-bord/", views.tableau_de_bord, name="tableau_de_bord"),

    # ── Enseignants ───────────────────────────────
    path("enseignants/", views.enseignant_liste, name="enseignant_liste"),
    path("enseignants/nouveau/", views.enseignant_creer, name="enseignant_creer"),
    path("enseignants/<int:pk>/modifier/", views.enseignant_modifier, name="enseignant_modifier"),
    path("enseignants/<int:pk>/supprimer/", views.enseignant_supprimer, name="enseignant_supprimer"),

    # ── Cours ─────────────────────────────────────
    path("cours/", views.cours_liste, name="cours_liste"),
    path("cours/nouveau/", views.cours_creer, name="cours_creer"),
    path("cours/<str:pk>/modifier/", views.cours_modifier, name="cours_modifier"),
    path("cours/<str:pk>/supprimer/", views.cours_supprimer, name="cours_supprimer"),

    # ── Salles ────────────────────────────────────
    path("salles/", views.salle_liste, name="salle_liste"),
    path("salles/nouvelle/", views.salle_creer, name="salle_creer"),
    path("salles/<int:pk>/modifier/", views.salle_modifier, name="salle_modifier"),
    path("salles/<int:pk>/supprimer/", views.salle_supprimer, name="salle_supprimer"),

    # ── Options (filières) ────────────────────────
    path("options/", views.option_liste, name="option_liste"),
    path("options/nouvelle/", views.option_creer, name="option_creer"),
    path("options/<int:pk>/modifier/", views.option_modifier, name="option_modifier"),
    path("options/<int:pk>/supprimer/", views.option_supprimer, name="option_supprimer"),
    
    # ── Emploi du temps ───────────────────────────
    path("emplois-du-temps/", views.liste_emplois_du_temps, name="liste_emplois_du_temps"),
    path("emplois-du-temps/creer/", views.creer_emploi_du_temps, name="creer_emploi_du_temps"),
    path("emplois-du-temps/<int:pk>/", views.detail_emploi_du_temps, name="detail_emploi_du_temps"),
    path("emplois-du-temps/<int:pk>/editeur/", views.editeur_emploi_du_temps, name="editeur_emploi_du_temps"),
    path("emplois-du-temps/<int:pk>/modifier/", views.modifier_emploi_du_temps, name="modifier_emploi_du_temps"),
    path("emplois-du-temps/<int:pk>/supprimer/", views.supprimer_emploi_du_temps, name="supprimer_emploi_du_temps"),
    path("emplois-du-temps/<int:pk>/publier/", views.publier_emploi_du_temps, name="publier_emploi_du_temps"),
    path("emplois-du-temps/<int:emploi_pk>/creneaux/ajouter/", views.ajouter_creneau, name="ajouter_creneau"),
    path("creneaux/<int:pk>/modifier/", views.modifier_creneau, name="modifier_creneau"),
    path("creneaux/<int:pk>/supprimer/", views.supprimer_creneau, name="supprimer_creneau"),
    path("creneaux/<int:pk>/deplacer/", views.deplacer_creneau, name="deplacer_creneau"),
    path("creneaux/<int:pk>/copier/", views.copier_creneau, name="copier_creneau"),
    
]