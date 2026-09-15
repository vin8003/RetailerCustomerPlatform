"""
OE-124 / F-0027 — product photo bulk import (thin EXTEND).

Zip/csv+files attach to existing Product.image. Failed rows do not abort
the rest. Auth + catalog.image required. Replace clears the old default.
"""
import io
import zipfile
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBatch, ProductCategory, ProductImage
from products.photo_import import (
    PERM_CATALOG_IMAGE,
    import_product_photos_for_retailer,
    replace_product_default_image,
)
from retailers.models import OrgAuditLog, OrgRole, OrgStaffMembership, RetailerProfile
from retailers.organization import ensure_organization_for_profile


MINIMAL_GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00'
    b'!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01'
    b'\x00\x00\x02\x02D\x01\x00;'
)


def _gif(name):
    return SimpleUploadedFile(name, MINIMAL_GIF, content_type='image/gif')


def _zip_upload(name, members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for path, data in members.items():
            zf.writestr(path, data)
    return SimpleUploadedFile(name, buf.getvalue(), content_type='application/zip')


def _csv_upload(name, text):
    return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/csv')


def _make_retailer(username, shop_name):
    user = User.objects.create_user(
        username=username,
        email=f'{username}@test.com',
        password='TestPass123!',
        user_type='retailer',
        is_active=True,
    )
    profile = RetailerProfile.objects.create(
        user=user,
        shop_name=shop_name,
        address_line1='1 Main',
        city='City',
        state='State',
        pincode='110001',
        is_active=True,
        offers_delivery=True,
        offers_pickup=True,
    )
    ensure_organization_for_profile(profile, name=f'{shop_name} Org')
    return user, profile


def _make_staff(org, username, permissions):
    user = User.objects.create_user(
        username=username,
        email=f'{username}@test.com',
        password='TestPass123!',
        user_type='retailer',
        is_active=True,
    )
    role = OrgRole.objects.create(
        organization=org,
        slug=f'role_{username}',
        name=f'Role {username}',
        permissions=list(permissions),
        is_system=False,
    )
    OrgStaffMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_active=True,
    )
    return user


def _make_location_profile(user, org, shop_name):
    return RetailerProfile.objects.create(
        user=user,
        organization=org,
        shop_name=shop_name,
        address_line1='2 Side',
        city='City',
        state='State',
        pincode='110002',
        is_active=True,
        offers_delivery=True,
        offers_pickup=True,
    )


def _make_customer(username):
    return User.objects.create_user(
        username=username,
        email=f'{username}@test.com',
        password='TestPass123!',
        user_type='customer',
        is_active=True,
        is_email_verified=True,
    )


def _make_product(retailer, name, barcode=None, extra_barcodes=None):
    category = ProductCategory.objects.create(name=f'{name} Cat', retailer=retailer)
    return Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        price=Decimal('40.00'),
        quantity=10,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit='kg',
        barcode=barcode,
        additional_barcodes=list(extra_barcodes or []),
    )


@pytest.mark.django_db
class TestPhotoImportService:
    def test_zip_attaches_by_barcode(self):
        owner, shop = _make_retailer('oe124_svc_bar', 'OE124 Zip Barcode')
        product = _make_product(shop, 'Rice', barcode='890124001')

        report = import_product_photos_for_retailer(
            retailer=shop,
            actor=owner,
            organization=shop.organization,
            archive=_zip_upload('photos.zip', {'890124001.gif': MINIMAL_GIF}),
        )

        assert report['successful_rows'] == 1
        assert report['failed_rows'] == 0
        product.refresh_from_db()
        assert product.image
        assert product.image_display_url
        assert OrgAuditLog.objects.filter(
            organization=shop.organization,
            object_type=OrgAuditLog.OBJECT_PRODUCT_IMAGE,
            object_id=str(product.id),
        ).exists()

    def test_zip_attaches_by_product_id(self):
        owner, shop = _make_retailer('oe124_svc_id', 'OE124 Zip Id')
        product = _make_product(shop, 'Atta')

        report = import_product_photos_for_retailer(
            retailer=shop,
            actor=owner,
            organization=shop.organization,
            archive=_zip_upload('photos.zip', {f'{product.id}.gif': MINIMAL_GIF}),
        )

        assert report['successful_rows'] == 1
        product.refresh_from_db()
        assert product.image

    def test_csv_plus_files_attaches_and_reports_failed_rows(self):
        owner, shop = _make_retailer('oe124_svc_csv', 'OE124 Csv Files')
        good = _make_product(shop, 'Good Oil', barcode='890124010')
        keep = _make_product(shop, 'Keep Plain')

        csv_file = _csv_upload(
            'map.csv',
            'sku,filename\n'
            '890124010,oil.gif\n'
            'MISSING,nope.gif\n'
            '890124010,notes.txt\n',
        )
        report = import_product_photos_for_retailer(
            retailer=shop,
            actor=owner,
            organization=shop.organization,
            csv_file=csv_file,
            uploaded_files=[
                _gif('oil.gif'),
                SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain'),
            ],
        )

        assert report['total_rows'] == 3
        assert report['successful_rows'] == 1
        assert report['failed_rows'] == 2
        errors = {row['error'] for row in report['results'] if row['status'] == 'failed'}
        assert 'missing SKU' in errors
        assert 'wrong type' in errors
        good.refresh_from_db()
        keep.refresh_from_db()
        assert good.image
        assert not keep.image

    def test_bad_file_and_wrong_type_do_not_abort_good_row(self):
        owner, shop = _make_retailer('oe124_svc_bad', 'OE124 Bad Rows')
        good = _make_product(shop, 'Good Dal', barcode='890124020')
        rotten = _make_product(shop, 'Rotten Dal', barcode='890124021')

        report = import_product_photos_for_retailer(
            retailer=shop,
            actor=owner,
            organization=shop.organization,
            archive=_zip_upload(
                'mix.zip',
                {
                    '890124020.gif': MINIMAL_GIF,
                    '890124021.jpg': b'not-an-image',
                    'readme.txt': b'ignore',
                },
            ),
        )

        assert report['successful_rows'] == 1
        assert report['failed_rows'] >= 1
        good.refresh_from_db()
        rotten.refresh_from_db()
        assert good.image
        assert not rotten.image
        assert any(row.get('error') == 'bad file' for row in report['results'])

    def test_replace_clears_old_default_file_url_and_primary_flag(self):
        owner, shop = _make_retailer('oe124_svc_rep', 'OE124 Replace')
        product = _make_product(shop, 'Sugar', barcode='890124030')
        product.image = _gif('old.gif')
        product.image_url = 'https://example.com/old-default.jpg'
        product.save()
        extra = ProductImage.objects.create(
            product=product,
            image=_gif('gallery.gif'),
            is_primary=True,
        )
        old_name = product.image.name

        replace_product_default_image(product, _gif('new.gif'))
        product.refresh_from_db()
        extra.refresh_from_db()

        assert product.image
        assert product.image.name != old_name
        assert not product.image_url
        assert extra.is_primary is False
        assert 'old-default.jpg' not in (product.image_display_url or '')
        assert product.image_display_url

        report = import_product_photos_for_retailer(
            retailer=shop,
            actor=owner,
            organization=shop.organization,
            archive=_zip_upload('again.zip', {'890124030.gif': MINIMAL_GIF}),
        )
        assert report['successful_rows'] == 1
        product.refresh_from_db()
        extra.refresh_from_db()
        assert extra.is_primary is False
        assert not product.image_url

    def test_additional_and_batch_barcodes_match(self):
        owner, shop = _make_retailer('oe124_svc_alt', 'OE124 Alt Codes')
        extra = _make_product(
            shop, 'Extra Tea', barcode='890124040', extra_barcodes=['ALT124']
        )
        batched = _make_product(shop, 'Batch Tea', barcode='890124041')
        ProductBatch.objects.create(
            product=batched,
            retailer=shop,
            barcode='BATCH124',
            price=Decimal('40.00'),
            quantity=4,
        )

        report = import_product_photos_for_retailer(
            retailer=shop,
            actor=owner,
            organization=shop.organization,
            archive=_zip_upload(
                'alt.zip',
                {
                    'ALT124.gif': MINIMAL_GIF,
                    'BATCH124.gif': MINIMAL_GIF,
                },
            ),
        )

        assert report['successful_rows'] == 2
        extra.refresh_from_db()
        batched.refresh_from_db()
        assert extra.image
        assert batched.image

    def test_cross_shop_identity_is_missing_sku(self):
        owner_a, shop_a = _make_retailer('oe124_svc_a', 'OE124 Shop A')
        owner_b, shop_b = _make_retailer('oe124_svc_b', 'OE124 Shop B')
        product_a = _make_product(shop_a, 'Tenant A Oil', barcode='SHARED124')
        product_a.image = _gif('keep.gif')
        product_a.save()

        report = import_product_photos_for_retailer(
            retailer=shop_b,
            actor=owner_b,
            organization=shop_b.organization,
            archive=_zip_upload(
                'b.zip',
                {
                    'SHARED124.gif': MINIMAL_GIF,
                    f'{product_a.id}.gif': MINIMAL_GIF,
                },
            ),
        )

        assert report['successful_rows'] == 0
        assert report['failed_rows'] == 2
        assert all(row['error'] == 'missing SKU' for row in report['results'])
        product_a.refresh_from_db()
        assert 'keep' in product_a.image.name or product_a.image


@pytest.mark.django_db
class TestPhotoImportApi:
    def test_owner_zip_import_attaches(self, api_client):
        owner, shop = _make_retailer('oe124_api_own', 'OE124 API Owner')
        product = _make_product(shop, 'API Rice', barcode='890124100')
        api_client.force_authenticate(user=owner)

        resp = api_client.post(
            reverse('import_product_photos'),
            {'archive': _zip_upload('photos.zip', {'890124100.gif': MINIMAL_GIF})},
            format='multipart',
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['successful_rows'] == 1
        product.refresh_from_db()
        assert product.image

    def test_anonymous_cannot_upload(self, api_client):
        owner, shop = _make_retailer('oe124_api_anon', 'OE124 API Anon')
        product = _make_product(shop, 'Anon Rice', barcode='890124101')

        resp = api_client.post(
            reverse('import_product_photos'),
            {'archive': _zip_upload('photos.zip', {'890124101.gif': MINIMAL_GIF})},
            format='multipart',
        )

        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
        product.refresh_from_db()
        assert not product.image

    def test_customer_cannot_upload(self, api_client):
        owner, shop = _make_retailer('oe124_api_cust', 'OE124 API Cust')
        product = _make_product(shop, 'Cust Rice', barcode='890124102')
        customer = _make_customer('oe124_cust')
        api_client.force_authenticate(user=customer)

        resp = api_client.post(
            reverse('import_product_photos'),
            {'archive': _zip_upload('photos.zip', {'890124102.gif': MINIMAL_GIF})},
            format='multipart',
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        product.refresh_from_db()
        assert not product.image

    def test_cashier_without_permission_gets_403_and_resource_unchanged(
        self, api_client
    ):
        owner, shop = _make_retailer('oe124_api_csh', 'OE124 API Cashier')
        cashier = _make_staff(shop.organization, 'oe124_csh', [])
        loc = _make_location_profile(cashier, shop.organization, 'OE124 Cashier Loc')
        product = _make_product(loc, 'Cashier Rice', barcode='890124103')
        product.image_url = 'https://example.com/keep.jpg'
        product.save()
        api_client.force_authenticate(user=cashier)

        resp = api_client.post(
            reverse('import_product_photos'),
            {'archive': _zip_upload('photos.zip', {'890124103.gif': MINIMAL_GIF})},
            format='multipart',
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert 'Catalog image' in resp.data['error']
        product.refresh_from_db()
        assert product.image_url == 'https://example.com/keep.jpg'
        assert not product.image
        assert not OrgAuditLog.objects.filter(
            object_type=OrgAuditLog.OBJECT_PRODUCT_IMAGE
        ).exists()

    def test_staff_with_catalog_image_can_import(self, api_client):
        owner, shop = _make_retailer('oe124_api_staff', 'OE124 API Staff')
        staff = _make_staff(
            shop.organization, 'oe124_staff_ok', [PERM_CATALOG_IMAGE]
        )
        loc = _make_location_profile(staff, shop.organization, 'OE124 Staff Loc')
        product = _make_product(loc, 'Staff Rice', barcode='890124104')
        api_client.force_authenticate(user=staff)

        resp = api_client.post(
            reverse('import_product_photos'),
            {'archive': _zip_upload('photos.zip', {'890124104.gif': MINIMAL_GIF})},
            format='multipart',
        )

        assert resp.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.image

    def test_tenant_b_cannot_mutate_tenant_a(self, api_client):
        owner_a, shop_a = _make_retailer('oe124_api_ten_a', 'OE124 API A')
        product = _make_product(shop_a, 'A Rice', barcode='890124105')
        product.image = _gif('a-keep.gif')
        product.save()
        old_name = product.image.name
        owner_b, shop_b = _make_retailer('oe124_api_ten_b', 'OE124 API B')
        api_client.force_authenticate(user=owner_b)

        resp = api_client.post(
            reverse('import_product_photos'),
            {
                'archive': _zip_upload(
                    'photos.zip',
                    {
                        '890124105.gif': MINIMAL_GIF,
                        f'{product.id}.gif': MINIMAL_GIF,
                    },
                )
            },
            format='multipart',
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['successful_rows'] == 0
        assert resp.data['failed_rows'] == 2
        product.refresh_from_db()
        assert product.image.name == old_name

    def test_replace_via_api_clears_old_default(self, api_client):
        owner, shop = _make_retailer('oe124_api_rep', 'OE124 API Replace')
        product = _make_product(shop, 'Replace Rice', barcode='890124106')
        product.image = _gif('old-api.gif')
        product.image_url = 'https://example.com/old-api.jpg'
        product.save()
        extra = ProductImage.objects.create(
            product=product,
            image=_gif('old-primary.gif'),
            is_primary=True,
        )
        old_name = product.image.name
        api_client.force_authenticate(user=owner)

        resp = api_client.post(
            reverse('import_product_photos'),
            {'archive': _zip_upload('photos.zip', {'890124106.gif': MINIMAL_GIF})},
            format='multipart',
        )

        assert resp.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        extra.refresh_from_db()
        assert product.image.name != old_name
        assert not product.image_url
        assert extra.is_primary is False

    def test_csv_multipart_import(self, api_client):
        owner, shop = _make_retailer('oe124_api_csv', 'OE124 API Csv')
        product = _make_product(shop, 'Csv Rice', barcode='890124107')
        api_client.force_authenticate(user=owner)

        resp = api_client.post(
            reverse('import_product_photos'),
            {
                'csv': _csv_upload('map.csv', 'barcode,filename\n890124107,rice.gif\n'),
                'images': _gif('rice.gif'),
            },
            format='multipart',
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['successful_rows'] == 1
        product.refresh_from_db()
        assert product.image
