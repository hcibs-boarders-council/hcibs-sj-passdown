"""Server-side clean-up of newly uploaded item photos.

Every photo is re-encoded before it is stored, so that:

* the EXIF orientation is applied (phone photos stay upright), and then all
  metadata is dropped — EXIF (including GPS location), XMP, comments and PNG
  text chunks. Only the colour profile is kept, so colours look the same;
* the long edge is at most MAX_EDGE pixels (smaller images are never enlarged);
* the file format stays the same (JPEG, PNG or WebP).

Upload limits (count, size, pixels, formats) are enforced by ItemForm before
this runs and are not changed by it. Existing stored photos are not touched.
"""
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_EDGE = 2000
JPEG_QUALITY = 88
WEBP_QUALITY = 88
EXTENSIONS = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}


class PhotoProcessingError(Exception):
    """The upload looked like an image but could not be decoded."""


def prepare_photo(uploaded_file):
    """Return a cleaned copy of an uploaded photo as a ContentFile."""
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as source:
            image_format = source.format
            if image_format not in EXTENSIONS:
                raise PhotoProcessingError(f'Unsupported format: {image_format}')
            icc_profile = source.info.get('icc_profile')
            if image_format == 'JPEG':
                # Let the JPEG decoder scale down while reading: faster and far
                # lighter on memory for large phone photos.
                source.draft(source.mode, (MAX_EDGE, MAX_EDGE))
            image = ImageOps.exif_transpose(source)
            image.load()
    except PhotoProcessingError:
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise PhotoProcessingError(str(error)) from error

    if image.mode == 'P' and max(image.size) > MAX_EDGE:
        # Palette images can only be resized with nearest-neighbour; convert
        # first so the downscaled photo stays smooth.
        image = image.convert('RGBA')
    if max(image.size) > MAX_EDGE:
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)

    # Drop every piece of metadata Pillow could otherwise write back (for
    # example JPEG comments); keep only what is needed to render correctly.
    transparency = image.info.get('transparency')
    image.info = {} if transparency is None else {'transparency': transparency}

    options = {'icc_profile': icc_profile} if icc_profile else {}
    output = BytesIO()
    if image_format == 'JPEG':
        if image.mode not in ('RGB', 'L', 'CMYK'):
            image = image.convert('RGB')
        image.save(output, 'JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True, **options)
    elif image_format == 'PNG':
        image.save(output, 'PNG', optimize=True, **options)
    else:
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA' if 'A' in image.getbands() or transparency is not None else 'RGB')
        image.save(output, 'WEBP', quality=WEBP_QUALITY, method=4, **options)

    return ContentFile(output.getvalue(), name='photo' + EXTENSIONS[image_format])
