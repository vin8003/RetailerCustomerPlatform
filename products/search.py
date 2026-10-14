"""Product search matching, including multi-batch barcodes (KAN-72)."""
from django.db.models import (
    Q, Value, Case, When, TextField, IntegerField,
)
from django.db.models.functions import Cast
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank


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
        '-is_barcode',
        '-is_exact',
        '-is_startswith',
        '-in_stock',
        '-rank_score',
        '-trigram_score',
        '-discount_percentage',
        'name'
    )

    if not qs_smart.exists():
        return queryset.annotate(
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
        ).distinct().order_by('-in_stock', '-discount_percentage', 'name')

    return qs_smart
