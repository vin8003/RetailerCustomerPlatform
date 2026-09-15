"""
OE-124 / F-0027 — product photo bulk import (thin EXTEND).

Attaches files to existing ``Product.image`` (catalog default for POS and
owned apps). No second media library. Match by Product.id, barcode,
additional_barcodes, or ProductBatch.barcode in the caller's shop.
"""
import csv
import io
import os
import zipfile
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import Q, Subquery, TextField
from django.db.models.functions import Cast
from PIL import Image, UnidentifiedImageError
from rest_framework import status
from rest_framework.response import Response

from products.models import Product, ProductBatch
from retailers.models import OrgAuditLog
from retailers.organization import (
    ensure_org_rbac_bootstrap,
    get_organization_for_user,
    user_has_org_permission,
)

PERM_CATALOG_IMAGE = 'catalog.image'

ALLOWED_IMAGE_EXTENSIONS = frozenset({'jpg', 'jpeg', 'png', 'gif', 'webp'})
MANIFEST_BASENAMES = frozenset({'manifest.csv', 'images.csv', 'mapping.csv'})
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200
# Catalog match is keyed to import rows — never load the full shop.
MAX_MATCH_PRODUCTS = MAX_ROWS
_JUNK_BASENAMES = frozenset({'thumbs.db', 'desktop.ini'})

_AMBIGUOUS = object()

_IDENTITY_COLUMNS = ('product_id', 'id', 'sku', 'barcode')
_FILENAME_COLUMNS = ('filename', 'file', 'image', 'path')


def catalog_image_denied_response():
    return Response(
        {'error': 'Catalog image permission required'},
        status=status.HTTP_403_FORBIDDEN,
    )


def require_catalog_image(user, organization=None):
    """
    Return a 403/404 Response when the user may not bulk-import photos.

    Owner is implicit admin. On deny, refresh system Admin from the catalog
    then re-check so stale admin roles do not block after a catalog bump.
    """
    org = organization
    if org is None:
        org = get_organization_for_user(user)
    if org is None:
        return Response(
            {'error': 'Organization not found or access denied'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if user_has_org_permission(user, org, PERM_CATALOG_IMAGE):
        return None
    ensure_org_rbac_bootstrap(org)
    if user_has_org_permission(user, org, PERM_CATALOG_IMAGE):
        return None
    return catalog_image_denied_response()


def _extension(name):
    if not name or '.' not in name:
        return ''
    return name.rsplit('.', 1)[-1].lower()


def _basename(name):
    return os.path.basename((name or '').replace('\\', '/'))


def _stem(name):
    base = _basename(name)
    if '.' not in base:
        return base
    return base.rsplit('.', 1)[0]


def _is_hidden_or_junk(name):
    path = (name or '').replace('\\', '/')
    parts = [part for part in path.split('/') if part]
    if not parts:
        return True
    if any(part.startswith('.') or part == '__MACOSX' for part in parts):
        return True
    if _basename(path).lower() in _JUNK_BASENAMES:
        return True
    return False


def _safe_zip_member(name):
    path = (name or '').replace('\\', '/')
    if not path or path.startswith('/') or '..' in path.split('/'):
        return None
    if path.endswith('/'):
        return None
    if _is_hidden_or_junk(path):
        return None
    return path


def _file_size(file_obj):
    if file_obj is None:
        return 0
    size = getattr(file_obj, 'size', None)
    if size is not None:
        return size
    pos = file_obj.tell()
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(pos)
    return size


def _read_bytes(file_obj):
    file_obj.seek(0)
    data = file_obj.read()
    file_obj.seek(0)
    return data


def validate_image_payload(file_obj, name):
    """Return a row error code or None when the file can be attached."""
    if file_obj is None:
        return 'bad file'
    ext = _extension(name)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return 'wrong type'
    if _file_size(file_obj) > MAX_IMAGE_BYTES:
        return 'bad file'
    data = _read_bytes(file_obj)
    if not data:
        return 'bad file'
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return 'bad file'
    return None


def _as_upload(file_obj, name):
    data = _read_bytes(file_obj)
    content_type = getattr(file_obj, 'content_type', None) or 'application/octet-stream'
    return SimpleUploadedFile(_basename(name) or 'image.jpg', data, content_type=content_type)


def default_image_summary(product):
    if product is None:
        return {'product_id': None, 'image': '', 'image_url': ''}
    image_name = ''
    try:
        if product.image:
            image_name = product.image.name or ''
    except (ValueError, AttributeError):
        image_name = ''
    return {
        'product_id': product.id,
        'image': image_name,
        'image_url': product.image_url or '',
    }


def replace_product_default_image(product, image_file):
    """
    New file becomes ``Product.image``. Old file is deleted; ``image_url``
    and additional ``is_primary`` flags are cleared so they are not default.
    """
    if product.image:
        product.image.delete(save=False)
    product.image = image_file
    product.image_url = None
    product.save(update_fields=['image', 'image_url', 'updated_at'])
    product.additional_images.filter(is_primary=True).update(is_primary=False)
    return product


def record_product_image_audit(
    *,
    product,
    actor,
    organization,
    location=None,
    summary_before=None,
    summary_after=None,
):
    if organization is None or product is None:
        return None
    before = dict(summary_before or {})
    after = dict(summary_after or {})
    if before == after:
        return None
    from retailers.audit_log import record_org_audit_event

    return record_org_audit_event(
        organization=organization,
        actor=actor,
        action=OrgAuditLog.ACTION_UPDATE,
        object_type=OrgAuditLog.OBJECT_PRODUCT_IMAGE,
        object_id=product.id,
        summary_before=before,
        summary_after=after,
        location=location,
    )


def _normalize_header(value):
    return (value or '').strip().lower().replace(' ', '_')


def _cell(row, *names):
    for name in names:
        raw = row.get(name)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ''


def _parse_csv_mapping(file_obj):
    data = _read_bytes(file_obj)
    if isinstance(data, bytes):
        text = data.decode('utf-8-sig')
    else:
        text = data
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError('CSV has no header row')
    rows = []
    for index, raw in enumerate(reader, start=2):
        mapped = {_normalize_header(key): value for key, value in raw.items()}
        identity = _cell(mapped, *_IDENTITY_COLUMNS)
        filename = _cell(mapped, *_FILENAME_COLUMNS)
        rows.append({
            'row': index,
            'key': identity,
            'filename': filename,
        })
    return rows


def _index_files(files_by_name):
    """Exact path, lowercase basename, and unique stem → file.

    Same path or basename last-wins (later zip member / later upload).
    Same stem with two different names is ambiguous (CSV stem lookup
    returns no file) so a later exact-basename hit can still resolve.
    """
    by_path = {}
    by_base = {}
    stems = {}
    for name, file_obj in files_by_name.items():
        path_key = name.replace('\\', '/').lower()
        by_path[path_key] = (name, file_obj)
        base = _basename(name).lower()
        by_base[base] = (name, file_obj)  # last-win
        stem = _stem(name).lower()
        if stem in stems and stems[stem][0].lower() != name.lower():
            stems[stem] = None
        else:
            stems[stem] = (name, file_obj)
    return SimpleNamespace(by_path=by_path, by_base=by_base, stems=stems)


def _lookup_file(index, filename, fallback_key=''):
    candidates = []
    if filename:
        candidates.append(filename.replace('\\', '/').lower())
        candidates.append(_basename(filename).lower())
    if fallback_key:
        candidates.append(fallback_key.lower())
        candidates.append(_basename(fallback_key).lower())
    for candidate in candidates:
        if candidate in index.by_path:
            return index.by_path[candidate]
        if candidate in index.by_base:
            return index.by_base[candidate]
        stem = candidate.rsplit('.', 1)[0] if '.' in candidate else candidate
        hit = index.stems.get(stem)
        if hit:
            return hit
    return None


def _read_zip_members(archive):
    if _file_size(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError('Archive is too large')
    data = _read_bytes(archive)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError('Archive is not a valid zip') from exc
    files = {}
    manifest = None
    with zf:
        for info in zf.infolist():
            path = _safe_zip_member(info.filename)
            if path is None:
                continue
            if info.file_size > MAX_IMAGE_BYTES:
                oversized = SimpleUploadedFile(
                    _basename(path),
                    b'',
                    content_type='application/octet-stream',
                )
                oversized._too_large = True
                files[path] = oversized
                continue
            payload = zf.read(info)
            uploaded = SimpleUploadedFile(
                _basename(path),
                payload,
                content_type='application/octet-stream',
            )
            if _basename(path).lower() in MANIFEST_BASENAMES:
                manifest = uploaded
                continue
            files[path] = uploaded
    return files, manifest


def collect_import_rows(*, archive=None, csv_file=None, uploaded_files=None):
    """
    Build per-row work items from zip and/or csv+files.

    Returns (rows, error). ``error`` is a whole-request problem (400),
    not a per-row failure.
    """
    files_by_name = {}
    manifest = None

    if archive is not None:
        name = getattr(archive, 'name', '') or ''
        if not name.lower().endswith('.zip'):
            return [], 'Archive must be a zip file'
        try:
            files_by_name, manifest = _read_zip_members(archive)
        except ValueError as exc:
            return [], str(exc)

    for uploaded in uploaded_files or []:
        upload_name = getattr(uploaded, 'name', '') or ''
        if not upload_name:
            continue
        files_by_name[_basename(upload_name)] = uploaded

    mapping_source = csv_file or manifest
    index = _index_files(files_by_name)

    if mapping_source is not None:
        try:
            mapped = _parse_csv_mapping(mapping_source)
        except (UnicodeDecodeError, ValueError, csv.Error):
            return [], 'CSV could not be parsed'
        if not mapped:
            return [], 'CSV has no data rows'
        if len(mapped) > MAX_ROWS:
            return [], 'Too many rows'
        rows = []
        for item in mapped:
            key = item['key']
            filename = item['filename']
            found = _lookup_file(index, filename, fallback_key=key)
            rows.append({
                'row': item['row'],
                'key': key,
                'filename': filename or (found[0] if found else ''),
                'file': found[1] if found else None,
            })
        return rows, None

    # No CSV: ignore dotted junk (readme.txt, Thumbs.db). Same stem last-wins.
    by_stem = {}
    for name, file_obj in files_by_name.items():
        if _extension(name) not in ALLOWED_IMAGE_EXTENSIONS:
            continue
        by_stem[_stem(name).lower()] = (name, file_obj)
    image_items = list(by_stem.values())
    if not image_items:
        return [], 'No image files to import'
    if len(image_items) > MAX_ROWS:
        return [], 'Too many rows'
    rows = []
    for offset, (name, file_obj) in enumerate(sorted(image_items, key=lambda item: item[0].lower()), start=1):
        rows.append({
            'row': offset,
            'key': _stem(name),
            'filename': name,
            'file': file_obj,
        })
    return rows, None


def _unique_import_keys(keys):
    seen = []
    seen_lower = set()
    for key in keys or ():
        raw = str(key or '').strip()
        if not raw:
            continue
        marker = raw.lower()
        if marker in seen_lower:
            continue
        seen_lower.add(marker)
        seen.append(raw)
        if len(seen) >= MAX_MATCH_PRODUCTS:
            break
    return seen


def _extra_barcode_text_q(keys):
    """Match JSON-list barcodes without JSON ``contains`` (SQLite + Postgres)."""
    q = Q()
    for key in keys:
        needle = key.replace('\\', '\\\\').replace('"', '\\"')
        q |= Q(additional_barcodes_text__icontains=f'"{needle}"')
    return q


def _product_identity_q(keys):
    numeric_ids = [int(key) for key in keys if key.isdigit()]
    q = Q()
    if numeric_ids:
        q |= Q(pk__in=numeric_ids)
    for key in keys:
        q |= Q(barcode__iexact=key)
    extra = _extra_barcode_text_q(keys)
    if extra:
        q |= extra
    return q


def _batch_identity_q(keys):
    q = Q()
    for key in keys:
        q |= Q(barcode__iexact=key)
    extra = _extra_barcode_text_q(keys)
    if extra:
        q |= extra
    return q


def load_shop_product_index(retailer, keys=()):
    """Load products that can match ``keys``, capped at ``MAX_MATCH_PRODUCTS``.

    Key-scoped: does not scan the full shop catalog. Prefetches ``batches``
    so batch barcodes of a matched SKU stay in the index. Does not prefetch
    ``additional_images`` (unused here; ``is_primary`` is an UPDATE).
    """
    keys = _unique_import_keys(keys)
    if not keys:
        return {}, {}

    extra_text = Cast('additional_barcodes', TextField())
    batch_product_ids = (
        ProductBatch.objects.filter(retailer=retailer)
        .annotate(additional_barcodes_text=extra_text)
        .filter(_batch_identity_q(keys))
        .values('product_id')[:MAX_MATCH_PRODUCTS]
    )
    products = list(
        Product.objects.filter(retailer=retailer)
        .annotate(additional_barcodes_text=extra_text)
        .filter(_product_identity_q(keys) | Q(pk__in=Subquery(batch_product_ids)))
        .prefetch_related('batches')[:MAX_MATCH_PRODUCTS]
    )
    by_id = {}
    by_code = {}

    def add_code(code, product):
        if code is None:
            return
        key = str(code).strip().lower()
        if not key:
            return
        existing = by_code.get(key)
        if existing is None:
            by_code[key] = product
        elif existing is not product:
            by_code[key] = _AMBIGUOUS

    for product in products:
        by_id[product.id] = product
        add_code(product.id, product)
        add_code(product.barcode, product)
        extras = product.additional_barcodes or []
        if isinstance(extras, list):
            for extra in extras:
                add_code(extra, product)
        for batch in product.batches.all():
            add_code(batch.barcode, product)
            batch_extras = batch.additional_barcodes or []
            if isinstance(batch_extras, list):
                for extra in batch_extras:
                    add_code(extra, product)
    return by_id, by_code


def resolve_shop_product(key, by_id, by_code):
    if key is None:
        return None, 'missing SKU'
    raw = str(key).strip()
    if not raw:
        return None, 'missing SKU'
    if raw.isdigit():
        product = by_id.get(int(raw))
        if product is not None:
            return product, None
    hit = by_code.get(raw.lower())
    if hit is _AMBIGUOUS:
        return None, 'ambiguous SKU'
    if hit is None:
        return None, 'missing SKU'
    return hit, None


def import_product_photos_for_retailer(
    *,
    retailer,
    actor,
    organization=None,
    archive=None,
    csv_file=None,
    uploaded_files=None,
):
    """
    Attach images to matching shop SKUs. Row failures do not roll back
    successful rows. Returns a report dict or raises ValueError for
    whole-request problems.
    """
    rows, error = collect_import_rows(
        archive=archive,
        csv_file=csv_file,
        uploaded_files=uploaded_files,
    )
    if error:
        raise ValueError(error)

    org = organization if organization is not None else getattr(retailer, 'organization', None)
    by_id, by_code = load_shop_product_index(
        retailer,
        [item.get('key') or '' for item in rows],
    )
    results = []
    successful = 0
    failed = 0

    for item in rows:
        key = item.get('key') or ''
        filename = item.get('filename') or ''
        file_obj = item.get('file')
        row_number = item['row']
        product, match_error = resolve_shop_product(key, by_id, by_code)
        if match_error:
            failed += 1
            results.append({
                'row': row_number,
                'key': key,
                'status': 'failed',
                'error': match_error,
            })
            continue
        if file_obj is None:
            failed += 1
            results.append({
                'row': row_number,
                'key': key,
                'product_id': product.id,
                'status': 'failed',
                'error': 'bad file',
            })
            continue
        if getattr(file_obj, '_too_large', False):
            image_error = 'bad file'
        else:
            image_error = validate_image_payload(file_obj, filename or getattr(file_obj, 'name', ''))
        if image_error:
            failed += 1
            results.append({
                'row': row_number,
                'key': key,
                'product_id': product.id,
                'status': 'failed',
                'error': image_error,
            })
            continue
        try:
            upload = _as_upload(file_obj, filename or getattr(file_obj, 'name', 'image.jpg'))
            with transaction.atomic():
                locked = Product.objects.select_for_update().get(
                    pk=product.pk,
                    retailer=retailer,
                )
                before = default_image_summary(locked)
                replace_product_default_image(locked, upload)
                locked.refresh_from_db()
                after = default_image_summary(locked)
                record_product_image_audit(
                    product=locked,
                    actor=actor,
                    organization=org,
                    location=retailer,
                    summary_before=before,
                    summary_after=after,
                )
            successful += 1
            results.append({
                'row': row_number,
                'key': key,
                'product_id': locked.id,
                'status': 'attached',
            })
            by_id[locked.id] = locked
        except Product.DoesNotExist:
            failed += 1
            results.append({
                'row': row_number,
                'key': key,
                'status': 'failed',
                'error': 'missing SKU',
            })
        except (OSError, ValueError):
            failed += 1
            results.append({
                'row': row_number,
                'key': key,
                'product_id': product.id,
                'status': 'failed',
                'error': 'bad file',
            })

    return {
        'total_rows': len(rows),
        'successful_rows': successful,
        'failed_rows': failed,
        'results': results,
    }
