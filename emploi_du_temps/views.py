from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from emploi_du_temps.forms import CreneauForm, EmploiDuTempsForm
from emploi_du_temps.grille import JOURS_EDT, PLAGES_HORAIRES, construire_grille, trouver_plage
from emploi_du_temps.permissions import cd_requis
from .models import Cours, Creneau, EmploiDuTemps, Option, Salle, Utilisateur


class ConnexionView(LoginView):
    """Page de connexion en français avec redirection vers le tableau de bord."""

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        return reverse_lazy("tableau_de_bord")


def accueil(request: HttpRequest) -> HttpResponse:
    """Page d'accueil publique de l'application."""
    if request.user.is_authenticated:
        return redirect("tableau_de_bord")
    return render(request, "emploi_du_temps/accueil.html")


@login_required
def tableau_de_bord(request: HttpRequest) -> HttpResponse:
    """Afficher le tableau de bord correspondant au rôle de l'utilisateur."""
    utilisateur = request.user
    context = {"utilisateur": utilisateur}

    if utilisateur.role == Utilisateur.Role.CD:
        template = "emploi_du_temps/tableaux_de_bord/cd.html"
        context.update(
            {
                "nb_enseignants": Utilisateur.objects.filter(
                    role=Utilisateur.Role.ENSEIGNANT
                ).count(),
                "nb_cours": Cours.objects.count(),
                "nb_salles": Salle.objects.count(),
                "nb_options": Option.objects.count(),
                "nb_emplois": EmploiDuTemps.objects.count(),
                "nb_brouillons": EmploiDuTemps.objects.filter(
                    statut=EmploiDuTemps.Statut.BROUILLON
                ).count(),
                "nb_publies": EmploiDuTemps.objects.filter(
                    statut=EmploiDuTemps.Statut.PUBLIE
                ).count(),
                "emplois_recents": EmploiDuTemps.objects.select_related("option")[:5],
            }
        )
    elif utilisateur.role == Utilisateur.Role.ENSEIGNANT:
        template = "emploi_du_temps/tableaux_de_bord/enseignant.html"
        context["emplois_du_temps"] = EmploiDuTemps.objects.filter(
            statut=EmploiDuTemps.Statut.PUBLIE,
            creneaux__enseignant=utilisateur,
        ).select_related("option").distinct()
    elif utilisateur.role == Utilisateur.Role.ETUDIANT:
        template = "emploi_du_temps/tableaux_de_bord/etudiant.html"
        context["emplois_du_temps"] = EmploiDuTemps.objects.filter(
            statut=EmploiDuTemps.Statut.PUBLIE
        ).select_related("option")
    else:
        return HttpResponseForbidden("Rôle utilisateur non autorisé.")

    return render(request, template, context)


def deconnexion(request: HttpRequest) -> HttpResponse:
    """Déconnecter l'utilisateur puis revenir à la page de connexion."""
    logout(request)
    messages.success(request, "Vous êtes déconnecté.")
    return redirect("login")


# ─────────────────────────────────────────────
#  ENSEIGNANTS
# ─────────────────────────────────────────────

@login_required
def enseignant_liste(request):
    enseignants = Utilisateur.objects.filter(role=Utilisateur.Role.ENSEIGNANT)
    return render(request, "emploi_du_temps/ressources/enseignants/liste.html", {
        "enseignants": enseignants
    })


@login_required
def enseignant_creer(request):
    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        prenom = request.POST.get("prenom", "").strip()
        email = request.POST.get("email", "").strip()
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        if not all([nom, prenom, email, username, password]):
            messages.error(request, "Tous les champs sont obligatoires.")
        elif Utilisateur.objects.filter(email=email).exists():
            messages.error(request, "Cet email est déjà utilisé.")
        elif Utilisateur.objects.filter(username=username).exists():
            messages.error(request, "Ce nom d'utilisateur est déjà pris.")
        else:
            Utilisateur.objects.create_user(
                username=username,
                email=email,
                password=password,
                nom=nom,
                prenom=prenom,
                role=Utilisateur.Role.ENSEIGNANT,
            )
            messages.success(request, f"Enseignant {prenom} {nom} créé avec succès.")
            return redirect("enseignant_liste")

    return render(request, "emploi_du_temps/ressources/enseignants/form.html", {
        "action": "Créer", "enseignant": None
    })


@login_required
def enseignant_modifier(request, pk):
    enseignant = get_object_or_404(Utilisateur, pk=pk, role=Utilisateur.Role.ENSEIGNANT)
    if request.method == "POST":
        enseignant.nom = request.POST.get("nom", enseignant.nom).strip()
        enseignant.prenom = request.POST.get("prenom", enseignant.prenom).strip()
        enseignant.email = request.POST.get("email", enseignant.email).strip()
        enseignant.save()
        messages.success(request, "Enseignant modifié avec succès.")
        return redirect("enseignant_liste")
    return render(request, "emploi_du_temps/ressources/enseignants/form.html", {
        "action": "Modifier", "enseignant": enseignant
    })


@login_required
def enseignant_supprimer(request, pk):
    enseignant = get_object_or_404(Utilisateur, pk=pk, role=Utilisateur.Role.ENSEIGNANT)
    if request.method == "POST":
        enseignant.delete()
        messages.success(request, "Enseignant supprimé.")
        return redirect("enseignant_liste")
    return render(request, "emploi_du_temps/ressources/enseignants/confirmer_suppression.html", {
        "enseignant": enseignant
    })


# ─────────────────────────────────────────────
#  COURS
# ─────────────────────────────────────────────

@login_required
def cours_liste(request):
    cours = Cours.objects.select_related("option").all()
    return render(request, "emploi_du_temps/ressources/cours/liste.html", {"cours": cours})


@login_required
def cours_creer(request):
    options = Option.objects.all()
    if request.method == "POST":
        code = request.POST.get("codeCours", "").strip()
        intitule = request.POST.get("intitule", "").strip()
        volume = request.POST.get("volumeHoraire", "").strip()
        option_id = request.POST.get("option")

        if not all([code, intitule, volume, option_id]):
            messages.error(request, "Tous les champs sont obligatoires.")
        elif Cours.objects.filter(codeCours=code).exists():
            messages.error(request, "Ce code cours existe déjà.")
        else:
            Cours.objects.create(
                codeCours=code,
                intitule=intitule,
                volumeHoraire=int(volume),
                option_id=option_id,
            )
            messages.success(request, f"Cours {intitule} créé avec succès.")
            return redirect("cours_liste")

    return render(request, "emploi_du_temps/ressources/cours/form.html", {
        "action": "Créer", "cours": None, "options": options
    })


@login_required
def cours_modifier(request, pk):
    cours = get_object_or_404(Cours, codeCours=pk)
    options = Option.objects.all()
    if request.method == "POST":
        cours.intitule = request.POST.get("intitule", cours.intitule).strip()
        cours.volumeHoraire = int(request.POST.get("volumeHoraire", cours.volumeHoraire))
        cours.option_id = request.POST.get("option", cours.option_id)
        cours.save()
        messages.success(request, "Cours modifié avec succès.")
        return redirect("cours_liste")
    return render(request, "emploi_du_temps/ressources/cours/form.html", {
        "action": "Modifier", "cours": cours, "options": options
    })


@login_required
def cours_supprimer(request, pk):
    cours = get_object_or_404(Cours, codeCours=pk)
    if request.method == "POST":
        cours.delete()
        messages.success(request, "Cours supprimé.")
        return redirect("cours_liste")
    return render(request, "emploi_du_temps/ressources/cours/confirmer_suppression.html", {
        "cours": cours
    })


# ─────────────────────────────────────────────
#  SALLES
# ─────────────────────────────────────────────

@login_required
def salle_liste(request):
    salles = Salle.objects.all()
    return render(request, "emploi_du_temps/ressources/salles/liste.html", {"salles": salles})


@login_required
def salle_creer(request):
    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        capacite = request.POST.get("capacite", "").strip()
        site = request.POST.get("site", "").strip()

        if not all([nom, capacite, site]):
            messages.error(request, "Tous les champs sont obligatoires.")
        else:
            Salle.objects.create(nom=nom, capacite=int(capacite), site=site)
            messages.success(request, f"Salle {nom} créée avec succès.")
            return redirect("salle_liste")

    return render(request, "emploi_du_temps/ressources/salles/form.html", {
        "action": "Créer", "salle": None
    })


@login_required
def salle_modifier(request, pk):
    salle = get_object_or_404(Salle, pk=pk)
    if request.method == "POST":
        salle.nom = request.POST.get("nom", salle.nom).strip()
        salle.capacite = int(request.POST.get("capacite", salle.capacite))
        salle.site = request.POST.get("site", salle.site).strip()
        salle.save()
        messages.success(request, "Salle modifiée avec succès.")
        return redirect("salle_liste")
    return render(request, "emploi_du_temps/ressources/salles/form.html", {
        "action": "Modifier", "salle": salle
    })


@login_required
def salle_supprimer(request, pk):
    salle = get_object_or_404(Salle, pk=pk)
    if request.method == "POST":
        salle.delete()
        messages.success(request, "Salle supprimée.")
        return redirect("salle_liste")
    return render(request, "emploi_du_temps/ressources/salles/confirmer_suppression.html", {
        "salle": salle
    })


# ─────────────────────────────────────────────
#  OPTIONS (filières)
# ─────────────────────────────────────────────

@login_required
def option_liste(request):
    options = Option.objects.all()
    return render(request, "emploi_du_temps/ressources/options/liste.html", {"options": options})


@login_required
def option_creer(request):
    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        niveau = request.POST.get("niveau", "").strip()

        if not all([nom, niveau]):
            messages.error(request, "Tous les champs sont obligatoires.")
        else:
            Option.objects.create(nom=nom, niveau=int(niveau))
            messages.success(request, f"Option {nom} créée avec succès.")
            return redirect("option_liste")

    return render(request, "emploi_du_temps/ressources/options/form.html", {
        "action": "Créer", "option": None
    })


@login_required
def option_modifier(request, pk):
    option = get_object_or_404(Option, pk=pk)
    if request.method == "POST":
        option.nom = request.POST.get("nom", option.nom).strip()
        option.niveau = int(request.POST.get("niveau", option.niveau))
        option.save()
        messages.success(request, "Option modifiée avec succès.")
        return redirect("option_liste")
    return render(request, "emploi_du_temps/ressources/options/form.html", {
        "action": "Modifier", "option": option
    })


@login_required
def option_supprimer(request, pk):
    option = get_object_or_404(Option, pk=pk)
    if request.method == "POST":
        option.delete()
        messages.success(request, "Option supprimée.")
        return redirect("option_liste")
    return render(request, "emploi_du_temps/ressources/options/confirmer_suppression.html", {
        "option": option
    })
    

# ─────────────────────────────────────────────
#  EMPLOI DU TEMPS
# ─────────────────────────────────────────────

@login_required
@cd_requis
def liste_emplois_du_temps(request: HttpRequest) -> HttpResponse:
    """Lister les emplois du temps que le CD peut gérer."""
    emplois_du_temps = EmploiDuTemps.objects.select_related("option", "creePar")
    return render(
        request,
        "emploi_du_temps/emplois_du_temps/liste.html",
        {"emplois_du_temps": emplois_du_temps},
    )


@cd_requis
def creer_emploi_du_temps(request: HttpRequest) -> HttpResponse:
    """Créer un emploi du temps en brouillon."""
    if request.method == "POST":
        form = EmploiDuTempsForm(request.POST)
        if form.is_valid():
            emploi_du_temps = form.save(commit=False)
            emploi_du_temps.creePar = request.user
            emploi_du_temps.statut = EmploiDuTemps.Statut.BROUILLON
            emploi_du_temps.save()
            messages.success(request, "Emploi du temps brouillon créé.")
            return redirect("detail_emploi_du_temps", pk=emploi_du_temps.pk)
    else:
        form = EmploiDuTempsForm()

    return render(
        request,
        "emploi_du_temps/emplois_du_temps/formulaire.html",
        {"form": form, "titre": "Créer un emploi du temps"},
    )


@login_required
def detail_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    """Afficher le détail d'un emploi du temps selon le rôle de l'utilisateur."""
    emploi_du_temps = get_object_or_404(
        EmploiDuTemps.objects.select_related("option", "creePar").prefetch_related(
            "creneaux__cours", "creneaux__enseignant", "creneaux__salle"
        ),
        pk=pk,
    )
    est_cd = request.user.role == Utilisateur.Role.CD
    if not est_cd and emploi_du_temps.statut != EmploiDuTemps.Statut.PUBLIE:
        return HttpResponseForbidden("Cet emploi du temps n'est pas encore publié.")

    return render(
        request,
        "emploi_du_temps/emplois_du_temps/detail.html",
        {"emploi_du_temps": emploi_du_temps, "est_cd": est_cd},
    )


@cd_requis
def modifier_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    """Modifier les informations générales d'un emploi du temps."""
    emploi_du_temps = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        form = EmploiDuTempsForm(request.POST, instance=emploi_du_temps)
        if form.is_valid():
            form.save()
            messages.success(request, "Emploi du temps modifié.")
            return redirect("detail_emploi_du_temps", pk=emploi_du_temps.pk)
    else:
        form = EmploiDuTempsForm(instance=emploi_du_temps)

    return render(
        request,
        "emploi_du_temps/emplois_du_temps/formulaire.html",
        {"form": form, "titre": "Modifier un emploi du temps"},
    )


@cd_requis
def supprimer_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    """Supprimer un emploi du temps."""
    emploi_du_temps = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        emploi_du_temps.delete()
        messages.success(request, "Emploi du temps supprimé.")
        return redirect("liste_emplois_du_temps")
    return render(
        request,
        "emploi_du_temps/emplois_du_temps/confirmer_suppression.html",
        {"emploi_du_temps": emploi_du_temps},
    )


@cd_requis
def publier_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    """Publier un emploi du temps brouillon."""
    emploi_du_temps = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        emploi_du_temps.statut = EmploiDuTemps.Statut.PUBLIE
        emploi_du_temps.datePublication = timezone.now()
        emploi_du_temps.save(update_fields=["statut", "datePublication"])
        messages.success(request, "Emploi du temps publié.")
    return redirect("detail_emploi_du_temps", pk=emploi_du_temps.pk)


@cd_requis
def editeur_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    """Afficher l'éditeur sous la forme d'un emploi du temps officiel."""
    emploi_du_temps = get_object_or_404(
        EmploiDuTemps.objects.select_related("option", "creePar"),
        pk=pk,
    )
    creneaux = list(emploi_du_temps.creneaux.select_related("salle"))
    sites = sorted({creneau.salle.site for creneau in creneaux if creneau.salle.site})
    salles = sorted({creneau.salle.nom for creneau in creneaux if creneau.salle.nom})

    return render(
        request,
        "emploi_du_temps/emplois_du_temps/editeur.html",
        {
            "emploi_du_temps": emploi_du_temps,
            "jours": JOURS_EDT,
            "lignes": construire_grille(emploi_du_temps),
            "plages": PLAGES_HORAIRES,
            "date_fin_semaine": emploi_du_temps.semaine + timedelta(days=5),
            "site_officiel": sites[0] if len(sites) == 1 else "à préciser",
            "salle_officielle": salles[0] if len(salles) == 1 else "selon créneau",
        },
    )


def _initial_creneau_depuis_cellule(request: HttpRequest) -> dict:
    """Préremplir le formulaire quand le CD clique sur une cellule."""
    plage = trouver_plage(request.GET.get("plage", ""))
    jour = request.GET.get("jour")
    if not plage or plage.get("pause") or jour not in dict(JOURS_EDT):
        return {}
    return {
        "jour": jour,
        "heureDebut": plage["debut"],
        "heureFin": plage["fin"],
    }


@cd_requis
def ajouter_creneau(request: HttpRequest, emploi_pk: int) -> HttpResponse:
    """Ajouter un créneau à un emploi du temps."""
    emploi_du_temps = get_object_or_404(EmploiDuTemps, pk=emploi_pk)
    if request.method == "POST":
        form = CreneauForm(request.POST, emploi_du_temps=emploi_du_temps)
        if form.is_valid():
            form.save()
            messages.success(request, "Créneau ajouté.")
            return redirect("editeur_emploi_du_temps", pk=emploi_du_temps.pk)
    else:
        form = CreneauForm(
            emploi_du_temps=emploi_du_temps,
            initial=_initial_creneau_depuis_cellule(request),
        )

    return render(
        request,
        "emploi_du_temps/creneaux/formulaire.html",
        {"form": form, "emploi_du_temps": emploi_du_temps, "titre": "Ajouter un créneau"},
    )


@cd_requis
def modifier_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    """Modifier un créneau existant."""
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi_du_temps = creneau.emploiDuTemps
    if request.method == "POST":
        form = CreneauForm(
            request.POST,
            instance=creneau,
            emploi_du_temps=emploi_du_temps,
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Créneau modifié.")
            return redirect("detail_emploi_du_temps", pk=emploi_du_temps.pk)
    else:
        form = CreneauForm(instance=creneau, emploi_du_temps=emploi_du_temps)

    return render(
        request,
        "emploi_du_temps/creneaux/formulaire.html",
        {"form": form, "emploi_du_temps": emploi_du_temps, "titre": "Modifier un créneau"},
    )


@cd_requis
def supprimer_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    """Supprimer un créneau."""
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi_du_temps = creneau.emploiDuTemps
    if request.method == "POST":
        creneau.delete()
        messages.success(request, "Créneau supprimé.")
        return redirect("detail_emploi_du_temps", pk=emploi_du_temps.pk)
    return render(
        request,
        "emploi_du_temps/creneaux/confirmer_suppression.html",
        {"creneau": creneau, "emploi_du_temps": emploi_du_temps},
    )


def _reponse_edition_cellule(
    request: HttpRequest,
    emploi_du_temps: EmploiDuTemps,
    message: str,
    statut: int = 200,
) -> HttpResponse:
    """Répondre en JSON pour le drag/drop ou rediriger en HTML classique."""
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"message": message}, status=statut)
    if statut >= 400:
        messages.error(request, message)
    else:
        messages.success(request, message)
    return redirect("editeur_emploi_du_temps", pk=emploi_du_temps.pk)


def _appliquer_cellule_officielle(
    creneau: Creneau,
    jour: str,
    plage_id: str,
) -> str | None:
    """Appliquer une cellule officielle à un créneau ou retourner une erreur."""
    plage = trouver_plage(plage_id)
    if not plage or plage.get("pause"):
        return "Plage horaire invalide."
    if jour not in dict(JOURS_EDT):
        return "Jour invalide."

    creneau.jour = jour
    creneau.heureDebut = plage["debut"]
    creneau.heureFin = plage["fin"]
    try:
        creneau.full_clean()
    except ValidationError as erreur:
        return " ".join(erreur.messages)
    creneau.save()
    return None


@cd_requis
def deplacer_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    """Déplacer un créneau par glisser-déposer vers une cellule officielle."""
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi_du_temps = creneau.emploiDuTemps
    if request.method != "POST":
        return redirect("editeur_emploi_du_temps", pk=emploi_du_temps.pk)

    erreur = _appliquer_cellule_officielle(
        creneau,
        request.POST.get("jour", ""),
        request.POST.get("plage", ""),
    )
    if erreur:
        return _reponse_edition_cellule(request, emploi_du_temps, erreur, statut=400)
    return _reponse_edition_cellule(request, emploi_du_temps, "Créneau déplacé.")


@cd_requis
def copier_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    """Copier un créneau vers une autre cellule officielle."""
    source = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi_du_temps = source.emploiDuTemps
    if request.method != "POST":
        return redirect("editeur_emploi_du_temps", pk=emploi_du_temps.pk)

    copie = Creneau(
        emploiDuTemps=emploi_du_temps,
        cours=source.cours,
        enseignant=source.enseignant,
        salle=source.salle,
        option=source.option,
    )
    erreur = _appliquer_cellule_officielle(
        copie,
        request.POST.get("jour", ""),
        request.POST.get("plage", ""),
    )
    if erreur:
        return _reponse_edition_cellule(request, emploi_du_temps, erreur, statut=400)
    return _reponse_edition_cellule(request, emploi_du_temps, "Créneau copié.")