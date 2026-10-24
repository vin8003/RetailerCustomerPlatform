from django.core.management.base import BaseCommand

from orders.pickup import expire_uncollected_pickup_orders


class Command(BaseCommand):
    help = (
        'Expire uncollected shop pickup orders past retailer policy hours, '
        'restore ATP, and cancel orders (OE-152).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--retailer-id',
            type=int,
            default=None,
            help='Limit expiry to a single retailer location id',
        )

    def handle(self, *args, **options):
        expired = expire_uncollected_pickup_orders(
            retailer_id=options.get('retailer_id'),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f'Expired {len(expired)} uncollected pickup order(s)'
            )
        )
        for row in expired:
            self.stdout.write(
                f"  - #{row['order_number']} (was {row['previous_status']}, "
                f"policy {row['policy_hours']}h)"
            )
