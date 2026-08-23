"""
Replay inventory logs to repair product/batch drift (KAN-75).

Default is dry-run — safe to review on production DB without writing.
Use --apply only on staging or after explicit approval (not on prod directly).
"""
from decimal import Decimal

from django.db.models import Sum

from django.core.management.base import BaseCommand

from products.inventory_service import reconcile_product_from_logs
from products.models import Product, ProductBatch


class Command(BaseCommand):
    help = (
        'Replay product_inventory_log movements to repair stock drift. '
        'Dry-run by default; pass --apply to write changes.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--product-id',
            type=int,
            help='Repair a single product by id (e.g. 111)',
        )
        parser.add_argument(
            '--drifted-only',
            action='store_true',
            help='Only products where product.quantity != sum(active batch quantities)',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Write repaired quantities (default is dry-run only)',
        )

    def handle(self, *args, **options):
        dry_run = not options['apply']
        product_id = options.get('product_id')
        drifted_only = options.get('drifted_only')

        if not product_id and not drifted_only:
            self.stderr.write(
                'Specify --product-id=<id> or --drifted-only. '
                'Dry-run is default; add --apply to write.'
            )
            return

        products = Product.objects.filter(track_inventory=True)
        if product_id:
            products = products.filter(id=product_id)
        if drifted_only:
            drifted_ids = []
            for product in products.filter(has_batches=True):
                batch_sum = (
                    product.batches.filter(is_active=True).aggregate(
                        total=Sum('quantity')
                    )['total']
                    or Decimal('0')
                )
                if Decimal(str(product.quantity)) != Decimal(str(batch_sum)):
                    drifted_ids.append(product.id)
            products = products.filter(id__in=drifted_ids)

        if not products.exists():
            self.stdout.write(self.style.WARNING('No matching products found.'))
            return

        mode = 'DRY-RUN' if dry_run else 'APPLY'
        self.stdout.write(self.style.NOTICE(f'KAN-75 reconcile [{mode}] — {products.count()} product(s)'))

        for product in products.order_by('id'):
            result = reconcile_product_from_logs(product, dry_run=dry_run)
            line = (
                f"#{result['product_id']} {result['product_name']}: "
                f"current={result['current_quantity']} "
                f"replayed={result['replayed_quantity']} "
                f"delta={result['delta']}"
            )
            if result['phantom_batch_ids']:
                line += f" phantom_batches={result['phantom_batch_ids']}"
            if dry_run:
                self.stdout.write(line)
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"{line} applied={result.get('applied_quantity')}"
                ))

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    'Dry-run only — no changes written. Re-run with --apply on staging after review.'
                )
            )
