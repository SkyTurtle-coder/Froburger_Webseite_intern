from django.http import JsonResponse

from .public_members import build_public_members_payload


def v1_public_members_api(request):
    return JsonResponse(build_public_members_payload())
