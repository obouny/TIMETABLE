from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden

from .models import Utilisateur


def est_cd(utilisateur: Utilisateur) -> bool:
    return utilisateur.is_authenticated and utilisateur.role == Utilisateur.Role.CD


def est_enseignant(utilisateur: Utilisateur) -> bool:
    return (
        utilisateur.is_authenticated
        and utilisateur.role == Utilisateur.Role.ENSEIGNANT
    )


def est_etudiant(utilisateur: Utilisateur) -> bool:
    return utilisateur.is_authenticated and utilisateur.role == Utilisateur.Role.ETUDIANT


def cd_requis(vue: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:

    @login_required
    @wraps(vue)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not est_cd(request.user):
            return HttpResponseForbidden("Accès réservé au Chef de département.")
        return vue(request, *args, **kwargs)

    return wrapper
