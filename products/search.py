"""Product search matching, including multi-batch barcodes (KAN-72)."""
import logging
import re

from django.db import DatabaseError, connection, transaction
from django.db.models import (
    Q, Value, Case, When, TextField, IntegerField,
)
from django.db.models.functions import Cast
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank

logger = logging.getLogger(__name__)


def product_barcode_match_q(query):
    """Match primary, extra, and batch barcodes (KAN-72)."""
    if not query:
        return Q()
    return (
        Q(barcode__icontains=query) |
        Q(additional_barcodes__icontains=query) |
        Q(batches__barcode__icontains=query) |
        Q(batches__additional_barcodes__icontains=query)
    )


def product_barcode_exact_q(query):
    """Whole-code match for scans. A quoted needle matches one JSON list element, not a fragment."""
    element = f'"{query}"'
    return (
        Q(barcode__iexact=query) |
        Q(additional_barcodes__icontains=element) |
        Q(batches__barcode__iexact=query) |
        Q(batches__additional_barcodes__icontains=element)
    )


def _exact_barcode_rank(query):
    return Case(
        When(product_barcode_exact_q(query), then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )


def smart_product_search(queryset, search_query):
    """
    Hybrid Smart Search optimized for grocery data.

    Strategy:
    1. Exact/Startswith Match (Highest Priority)
    2. Full-Text Search (Ranked via Weights A-D)
    3. Trigram Similarity (Fuzzy matching/Typo tolerance)
    4. Fallback to simple icontains
    """
    from django.contrib.postgres.search import TrigramSimilarity

    if not search_query:
        return queryset

    query = " ".join(search_query.lower().split())
    if not query:
        return queryset

    vector = (
        SearchVector('name', weight='A') +
        SearchVector('category__name', weight='B') +
        SearchVector(Cast('tags', TextField()), weight='C') +
        SearchVector('product_group', weight='C') +
        SearchVector('description', weight='D')
    )

    search_query_obj = SearchQuery(query)

    qs_smart = queryset.annotate(
        is_barcode_exact=_exact_barcode_rank(query),
        rank_score=SearchRank(vector, search_query_obj),
        trigram_score=TrigramSimilarity('name', query),
        is_barcode=Case(
            When(product_barcode_match_q(query), then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        is_exact=Case(
            When(name__iexact=query, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        is_startswith=Case(
            When(name__istartswith=query, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        in_stock=Case(
            When(quantity__gt=0, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).filter(
        Q(rank_score__gt=0.05) |
        Q(trigram_score__gt=0.2) |
        Q(is_barcode=1) |
        Q(is_exact=1) |
        Q(is_startswith=1)
    ).distinct()

    qs_smart = qs_smart.order_by(
        '-is_barcode_exact',
        '-is_barcode',
        '-is_exact',
        '-is_startswith',
        '-in_stock',
        '-rank_score',
        '-trigram_score',
        '-discount_percentage',
        'name'
    )

    # Fall back to basic search when FTS/trigram finds nothing or is unavailable
    # (no pg_trgm, SQLite). The savepoint keeps a failed probe from aborting an
    # outer transaction, which PostgreSQL would otherwise do.
    try:
        with transaction.atomic():
            if qs_smart.exists():
                return qs_smart
    except DatabaseError:
        logger.warning('Smart product search failed; using the basic search', exc_info=True)

    return queryset.annotate(
        is_barcode_exact=_exact_barcode_rank(query),
        in_stock=Case(
            When(quantity__gt=0, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).filter(
        Q(name__icontains=query) |
        Q(description__icontains=query) |
        Q(tags__icontains=query) |
        Q(category__name__icontains=query) |
        Q(product_group__icontains=query) |
        product_barcode_match_q(query)
    ).distinct().order_by('-is_barcode_exact', '-in_stock', '-discount_percentage', 'name')


_SCAN_CODE = re.compile(r'^\d{6,50}$')


def barcode_scan_queryset(queryset, search_query):
    """
    The shop's products whose primary, extra or batch barcode is exactly ``search_query``, or None
    when the text is not a scanned code or nothing carries it.

    A scan is an equality lookup on indexed columns, so it skips the full-text and trigram ranking
    that has to look at every product of the shop. Text that is not a whole numeric code, and a code
    nobody has, fall through to the smart search, which also matches partial codes.
    """
    code = (search_query or '').strip()
    if not _SCAN_CODE.match(code):
        return None
    # One equality lookup per column, each on its own index. A single OR across the product and its
    # batches makes PostgreSQL walk the shop in created_at order instead of using any of them.
    base = queryset.order_by()
    lookups = [Q(barcode=code), Q(batches__barcode=code)]
    if connection.vendor == 'postgresql':
        # jsonb containment, served by the GIN indexes from migration 0038.
        lookups += [Q(additional_barcodes__contains=[code]), Q(batches__additional_barcodes__contains=[code])]
    ids = set()
    for lookup in lookups:
        ids.update(base.filter(lookup).values_list('pk', flat=True))
    if not ids:
        return None
    return queryset.filter(pk__in=ids)


def search_products_queryset(queryset, search_query):
    """A scanned code takes the exact-barcode path; everything else is the smart search."""
    return barcode_scan_queryset(queryset, search_query) or smart_product_search(queryset, search_query)
