"""
Replay inventory logs to repair product/batch drift (KAN-75).

Default is dry-run — no writes and no row locks. Use --apply only on staging
or after explicit approval (not on prod directly).

--apply without --product-id rewrites every selected SKU; require
--confirm-all-drifted for that blast radius.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from products.inventory_service import reconcile_product_from_logs
from products.models import Product


class Command(BaseCommand):
    help = (
        'Replay product_inventory_log movements to repair stock drift. '
        'Dry-run by default; pass --apply to write changes. '
        '--apply without --product-id also requires --confirm-all-drifted.'
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
        parser.add_argument(
            '--confirm-all-drifted',
            action='store_true',
            help='Required with --apply when --product-id is omitted (bulk rewrite)',
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

        if options['apply'] and not product_id and not options.get('confirm_all_drifted'):
            raise CommandError(
                '--apply without --product-id rewrites every selected SKU. '
                'Re-run with --confirm-all-drifted, or pass --product-id=<id>.'
            )

        products = Product.objects.filter(track_inventory=True)
        if product_id:
            products = products.filter(id=product_id)
        if drifted_only:
            products = (
                products.filter(has_batches=True)
                .annotate(
                    batch_sum=Coalesce(
                        Sum(
                            'batches__quantity',
                            filter=Q(batches__is_active=True),
                        ),
                        Value(0),
                        output_field=DecimalField(max_digits=12, decimal_places=3),
                    )
                )
                .exclude(quantity=F('batch_sum'))
            )

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
            if not result.get('base_trusted', True):
                line += ' base_untrusted=True'
            if dry_run:
                self.stdout.write(line)
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"{line} applied={result.get('applied_quantity')}"
                ))
            if result.get('warning'):
                self.stdout.write(self.style.WARNING(f"  warning: {result['warning']}"))

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    'Dry-run only — no changes written. Re-run with --apply on staging after review.'
                )
            )
