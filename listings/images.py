"""Server-side clean-up of newly uploaded item photos.

Every photo is re-encoded before it is stored, so that:

* the EXIF orientation is applied (phone photos stay upright), and then all
  metadata is dropped — EXIF (including GPS location), XMP, comments and PNG
  text chunks. Only the colour profile is kept, so colours look the same;
* the long edge is at most MAX_EDGE pixels (smaller images are never enlarged);
* the file format stays the same (JPEG, PNG or WebP). Multi-picture JPEGs
  (MPO, produced by some phone cameras) are stored as a plain JPEG of the
  main picture.

Upload limits (count, size, pixels, formats) are enforced by ItemForm before
this runs and are not changed by it. Existing stored photos are not touched.

Memory: decoding is the expensive part. A JPEG is decoded at reduced size
(cheap), but a PNG or WebP at the 25-megapixel limit can briefly need roughly
250-400 MB while it is decoded and shrunk. The image is shrunk in place before
any other step, and only one photo is decoded at a time per process
(PROCESSING_SLOTS), so concurrent uploads queue instead of multiplying that.
"""
import threading
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_EDGE = 2000
JPEG_QUALITY = 88
WEBP_QUALITY = 88
EXTENSIONS = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}
# Formats stored as another format: MPO is a JPEG with extra pictures attached.
FORMAT_ALIASES = {'MPO': 'JPEG'}
PROCESSING_SLOTS = threading.BoundedSemaphore(1)


class PhotoProcessingError(Exception):
    """The upload looked like an image but could not be decoded."""


def stored_format(image_format):
    """The format a photo is stored in, or None if it isn't supported."""
    image_format = FORMAT_ALIASES.get(image_format, image_format)
    return image_format if image_format in EXTENSIONS else None


def prepare_photo(uploaded_file):
    """Return a cleaned copy of an uploaded photo as a ContentFile."""
    with PROCESSING_SLOTS:
        return _prepare(uploaded_file)


def _prepare(uploaded_file):
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image_format = stored_format(image.format)
            if image_format is None:
                raise PhotoProcessingError(f'Unsupported format: {image.format}')
            icc_profile = image.info.get('icc_profile')
            if image_format == 'JPEG':
                # Let the JPEG decoder scale down while reading: faster and far
                # lighter on memory for large phone photos.
                image.draft(image.mode, (MAX_EDGE, MAX_EDGE))
            image.load()

            if image.mode == 'P' and max(image.size) > MAX_EDGE:
                # Palette images can only be resized with nearest-neighbour;
                # convert first so the downscaled photo stays smooth.
                image = image.convert('RGBA')
            if max(image.size) > MAX_EDGE:
                # In place, so the full-size pixels are released straight away.
                image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            # Rotate upright using the (still present) EXIF orientation.
            ImageOps.exif_transpose(image, in_place=True)
    except PhotoProcessingError:
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise PhotoProcessingError(str(error)) from error

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
