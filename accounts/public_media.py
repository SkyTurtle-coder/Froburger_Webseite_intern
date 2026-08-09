import hashlib
import shutil
from pathlib import Path
from urllib.parse import urljoin

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from PIL import Image, ImageOps, UnidentifiedImageError


PUBLIC_MEMBER_PHOTO_SIZES = (
    ("small", 160),
    ("medium", 320),
    ("large", 640),
)


def get_public_media_base_url():
    base_url = (getattr(settings, "PUBLIC_MEDIA_BASE_URL", "") or "").strip()
    if not base_url:
        return ""
    if not base_url.startswith(("http://", "https://")):
        raise ImproperlyConfigured("PUBLIC_MEDIA_BASE_URL must start with http:// or https://")
    return f"{base_url.rstrip('/')}/"


def public_media_url(relative_path):
    base_url = get_public_media_base_url()
    if not base_url:
        return ""
    clean_path = str(relative_path).replace("\\", "/").lstrip("/")
    return urljoin(base_url, clean_path)


def build_public_member_photo(profile):
    if not profile.photo:
        return {"fallback": True, "variants": {}}
    if not get_public_media_base_url():
        return {"fallback": True, "variants": {}}

    try:
        source_path = Path(profile.photo.path)
    except (NotImplementedError, ValueError):
        return {"fallback": True, "variants": {}}

    if not source_path.exists():
        return {"fallback": True, "variants": {}}

    try:
        variants = _ensure_derivatives(profile, source_path)
    except (OSError, UnidentifiedImageError, ValueError):
        return {"fallback": True, "variants": {}}

    return {
        "fallback": False,
        "variants": variants,
    }


def _ensure_derivatives(profile, source_path):
    public_root = Path(settings.MEDIA_ROOT) / "public" / "members" / str(profile.pk)
    public_root.mkdir(parents=True, exist_ok=True)

    with Image.open(source_path) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")

        smallest_edge = min(image.width, image.height)
        if smallest_edge <= 0:
            raise ValueError("Source image has no usable dimensions.")

        version = _build_version(source_path)
        stem = _safe_stem(source_path)
        variants = {}

        for variant_key, configured_size in PUBLIC_MEMBER_PHOTO_SIZES:
            target_size = min(configured_size, smallest_edge)
            derivative_name = f"{stem}-{version}-{target_size}.webp"
            derivative_path = public_root / derivative_name
            if not derivative_path.exists():
                fitted = ImageOps.fit(
                    image,
                    (target_size, target_size),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
                if fitted.mode != "RGB":
                    fitted = fitted.convert("RGB")
                fitted.save(derivative_path, format="WEBP", quality=82, method=6)

            relative_path = derivative_path.relative_to(settings.MEDIA_ROOT)
            variants[variant_key] = {
                "url": public_media_url(relative_path),
                "width": target_size,
                "height": target_size,
            }

    return variants


def purge_public_member_media(profile_pk):
    """Deletes every cached public-facing derivative for one profile.

    Safe to call unconditionally (a no-op if nothing was ever generated).
    Never touches the original Profile.photo upload - only the derived
    /media/public/members/<pk>/ files that _ensure_derivatives() creates,
    which are what nginx serves directly with no auth check (SEC-006: these
    were never cleaned up when a profile stopped being publicly listed).
    """
    public_root = Path(settings.MEDIA_ROOT) / "public" / "members" / str(profile_pk)
    shutil.rmtree(public_root, ignore_errors=True)


def _build_version(source_path):
    stat = source_path.stat()
    digest = hashlib.sha256(f"{source_path.name}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()
    return digest[:12]


def _safe_stem(source_path):
    stem = "".join(char for char in source_path.stem.lower() if char.isalnum() or char in ("-", "_"))
    return stem or "member-photo"
