from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from emploi_du_temps.forms import (
    CreneauDirectForm,
    EmploiDuTempsForm,
    UtilisateurRoleCreationForm,
    UtilisateurRoleModificationForm,
)
from emploi_du_temps.grille import JOURS_EDT, PLAGES_HORAIRES, construire_grille_semaine, trouver_plage
from emploi_du_temps.permissions import cd_requis
from .models import Cours, Creneau, EmploiDuTemps, Option, Salle, UE, Utilisateur


class ConnexionView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        return reverse_lazy("tableau_de_bord")


def accueil(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("tableau_de_bord")
    return render(request, "emploi_du_temps/accueil.html")


@login_required
def tableau_de_bord(request: HttpRequest) -> HttpResponse:
    utilisateur = request.user
    context = {"utilisateur": utilisateur}

    if utilisateur.role == Utilisateur.Role.CD:
        template = "emploi_du_temps/tableaux_de_bord/cd.html"
        context.update({
            "nb_enseignants": Utilisateur.objects.filter(role=Utilisateur.Role.ENSEIGNANT).count(),
            "nb_etudiants": Utilisateur.objects.filter(role=Utilisateur.Role.ETUDIANT).count(),
            "nb_cours": Cours.objects.count(),
            "nb_ues": UE.objects.count(),
            "nb_salles": Salle.objects.count(),
            "nb_options": Option.objects.count(),
            "nb_emplois": EmploiDuTemps.objects.count(),
            "nb_brouillons": EmploiDuTemps.objects.filter(statut=EmploiDuTemps.Statut.BROUILLON).count(),
            "nb_publies": EmploiDuTemps.objects.filter(statut=EmploiDuTemps.Statut.PUBLIE).count(),
            "emplois_recents": EmploiDuTemps.objects.select_related("creePar")[:5],
        })
    elif utilisateur.role == Utilisateur.Role.ENSEIGNANT:
        template = "emploi_du_temps/tableaux_de_bord/enseignant.html"
        context["emplois_du_temps"] = EmploiDuTemps.objects.filter(
            statut=EmploiDuTemps.Statut.PUBLIE,
            creneaux__enseignant=utilisateur,
        ).distinct()
    elif utilisateur.role == Utilisateur.Role.ETUDIANT:
        template = "emploi_du_temps/tableaux_de_bord/etudiant.html"
        emplois_du_temps = EmploiDuTemps.objects.filter(statut=EmploiDuTemps.Statut.PUBLIE)
        if utilisateur.option_id:
            emplois_du_temps = emplois_du_temps.filter(creneaux__option=utilisateur.option).distinct()
        else:
            emplois_du_temps = emplois_du_temps.none()
        context["emplois_du_temps"] = emplois_du_temps
    else:
        return HttpResponseForbidden("Rôle utilisateur non autorisé.")

    return render(request, template, context)


@login_required
@require_POST
def deconnexion(request: HttpRequest) -> HttpResponse:
    logout(request)
    messages.success(request, "Vous êtes déconnecté.")
    return redirect("login")


# ─────────────────────────────────────────────
#  GRILLE EDT PAR SEMAINE (style PHP)
# ─────────────────────────────────────────────

def _get_lundi(semaine_str: str | None) -> date:
    """Retourne le lundi de la semaine donnée ou de la semaine courante."""
    if semaine_str:
        try:
            d = date.fromisoformat(semaine_str)
            return d - timedelta(days=d.weekday())
        except ValueError:
            pass
    today = date.today()
    return today - timedelta(days=today.weekday())


@login_required
def grille_edt(request: HttpRequest, semaine: str | None = None) -> HttpResponse:
    """Grille EDT par semaine — vue principale (équivalent PHP /edt)."""
    semaine_date = _get_lundi(semaine or request.GET.get("semaine"))
    salles = Salle.objects.all()
    salle_id_param = request.GET.get("salle_id", "")
    try:
        salle_id = int(salle_id_param) if salle_id_param else None
    except (TypeError, ValueError):
        salle_id = None
    if salle_id and not salles.filter(pk=salle_id).exists():
        salle_id = None
    if not salle_id:
        premiere_salle = salles.first()
        salle_id = premiere_salle.pk if premiere_salle else None
    est_cd = request.user.role == Utilisateur.Role.CD

    lignes = construire_grille_semaine(
        semaine_date,
        salle_id=salle_id,
        utilisateur=request.user,
    )

    # Semaines déjà planifiées
    semaines_dispo_qs = EmploiDuTemps.objects.all()
    if not est_cd:
        semaines_dispo_qs = semaines_dispo_qs.filter(statut=EmploiDuTemps.Statut.PUBLIE)
        if request.user.role == Utilisateur.Role.ENSEIGNANT:
            semaines_dispo_qs = semaines_dispo_qs.filter(creneaux__enseignant=request.user)
        elif request.user.role == Utilisateur.Role.ETUDIANT:
            if request.user.option_id:
                semaines_dispo_qs = semaines_dispo_qs.filter(creneaux__option=request.user.option)
            else:
                semaines_dispo_qs = semaines_dispo_qs.none()
    semaines_dispo = (
        semaines_dispo_qs.values_list("semaine", flat=True)
        .distinct()
        .order_by("semaine")
    )

    # Emplois de cette semaine (pour publication / export)
    emplois_semaine = EmploiDuTemps.objects.filter(semaine=semaine_date).prefetch_related("creneaux")
    if not est_cd:
        emplois_semaine = emplois_semaine.filter(statut=EmploiDuTemps.Statut.PUBLIE)
        if request.user.role == Utilisateur.Role.ENSEIGNANT:
            emplois_semaine = emplois_semaine.filter(creneaux__enseignant=request.user).distinct()
        elif request.user.role == Utilisateur.Role.ETUDIANT:
            if request.user.option_id:
                emplois_semaine = emplois_semaine.filter(creneaux__option=request.user.option).distinct()
            else:
                emplois_semaine = emplois_semaine.none()

    return render(request, "emploi_du_temps/grille/index.html", {
        "semaine": semaine_date,
        "semaine_prev": semaine_date - timedelta(weeks=1),
        "semaine_next": semaine_date + timedelta(weeks=1),
        "jours": JOURS_EDT,
        "lignes": lignes,
        "plages": PLAGES_HORAIRES,
        "salles": salles,
        "salle_id_actif": salle_id,
        "semaines_dispo": semaines_dispo,
        "est_cd": est_cd,
        "emplois_semaine": emplois_semaine,
    })


@cd_requis
def ajouter_creneau_grille(request: HttpRequest) -> HttpResponse:
    """Formulaire d'ajout d'un créneau depuis la grille (équivalent PHP /edt/create)."""
    semaine_str = request.GET.get("semaine") or request.POST.get("semaine") or str(date.today())
    semaine_date = _get_lundi(semaine_str)

    # Préremplissage si clic sur une cellule
    salle_initiale = request.GET.get("salle") or request.GET.get("salle_id") or ""
    if salle_initiale:
        try:
            salle_initiale = str(Salle.objects.get(pk=int(salle_initiale)).pk)
        except (Salle.DoesNotExist, TypeError, ValueError):
            salle_initiale = ""

    initial = {
        "semaine": semaine_date,
        "salle": salle_initiale,
        "jour": request.GET.get("jour", ""),
        "plage": request.GET.get("plage", ""),
    }

    if request.method == "POST":
        form = CreneauDirectForm(request.POST)
        if form.is_valid():
            # On récupère ou crée l'EmploiDuTemps brouillon global pour cette semaine.
            # Toujours utiliser LE LUNDI de la semaine comme clé
            semaine_lundi = _get_lundi(str(form.cleaned_data["semaine"]))
            emploi, _ = EmploiDuTemps.objects.get_or_create(
                semaine=semaine_lundi,
                defaults={"creePar": request.user, "statut": EmploiDuTemps.Statut.BROUILLON},
            )
            try:
                plage = trouver_plage(form.cleaned_data["plage"])
                creneau = Creneau(
                    emploiDuTemps=emploi,
                    option=form.cleaned_data["cours"].option,
                    jour=form.cleaned_data["jour"],
                    heureDebut=plage["debut"],
                    heureFin=plage["fin"],
                    cours=form.cleaned_data["cours"],
                    enseignant=form.cleaned_data["enseignant"],
                    salle=form.cleaned_data["salle"],
                )
                creneau.full_clean()
                creneau.save()
                messages.success(request, "Créneau ajouté avec succès.")
            except ValidationError as e:
                for msg in e.messages:
                    messages.error(request, msg)
                return render(request, "emploi_du_temps/grille/formulaire.html", {
                    "form": form,
                    "semaine": semaine_date,
                    "titre": "Ajouter un créneau",
                    "plages": PLAGES_HORAIRES,
                    "jours": JOURS_EDT,
                })
            return redirect(f"/emplois-du-temps/grille/{semaine_lundi.isoformat()}/?salle_id={form.cleaned_data['salle'].pk}")

        return render(request, "emploi_du_temps/grille/formulaire.html", {
            "form": form,
            "semaine": semaine_date,
            "titre": "Ajouter un créneau",
            "plages": PLAGES_HORAIRES,
            "jours": JOURS_EDT,
        })

    form = CreneauDirectForm(initial=initial)
    return render(request, "emploi_du_temps/grille/formulaire.html", {
        "form": form,
        "semaine": semaine_date,
        "titre": "Ajouter un créneau",
        "plages": PLAGES_HORAIRES,
        "jours": JOURS_EDT,
    })


@cd_requis
def modifier_creneau_grille(request: HttpRequest, pk: int) -> HttpResponse:
    """Modifier un créneau depuis la grille."""
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps", "cours", "enseignant", "salle", "option"), pk=pk)
    semaine = creneau.emploiDuTemps.semaine

    if request.method == "POST":
        form = CreneauDirectForm(request.POST, instance=creneau)
        if form.is_valid():
            try:
                plage = trouver_plage(form.cleaned_data["plage"])
                creneau.jour = form.cleaned_data["jour"]
                creneau.heureDebut = plage["debut"]
                creneau.heureFin = plage["fin"]
                creneau.cours = form.cleaned_data["cours"]
                creneau.option = form.cleaned_data["cours"].option
                creneau.enseignant = form.cleaned_data["enseignant"]
                creneau.salle = form.cleaned_data["salle"]
                creneau.full_clean()
                creneau.save()
                messages.success(request, "Créneau modifié avec succès.")
            except ValidationError as e:
                for msg in e.messages:
                    messages.error(request, msg)
                return render(request, "emploi_du_temps/grille/formulaire.html", {
                    "form": form, "semaine": semaine, "titre": "Modifier un créneau",
                    "creneau": creneau, "plages": PLAGES_HORAIRES, "jours": JOURS_EDT,
                })
            return redirect(f"/emplois-du-temps/grille/{semaine.isoformat()}/?salle_id={creneau.salle_id}")
    else:
        # Préremplir le formulaire avec les valeurs existantes
        # Trouver la plage correspondante
        plage_id = ""
        for p in PLAGES_HORAIRES:
            if p["debut"] == creneau.heureDebut and p["fin"] == creneau.heureFin:
                plage_id = p["id"]
                break
        form = CreneauDirectForm(initial={
            "semaine": semaine.isoformat(),
            "jour": creneau.jour,
            "plage": plage_id,
            "cours": creneau.cours,
            "enseignant": creneau.enseignant,
            "salle": creneau.salle,
        }, instance=creneau)

    return render(request, "emploi_du_temps/grille/formulaire.html", {
        "form": form, "semaine": semaine, "titre": "Modifier un créneau",
        "creneau": creneau, "plages": PLAGES_HORAIRES, "jours": JOURS_EDT,
    })


@cd_requis
def supprimer_creneau_grille(request: HttpRequest, pk: int) -> HttpResponse:
    """Supprimer un créneau depuis la grille."""
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    semaine = creneau.emploiDuTemps.semaine
    if request.method == "POST":
        creneau.delete()
        messages.success(request, "Créneau supprimé.")
        return redirect(f"/emplois-du-temps/grille/{semaine.isoformat()}/?salle_id={creneau.salle_id}")
    return render(request, "emploi_du_temps/grille/confirmer_suppression.html", {
        "creneau": creneau, "semaine": semaine,
    })


@cd_requis
def publier_semaine(request: HttpRequest) -> HttpResponse:
    """Publie tous les emplois du temps brouillons de la semaine donnée."""
    if request.method != "POST":
        return redirect("grille_edt")
    semaine_str = request.POST.get("semaine", "")
    semaine_lundi = _get_lundi(semaine_str)
    emplois = EmploiDuTemps.objects.filter(semaine=semaine_lundi, statut=EmploiDuTemps.Statut.BROUILLON)
    count = emplois.update(statut=EmploiDuTemps.Statut.PUBLIE, datePublication=timezone.now())
    if count:
        messages.success(request, f"{count} emploi(s) du temps publié(s) pour la semaine du {semaine_lundi.strftime('%d/%m/%Y')}.")
    else:
        messages.info(request, "Aucun brouillon à publier pour cette semaine.")
    return redirect(f"/emplois-du-temps/grille/{semaine_lundi.isoformat()}/")


@cd_requis
def depublier_semaine(request: HttpRequest) -> HttpResponse:
    """Repasse les emplois du temps de la semaine en brouillon."""
    if request.method != "POST":
        return redirect("grille_edt")
    semaine_str = request.POST.get("semaine", "")
    semaine_lundi = _get_lundi(semaine_str)
    count = EmploiDuTemps.objects.filter(semaine=semaine_lundi, statut=EmploiDuTemps.Statut.PUBLIE).update(statut=EmploiDuTemps.Statut.BROUILLON)
    messages.success(request, f"{count} emploi(s) repassé(s) en brouillon.")
    return redirect(f"/emplois-du-temps/grille/{semaine_lundi.isoformat()}/")


@cd_requis
def ajax_conflits(request: HttpRequest) -> JsonResponse:
    """Vérification AJAX des conflits (équivalent PHP /edt/check-conflicts)."""
    if request.method != "POST":
        return JsonResponse({"conflits": [], "count": 0})

    semaine_str = request.POST.get("semaine", "")
    cours_id = request.POST.get("cours_id")
    enseignant_id = request.POST.get("enseignant_id")
    salle_id = request.POST.get("salle_id")
    plage_id = request.POST.get("plage", "")
    jour = request.POST.get("jour", "")
    exclude_id = request.POST.get("exclude_id")

    plage = trouver_plage(plage_id)
    if not plage or not semaine_str or not jour:
        return JsonResponse({"conflits": [], "count": 0})

    try:
        semaine_date = _get_lundi(semaine_str)
    except Exception:
        return JsonResponse({"conflits": [], "count": 0})

    qs = Creneau.objects.filter(
        emploiDuTemps__semaine=semaine_date,
        jour=jour,
        heureDebut__lt=plage["fin"],
        heureFin__gt=plage["debut"],
    ).select_related("cours", "enseignant", "salle", "option")

    if exclude_id:
        try:
            qs = qs.exclude(pk=int(exclude_id))
        except (TypeError, ValueError):
            pass

    conflits = []
    if salle_id:
        try:
            qs_salle = qs.filter(salle_id=int(salle_id))
        except (TypeError, ValueError):
            qs_salle = Creneau.objects.none()
        for c in qs_salle:
            conflits.append({
                "type": "salle",
                "message": f"Conflit de SALLE : « {c.salle.nom} » est déjà occupée le {c.get_jour_display()} de {c.heureDebut.strftime('%H:%M')} à {c.heureFin.strftime('%H:%M')} par le cours {c.cours.intitule} ({c.enseignant.prenom} {c.enseignant.nom}).",
            })
    if enseignant_id:
        try:
            qs_enseignant = qs.filter(enseignant_id=int(enseignant_id))
        except (TypeError, ValueError):
            qs_enseignant = Creneau.objects.none()
        for c in qs_enseignant:
            conflits.append({
                "type": "enseignant",
                "message": f"Conflit d'ENSEIGNANT : {c.enseignant.nom} {c.enseignant.prenom} est déjà programmé(e) le {c.get_jour_display()} de {c.heureDebut.strftime('%H:%M')} à {c.heureFin.strftime('%H:%M')} en salle {c.salle.nom} pour le cours {c.cours.intitule}.",
            })
    option_id = None
    if cours_id:
        option_id = Cours.objects.filter(pk=cours_id).values_list("option_id", flat=True).first()
    if option_id:
        for c in qs.filter(option_id=option_id):
            conflits.append({
                "type": "option",
                "message": f"Conflit OPTION : l'option « {c.option.nom} » a déjà un cours le {c.get_jour_display()} de {c.heureDebut.strftime('%H:%M')} à {c.heureFin.strftime('%H:%M')} ({c.cours.intitule} — salle {c.salle.nom}).",
            })

    # Dédupliquer
    seen = set()
    unique = []
    for conf in conflits:
        if conf["message"] not in seen:
            seen.add(conf["message"])
            unique.append(conf)

    return JsonResponse({"conflits": unique, "count": len(unique)})


@login_required
def ajax_cours_par_option(request: HttpRequest, option_id: int) -> JsonResponse:
    """Retourne les cours d'une option (équivalent PHP /edt/cours-par-filiere)."""
    cours = list(Cours.objects.filter(option_id=option_id).values("id", "codeCours", "intitule", "ue_id"))
    return JsonResponse(cours, safe=False)


# ─────────────────────────────────────────────
#  EMPLOIS DU TEMPS (liste + gestion statut)
# ─────────────────────────────────────────────

@login_required
@cd_requis
def liste_emplois_du_temps(request: HttpRequest) -> HttpResponse:
    emplois_du_temps = EmploiDuTemps.objects.select_related("creePar")
    return render(request, "emploi_du_temps/emplois_du_temps/liste.html", {
        "emplois_du_temps": emplois_du_temps,
    })


@cd_requis
def creer_emploi_du_temps(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = EmploiDuTempsForm(request.POST)
        if form.is_valid():
            emploi = form.save(commit=False)
            emploi.creePar = request.user
            emploi.statut = EmploiDuTemps.Statut.BROUILLON
            emploi.save()
            messages.success(request, "Emploi du temps brouillon créé.")
            return redirect("editeur_emploi_du_temps", pk=emploi.pk)
    else:
        form = EmploiDuTempsForm()
    return render(request, "emploi_du_temps/emplois_du_temps/formulaire.html", {
        "form": form, "titre": "Créer un emploi du temps",
    })


@login_required
def detail_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(
        EmploiDuTemps.objects.select_related("creePar")
        .prefetch_related("creneaux__cours", "creneaux__enseignant", "creneaux__salle"),
        pk=pk,
    )
    est_cd = request.user.role == Utilisateur.Role.CD
    if not est_cd and emploi.statut != EmploiDuTemps.Statut.PUBLIE:
        return HttpResponseForbidden("Cet emploi du temps n'est pas encore publié.")
    if request.user.role == Utilisateur.Role.ENSEIGNANT and not emploi.creneaux.filter(
        enseignant=request.user
    ).exists():
        return HttpResponseForbidden("Cet emploi du temps ne vous est pas affecté.")
    creneaux_visibles = emploi.creneaux.all()
    if request.user.role == Utilisateur.Role.ENSEIGNANT:
        creneaux_visibles = creneaux_visibles.filter(enseignant=request.user)
    if request.user.role == Utilisateur.Role.ETUDIANT:
        if not request.user.option_id or not emploi.creneaux.filter(option=request.user.option).exists():
            return HttpResponseForbidden("Cet emploi du temps ne correspond pas à votre option.")
        creneaux_visibles = creneaux_visibles.filter(option=request.user.option)
    return render(request, "emploi_du_temps/emplois_du_temps/detail.html", {
        "emploi_du_temps": emploi, "est_cd": est_cd, "creneaux_visibles": creneaux_visibles,
    })


@cd_requis
def modifier_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        form = EmploiDuTempsForm(request.POST, instance=emploi)
        if form.is_valid():
            form.save()
            messages.success(request, "Emploi du temps modifié.")
            return redirect("detail_emploi_du_temps", pk=emploi.pk)
    else:
        form = EmploiDuTempsForm(instance=emploi)
    return render(request, "emploi_du_temps/emplois_du_temps/formulaire.html", {
        "form": form, "titre": "Modifier un emploi du temps",
    })


@cd_requis
def supprimer_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        emploi.delete()
        messages.success(request, "Emploi du temps supprimé.")
        return redirect("liste_emplois_du_temps")
    return render(request, "emploi_du_temps/emplois_du_temps/confirmer_suppression.html", {
        "emploi_du_temps": emploi,
    })


@cd_requis
def publier_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        emploi.statut = EmploiDuTemps.Statut.PUBLIE
        emploi.datePublication = timezone.now()
        emploi.save(update_fields=["statut", "datePublication"])
        messages.success(request, "Emploi du temps publié.")
    return redirect("detail_emploi_du_temps", pk=emploi.pk)


@cd_requis
def editeur_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(
        EmploiDuTemps.objects.select_related("creePar"), pk=pk
    )
    from emploi_du_temps.grille import construire_grille
    creneaux = list(emploi.creneaux.select_related("salle"))
    sites = sorted({c.salle.site for c in creneaux if c.salle.site})
    salles = sorted({c.salle.nom for c in creneaux if c.salle.nom})
    return render(request, "emploi_du_temps/emplois_du_temps/editeur.html", {
        "emploi_du_temps": emploi,
        "jours": JOURS_EDT,
        "lignes": construire_grille(emploi),
        "plages": PLAGES_HORAIRES,
        "date_fin_semaine": emploi.semaine + timedelta(days=5),
        "site_officiel": sites[0] if len(sites) == 1 else "à préciser",
        "salle_officielle": salles[0] if len(salles) == 1 else "selon créneau",
    })


@cd_requis
def ajouter_creneau(request: HttpRequest, emploi_pk: int) -> HttpResponse:
    from emploi_du_temps.forms import CreneauForm
    emploi = get_object_or_404(EmploiDuTemps, pk=emploi_pk)
    if request.method == "POST":
        form = CreneauForm(request.POST, emploi_du_temps=emploi)
        if form.is_valid():
            form.save()
            messages.success(request, "Créneau ajouté.")
            return redirect("editeur_emploi_du_temps", pk=emploi.pk)
    else:
        plage = trouver_plage(request.GET.get("plage", ""))
        jour = request.GET.get("jour")
        initial = {}
        if plage and not plage.get("pause") and jour:
            initial = {"jour": jour, "heureDebut": plage["debut"], "heureFin": plage["fin"]}
        form = CreneauForm(emploi_du_temps=emploi, initial=initial)
    return render(request, "emploi_du_temps/creneaux/formulaire.html", {
        "form": form, "emploi_du_temps": emploi, "titre": "Ajouter un créneau",
    })


@cd_requis
def modifier_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    from emploi_du_temps.forms import CreneauForm
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi = creneau.emploiDuTemps
    if request.method == "POST":
        form = CreneauForm(request.POST, instance=creneau, emploi_du_temps=emploi)
        if form.is_valid():
            form.save()
            messages.success(request, "Créneau modifié.")
            return redirect("detail_emploi_du_temps", pk=emploi.pk)
    else:
        form = CreneauForm(instance=creneau, emploi_du_temps=emploi)
    return render(request, "emploi_du_temps/creneaux/formulaire.html", {
        "form": form, "emploi_du_temps": emploi, "titre": "Modifier un créneau",
    })


@cd_requis
def supprimer_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi = creneau.emploiDuTemps
    if request.method == "POST":
        creneau.delete()
        messages.success(request, "Créneau supprimé.")
        return redirect("detail_emploi_du_temps", pk=emploi.pk)
    return render(request, "emploi_du_temps/creneaux/confirmer_suppression.html", {
        "creneau": creneau, "emploi_du_temps": emploi,
    })


def _reponse_edition_cellule(request, emploi, message, statut=200):
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"message": message}, status=statut)
    if statut >= 400:
        messages.error(request, message)
    else:
        messages.success(request, message)
    return redirect("editeur_emploi_du_temps", pk=emploi.pk)


@cd_requis
def deplacer_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi = creneau.emploiDuTemps
    if request.method != "POST":
        return redirect("editeur_emploi_du_temps", pk=emploi.pk)
    plage = trouver_plage(request.POST.get("plage", ""))
    jour = request.POST.get("jour", "")
    if not plage or plage.get("pause") or jour not in dict(JOURS_EDT):
        return _reponse_edition_cellule(request, emploi, "Plage ou jour invalide.", 400)
    creneau.jour = jour
    creneau.heureDebut = plage["debut"]
    creneau.heureFin = plage["fin"]
    try:
        creneau.full_clean()
    except ValidationError as e:
        return _reponse_edition_cellule(request, emploi, " ".join(e.messages), 400)
    creneau.save()
    return _reponse_edition_cellule(request, emploi, "Créneau déplacé.")


@cd_requis
def copier_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    source = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi = source.emploiDuTemps
    if request.method != "POST":
        return redirect("editeur_emploi_du_temps", pk=emploi.pk)
    plage = trouver_plage(request.POST.get("plage", ""))
    jour = request.POST.get("jour", "")
    if not plage or plage.get("pause") or jour not in dict(JOURS_EDT):
        return _reponse_edition_cellule(request, emploi, "Plage ou jour invalide.", 400)
    copie = Creneau(
        emploiDuTemps=emploi, cours=source.cours,
        enseignant=source.enseignant, salle=source.salle, option=source.option,
        jour=jour, heureDebut=plage["debut"], heureFin=plage["fin"],
    )
    try:
        copie.full_clean()
    except ValidationError as e:
        return _reponse_edition_cellule(request, emploi, " ".join(e.messages), 400)
    copie.save()
    return _reponse_edition_cellule(request, emploi, "Créneau copié.")


# ─────────────────────────────────────────────
#  RESSOURCES
# ─────────────────────────────────────────────


def _utilisateur_liste(request, role: str, template: str, context_name: str):
    utilisateurs = Utilisateur.objects.filter(role=role).select_related("option")
    return render(request, template, {context_name: utilisateurs})


def _utilisateur_creer(request, role: str, template: str, redirect_name: str, label: str):
    if request.method == "POST":
        form = UtilisateurRoleCreationForm(request.POST, role=role)
        if form.is_valid():
            utilisateur = form.save()
            messages.success(request, f"{label} {utilisateur.nom} {utilisateur.prenom} créé avec succès.")
            return redirect(redirect_name)
    else:
        form = UtilisateurRoleCreationForm(role=role)
    return render(request, template, {"action": "Créer", "form": form, "label": label})


def _utilisateur_modifier(request, pk: int, role: str, template: str, redirect_name: str, label: str):
    utilisateur = get_object_or_404(Utilisateur, pk=pk, role=role)
    if request.method == "POST":
        form = UtilisateurRoleModificationForm(request.POST, instance=utilisateur, role=role)
        if form.is_valid():
            form.save()
            messages.success(request, f"{label} modifié avec succès.")
            return redirect(redirect_name)
    else:
        form = UtilisateurRoleModificationForm(instance=utilisateur, role=role)
    return render(request, template, {"action": "Modifier", "form": form, "label": label, "utilisateur": utilisateur})


def _utilisateur_supprimer(request, pk: int, role: str, template: str, redirect_name: str, label: str, context_name: str):
    utilisateur = get_object_or_404(Utilisateur, pk=pk, role=role)
    if request.method == "POST":
        try:
            utilisateur.delete()
        except ProtectedError:
            messages.error(request, f"Impossible de supprimer ce {label.lower()} car il est lié à des créneaux.")
            return redirect(redirect_name)
        messages.success(request, f"{label} supprimé.")
        return redirect(redirect_name)
    return render(request, template, {context_name: utilisateur, "label": label})


@cd_requis
def enseignant_liste(request):
    return _utilisateur_liste(
        request,
        Utilisateur.Role.ENSEIGNANT,
        "emploi_du_temps/ressources/enseignants/liste.html",
        "enseignants",
    )


@cd_requis
def enseignant_creer(request):
    return _utilisateur_creer(
        request,
        Utilisateur.Role.ENSEIGNANT,
        "emploi_du_temps/ressources/utilisateurs/form.html",
        "enseignant_liste",
        "Enseignant",
    )


@cd_requis
def enseignant_modifier(request, pk):
    return _utilisateur_modifier(
        request,
        pk,
        Utilisateur.Role.ENSEIGNANT,
        "emploi_du_temps/ressources/utilisateurs/form.html",
        "enseignant_liste",
        "Enseignant",
    )


@cd_requis
def enseignant_supprimer(request, pk):
    return _utilisateur_supprimer(
        request,
        pk,
        Utilisateur.Role.ENSEIGNANT,
        "emploi_du_temps/ressources/enseignants/confirmer_suppression.html",
        "enseignant_liste",
        "Enseignant",
        "enseignant",
    )


@cd_requis
def etudiant_liste(request):
    return _utilisateur_liste(
        request,
        Utilisateur.Role.ETUDIANT,
        "emploi_du_temps/ressources/etudiants/liste.html",
        "etudiants",
    )


@cd_requis
def etudiant_creer(request):
    return _utilisateur_creer(
        request,
        Utilisateur.Role.ETUDIANT,
        "emploi_du_temps/ressources/utilisateurs/form.html",
        "etudiant_liste",
        "Étudiant",
    )


@cd_requis
def etudiant_modifier(request, pk):
    return _utilisateur_modifier(
        request,
        pk,
        Utilisateur.Role.ETUDIANT,
        "emploi_du_temps/ressources/utilisateurs/form.html",
        "etudiant_liste",
        "Étudiant",
    )


@cd_requis
def etudiant_supprimer(request, pk):
    return _utilisateur_supprimer(
        request,
        pk,
        Utilisateur.Role.ETUDIANT,
        "emploi_du_temps/ressources/etudiants/confirmer_suppression.html",
        "etudiant_liste",
        "Étudiant",
        "etudiant",
    )

@cd_requis
def ue_liste(request):
    ues = UE.objects.prefetch_related("cours").all()
    return render(request, "emploi_du_temps/ressources/ues/liste.html", {"ues": ues})


@cd_requis
def ue_creer(request):
    if request.method == "POST":
        code = request.POST.get("codeUE", "").strip().upper()
        intitule = request.POST.get("intituleUE", "").strip()
        if not all([code, intitule]):
            messages.error(request, "Tous les champs sont obligatoires.")
        elif UE.objects.filter(codeUE=code).exists():
            messages.error(request, "Ce code UE existe déjà.")
        else:
            UE.objects.create(codeUE=code, intituleUE=intitule)
            messages.success(request, f"UE {code} créée avec succès.")
            return redirect("ue_liste")
    return render(request, "emploi_du_temps/ressources/ues/form.html", {"action": "Créer", "ue": None})


@cd_requis
def ue_modifier(request, pk):
    ue = get_object_or_404(UE, codeUE=pk)
    if request.method == "POST":
        ue.intituleUE = request.POST.get("intituleUE", ue.intituleUE).strip()
        if not ue.intituleUE:
            messages.error(request, "L’intitulé UE est obligatoire.")
        else:
            ue.save()
            messages.success(request, "UE modifiée avec succès.")
            return redirect("ue_liste")
    return render(request, "emploi_du_temps/ressources/ues/form.html", {"action": "Modifier", "ue": ue})


@cd_requis
def ue_supprimer(request, pk):
    ue = get_object_or_404(UE, codeUE=pk)
    if request.method == "POST":
        try:
            ue.delete()
        except ProtectedError:
            messages.error(request, "Impossible de supprimer cette UE car elle est liée à des cours.")
            return redirect("ue_liste")
        messages.success(request, "UE supprimée.")
        return redirect("ue_liste")
    return render(request, "emploi_du_temps/ressources/ues/confirmer_suppression.html", {"ue": ue})


@cd_requis
def cours_liste(request):
    cours = Cours.objects.select_related("ue", "option").all()
    return render(request, "emploi_du_temps/ressources/cours/liste.html", {"cours": cours})


@cd_requis
def cours_creer(request):
    options = Option.objects.all()
    ues = UE.objects.all()
    if request.method == "POST":
        ue_id = request.POST.get("ue")
        intitule = request.POST.get("intitule", "").strip()
        volume = request.POST.get("volumeHoraire", "").strip()
        option_id = request.POST.get("option")
        if not all([ue_id, intitule, option_id]):
            messages.error(request, "Tous les champs marqués * sont obligatoires.")
        else:
            cours = Cours(ue_id=ue_id, intitule=intitule, volumeHoraire=volume, option_id=option_id)
            try:
                cours.full_clean()
                cours.save()
            except ValidationError as e:
                for msg in e.messages:
                    messages.error(request, msg)
            else:
                messages.success(request, f"Cours {intitule} créé avec succès.")
                return redirect("cours_liste")
    return render(request, "emploi_du_temps/ressources/cours/form.html", {"action": "Créer", "cours": None, "options": options, "ues": ues})


@cd_requis
def cours_modifier(request, pk):
    cours = get_object_or_404(Cours.objects.select_related("ue", "option"), pk=pk)
    options = Option.objects.all()
    ues = UE.objects.all()
    if request.method == "POST":
        cours.ue_id = request.POST.get("ue", cours.ue_id)
        cours.intitule = request.POST.get("intitule", cours.intitule).strip()
        cours.volumeHoraire = request.POST.get("volumeHoraire", cours.volumeHoraire).strip()
        cours.option_id = request.POST.get("option", cours.option_id)
        try:
            cours.full_clean()
            cours.save()
        except ValidationError as e:
            for msg in e.messages:
                messages.error(request, msg)
        else:
            messages.success(request, "Cours modifié avec succès.")
            return redirect("cours_liste")
    return render(request, "emploi_du_temps/ressources/cours/form.html", {"action": "Modifier", "cours": cours, "options": options, "ues": ues})


@cd_requis
def cours_supprimer(request, pk):
    cours = get_object_or_404(Cours, pk=pk)
    if request.method == "POST":
        try:
            cours.delete()
        except ProtectedError:
            messages.error(request, "Impossible de supprimer ce cours car il est utilisé dans des créneaux.")
            return redirect("cours_liste")
        messages.success(request, "Cours supprimé.")
        return redirect("cours_liste")
    return render(request, "emploi_du_temps/ressources/cours/confirmer_suppression.html", {"cours": cours})

@cd_requis
def salle_liste(request):
    salles = Salle.objects.all()
    return render(request, "emploi_du_temps/ressources/salles/liste.html", {"salles": salles})

@cd_requis
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
    return render(request, "emploi_du_temps/ressources/salles/form.html", {"action": "Créer", "salle": None})

@cd_requis
def salle_modifier(request, pk):
    salle = get_object_or_404(Salle, pk=pk)
    if request.method == "POST":
        salle.nom = request.POST.get("nom", salle.nom).strip()
        salle.capacite = int(request.POST.get("capacite", salle.capacite))
        salle.site = request.POST.get("site", salle.site).strip()
        salle.save()
        messages.success(request, "Salle modifiée avec succès.")
        return redirect("salle_liste")
    return render(request, "emploi_du_temps/ressources/salles/form.html", {"action": "Modifier", "salle": salle})

@cd_requis
def salle_supprimer(request, pk):
    salle = get_object_or_404(Salle, pk=pk)
    if request.method == "POST":
        try:
            salle.delete()
        except ProtectedError:
            messages.error(request, "Impossible de supprimer cette salle car elle est utilisée dans des créneaux.")
            return redirect("salle_liste")
        messages.success(request, "Salle supprimée.")
        return redirect("salle_liste")
    return render(request, "emploi_du_temps/ressources/salles/confirmer_suppression.html", {"salle": salle})

@cd_requis
def option_liste(request):
    options = Option.objects.all()
    return render(request, "emploi_du_temps/ressources/options/liste.html", {"options": options})

@cd_requis
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
    return render(request, "emploi_du_temps/ressources/options/form.html", {"action": "Créer", "option": None})

@cd_requis
def option_modifier(request, pk):
    option = get_object_or_404(Option, pk=pk)
    if request.method == "POST":
        option.nom = request.POST.get("nom", option.nom).strip()
        option.niveau = int(request.POST.get("niveau", option.niveau))
        option.save()
        messages.success(request, "Option modifiée avec succès.")
        return redirect("option_liste")
    return render(request, "emploi_du_temps/ressources/options/form.html", {"action": "Modifier", "option": option})

@cd_requis
def option_supprimer(request, pk):
    option = get_object_or_404(Option, pk=pk)
    if request.method == "POST":
        try:
            option.delete()
        except ProtectedError:
            messages.error(request, "Impossible de supprimer cette option car elle est liée à des cours, créneaux ou étudiants.")
            return redirect("option_liste")
        messages.success(request, "Option supprimée.")
        return redirect("option_liste")
    return render(request, "emploi_du_temps/ressources/options/confirmer_suppression.html", {"option": option})
