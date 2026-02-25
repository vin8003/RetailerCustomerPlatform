from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Avg, Count, Sum, Max
from django.db.models import Q, Avg, Count, Sum, Max, F, Value, Case, When, FloatField, TextField, IntegerField
from django.db.models.functions import Coalesce, Greatest, Cast
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from django.shortcuts import get_object_or_404
from django.utils import timezone
import logging
import json

from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from decimal import Decimal, InvalidOperation

from .models import (
    Product, ProductCategory, ProductBrand, ProductReview,
    ProductUpload, ProductInventoryLog, MasterProduct,
    ProductUploadSession, UploadSessionItem
)
from .serializers import (
    ProductListSerializer, ProductDetailSerializer, ProductCreateSerializer,
    ProductUpdateSerializer, ProductCategorySerializer, ProductBrandSerializer,
    ProductReviewSerializer, ProductUploadSerializer, ProductBulkUploadSerializer,
    ProductStatsSerializer, MasterProductSerializer,
    ProductUploadSessionSerializer, UploadSessionItemSerializer,
    ProductSearchSerializer
)
from retailers.models import RetailerProfile
from common.permissions import IsRetailerOwner

logger = logging.getLogger(__name__)



from django.core.cache import cache

def get_cached_category_tree():
    """
    Returns a cached dictionary of the category tree.
    Cache key: 'category_tree_structure'
    Structure: {
        'node_map': {id: parent_id},
        'children_map': {parent_id: [child_ids]}
    }
    """
    cache_key = 'category_tree_structure'
    tree = cache.get(cache_key)
    
    if tree is None:
        # Fetch all active categories (lightweight)
        all_cats = list(ProductCategory.objects.filter(is_active=True).values('id', 'parent_id'))
        
        node_map = {}
        children_map = {}
        
        for cat in all_cats:
            cat_id = cat['id']
            pid = cat['parent_id']
            
            node_map[cat_id] = pid
            
            if pid:
                if pid not in children_map:
                    children_map[pid] = []
                children_map[pid].append(cat_id)
        
        tree = {
            'node_map': node_map,
            'children_map': children_map
        }
        # Cache indefinitely (None), signals will handle invalidation
        cache.set(cache_key, tree, None)
    
    return tree

def get_all_category_ids(category_id):
    """
    Get all subcategory ids efficiently using cached tree
    """
    tree = get_cached_category_tree()
    children_map = tree['children_map']
    
    # BFS to find all descendants
    try:
        target_id = int(category_id)
    except (ValueError, TypeError):
        return []

    ids_to_collect = {target_id}
    queue = [target_id]
    
    while queue:
        current_id = queue.pop(0)
        if current_id in children_map:
            for child_id in children_map[current_id]:
                if child_id not in ids_to_collect:
                    ids_to_collect.add(child_id)
                    queue.append(child_id)
                    
    return list(ids_to_collect)


def smart_product_search(queryset, search_query):
    """
    Hybrid Smart Search optimized for grocery data.
    
    Strategy:
    1. Exact/Startswith Match (Highest Priority)
    2. Full-Text Search (Ranked via Weights A-D)
    3. Fallback to simple icontains
    
    Weights:
    - A: Name
    - B: Category Name
    - C: Tags, Product Group
    - D: Description
    
    Performance:
    - Uses efficient Postgres SearchVector.
    - Recommended Index: GinIndex(SearchVector('name', 'category__name', ...))
    """
    if not search_query:
        return queryset

    # STEP 1: Normalize input
    query = " ".join(search_query.lower().split())
    if not query:
        return queryset

    # STEP 2 & 3: Primary Search (FTS) & Exact Match Boost
    # Define Weighted Search Vector
    vector = (
        SearchVector('name', weight='A') +
        SearchVector('category__name', weight='B') +
        SearchVector(Cast('tags', TextField()), weight='C') +
        SearchVector('product_group', weight='C') +
        SearchVector('description', weight='D')
    )
    
    search_query_obj = SearchQuery(query)

    # Annotate with Rank and Exact Boosts
    qs_smart = queryset.annotate(
        rank_score=SearchRank(vector, search_query_obj),
        is_barcode=Case(
            When(barcode__icontains=query, then=Value(1)),
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
        )
    ).filter(
        Q(rank_score__gt=0) |
        Q(is_barcode=1)
    )

    # STEP 5: Ordering
    # Priority: Barcode > Exact > Startswith > Rank > Name
    qs_smart = qs_smart.order_by(
        '-is_barcode',
        '-is_exact',
        '-is_startswith',
        '-rank_score',
        'name'
    )

    # STEP 6: Fallback logic
    if not qs_smart.exists():
        # Fallback to original icontains logic
        return queryset.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(tags__icontains=query) |
            Q(category__name__icontains=query) |
            Q(product_group__icontains=query) |
            Q(barcode__icontains=query)
        )
    
    return qs_smart


class ProductPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_retailer_products(request):
    """
    Get products for authenticated retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        products = Product.objects.select_related(
            'retailer', 'category', 'brand', 'master_product'
        ).annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).filter(retailer=retailer).order_by('-created_at')

        # Apply filters
        category = request.query_params.get('category')
        brand = request.query_params.get('brand')
        is_active = request.query_params.get('is_active')
        is_featured = request.query_params.get('is_featured')
        is_available = request.query_params.get('is_available')
        in_stock = request.query_params.get('in_stock')

        if category:
            if category.isdigit():
                category_ids = get_all_category_ids(category)
                products = products.filter(category_id__in=category_ids)
            else:
                products = products.filter(category__name__icontains=category)

        if brand:
            products = products.filter(brand__name__icontains=brand)

        if is_active is not None:
            products = products.filter(is_active=is_active.lower() == 'true')

        if is_featured is not None:
            products = products.filter(is_featured=is_featured.lower() == 'true')

        if is_available is not None:
            products = products.filter(is_available=is_available.lower() == 'true')

        if in_stock is not None:
            if in_stock.lower() == 'true':
                products = products.filter(quantity__gt=0)
            else:
                products = products.filter(quantity=0)

        # Search functionality
        search = request.query_params.get('search')
        if search:
            products = smart_product_search(products, search)

        # Pre-fetch active offers for N+1 optimization in serializer
        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        # Pagination
        paginator = ProductPagination()
        page = paginator.paginate_queryset(products, request)

        if page is not None:
            serializer = ProductListSerializer(page, many=True, context={'request': request, 'active_offers': active_offers})
            return paginator.get_paginated_response(serializer.data)

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting retailer products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_products(request):
    """
    Search products for authenticated retailer with minimal data
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        products = Product.objects.filter(retailer=retailer, is_active=True).order_by('-created_at')

        # Apply search
        search = request.query_params.get('search')
        if search:
            products = smart_product_search(products, search)

        # Apply category filter if provided
        if category:
            if category.isdigit():
                category_ids = get_all_category_ids(category)
                products = products.filter(category_id__in=category_ids)
            else:
                products = products.filter(category__name__icontains=category)

        # Limit results for search
        limit = int(request.query_params.get('limit', 50))
        products = products[:limit]

        serializer = ProductSearchSerializer(products, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error searching retailer products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_product(request):
    """
    Create a new product for authenticated retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can create products'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ProductCreateSerializer(
            data=request.data,
            context={'retailer': retailer}
        )

        if serializer.is_valid():
            product = serializer.save()

            # Log inventory addition
            ProductInventoryLog.objects.create(
                product=product,
                log_type='added',
                quantity_change=product.quantity,
                previous_quantity=0,
                new_quantity=product.quantity,
                reason='Initial product creation',
                created_by=request.user
            )

            # Pre-fetch active offers for optimization
            from offers.models import Offer
            from django.utils import timezone
            active_offers = list(Offer.objects.filter(
                retailer=retailer,
                is_active=True,
                start_date__lte=timezone.now()
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
            ).order_by('-priority').prefetch_related('targets'))

            response_serializer = ProductDetailSerializer(product, context={'request': request, 'active_offers': active_offers})
            logger.info(f"Product created: {product.name} by {retailer.shop_name}")
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error creating product: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_product_detail(request, product_id):
    """
    Get product detail for authenticated retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Optimize query with select_related and prefetch_related
        queryset = Product.objects.select_related(
            'retailer', 'category', 'brand'
        ).prefetch_related(
            'additional_images', 'reviews', 'reviews__customer'
        )
        
        product = get_object_or_404(queryset, id=product_id, retailer=retailer)
        # Pre-fetch active offers for optimization
        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductDetailSerializer(product, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting product detail: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_product(request, product_id):
    """
    Update product for authenticated retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can update products'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        product = get_object_or_404(Product, id=product_id, retailer=retailer)
        old_quantity = product.quantity

        serializer = ProductUpdateSerializer(
            product,
            data=request.data,
            partial=request.method == 'PATCH'
        )

        if serializer.is_valid():
            product = serializer.save()

            # Log inventory change if quantity changed
            new_quantity = product.quantity
            if old_quantity != new_quantity:
                quantity_change = new_quantity - old_quantity
                log_type = 'added' if quantity_change > 0 else 'removed'

                ProductInventoryLog.objects.create(
                    product=product,
                    log_type=log_type,
                    quantity_change=abs(quantity_change),
                    previous_quantity=old_quantity,
                    new_quantity=new_quantity,
                    reason='Product update',
                    created_by=request.user
                )

            # Pre-fetch active offers for optimization
            from offers.models import Offer
            from django.utils import timezone
            active_offers = list(Offer.objects.filter(
                retailer=retailer,
                is_active=True,
                start_date__lte=timezone.now()
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
            ).order_by('-priority').prefetch_related('targets'))

            response_serializer = ProductDetailSerializer(product, context={'request': request, 'active_offers': active_offers})
            logger.info(f"Product updated: {product.name} by {retailer.shop_name}")
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error updating product: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_product(request, product_id):
    """
    Delete product for authenticated retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can delete products'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        product = get_object_or_404(Product, id=product_id, retailer=retailer)
        product_name = product.name

        # Soft delete - set as inactive
        product.is_active = False
        product.save()

        logger.info(f"Product deleted: {product_name} by {retailer.shop_name}")
        return Response(
            {'message': 'Product deleted successfully'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error deleting product: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_retailer_products_public(request, retailer_id):
    """
    Get products for a specific retailer (public endpoint)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)

        products = Product.objects.select_related(
            'retailer', 'category', 'brand', 'master_product'
        ).annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).filter(
            retailer=retailer,
            is_active=True,
            is_available=True
        ).order_by('-is_featured', '-created_at')

        # Apply filters
        category = request.query_params.get('category')
        brand = request.query_params.get('brand')
        min_price = request.query_params.get('min_price')
        max_price = request.query_params.get('max_price')
        in_stock = request.query_params.get('in_stock')
        offer_id = request.query_params.get('offer_id')
        product_group = request.query_params.get('product_group')

        # Offer filtering
        if offer_id:
            from offers.models import Offer
            try:
                offer = Offer.objects.prefetch_related('targets').get(id=offer_id, retailer=retailer, is_active=True)
                targets = offer.targets.all()
                if targets:
                    inclusion_q = Q()
                    exclusion_q = Q()
                    has_all_products = False

                    for target in targets:
                        q = Q()
                        if target.target_type == 'all_products':
                            if not target.is_excluded:
                                has_all_products = True
                        elif target.target_type == 'product':
                            q = Q(id=target.product_id)
                        elif target.target_type == 'category':
                            cat_ids = get_all_category_ids(target.category_id)
                            q = Q(category_id__in=cat_ids)
                        elif target.target_type == 'brand':
                            q = Q(brand_id=target.brand_id)
                        
                        if target.is_excluded:
                            exclusion_q |= q
                        else:
                            inclusion_q |= q
                    
                    if has_all_products:
                        if exclusion_q:
                            products = products.exclude(exclusion_q)
                    else:
                        if inclusion_q:
                            products = products.filter(inclusion_q)
                        if exclusion_q:
                            products = products.exclude(exclusion_q)
                else:
                    products = products.none()
            except Offer.DoesNotExist:
                pass

        if category:
            if category.isdigit():
                category_ids = get_all_category_ids(category)
                products = products.filter(category_id__in=category_ids)
            else:
                products = products.filter(category__name__icontains=category)

        if product_group:
            products = products.filter(product_group=product_group)

        if brand:
            products = products.filter(brand__name__icontains=brand)

        if min_price:
            try:
                products = products.filter(price__gte=float(min_price))
            except ValueError:
                pass

        if max_price:
            try:
                products = products.filter(price__lte=float(max_price))
            except ValueError:
                pass

        if in_stock and in_stock.lower() == 'true':
            products = products.filter(quantity__gt=0)

        # Search functionality
        search = request.query_params.get('search')
        if search:
            products = smart_product_search(products, search)

        # Ordering
        ordering = request.query_params.get('ordering', '-created_at')
        if ordering in ['name', '-name', 'price', '-price', 'created_at', '-created_at']:
            products = products.order_by(ordering)

        # Pre-fetch active offers for N+1 optimization in serializer
        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        # Pagination
        paginator = ProductPagination()
        page = paginator.paginate_queryset(products, request)

        if page is not None:
            serializer = ProductListSerializer(page, many=True, context={'request': request, 'active_offers': active_offers})
            return paginator.get_paginated_response(serializer.data)

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting retailer products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def search_products_public(request, retailer_id):
    """
    Search products for a specific retailer (public endpoint) with minimal data
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)

        products = Product.objects.filter(
            retailer=retailer, 
            is_active=True,
            is_available=True
        ).order_by('-is_featured', '-created_at')

        # Apply search
        search = request.query_params.get('search')
        if search:
            products = smart_product_search(products, search)

        # Apply category filter if provided
        category = request.query_params.get('category')
        if category:
            if category.isdigit():
                category_ids = get_all_category_ids(category)
                products = products.filter(category_id__in=category_ids)
            else:
                products = products.filter(category__name__icontains=category)

        # Limit results for search
        limit = int(request.query_params.get('limit', 50))
        products = products[:limit]

        serializer = ProductSearchSerializer(products, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error searching public retailer products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_retailer_categories(request, retailer_id):
    """
    Get categories that have products for a specific retailer (public endpoint).
    Supports hierarchical fetching:
    - If parent_id is not provided, returns root categories (that have active products in themselves or descendants).
    - If parent_id IS provided, returns direct children of that parent.
    Includes recursive product counts.
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        requested_parent_id = request.query_params.get('parent_id')
        if requested_parent_id == 'null' or requested_parent_id == '':
            requested_parent_id = None
        else:
            requested_parent_id = int(requested_parent_id) if requested_parent_id else None

        # 1. Get raw counts for all categories that have products for this retailer
        # This gives us {category_id: direct_product_count}
        raw_counts_qs = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True,
            category__isnull=False
        ).values('category_id').annotate(count=Count('id'))
        
        category_product_map = {item['category_id']: item['count'] for item in raw_counts_qs}
        used_category_ids = set(category_product_map.keys())

        if not used_category_ids:
            return Response([], status=status.HTTP_200_OK)

        # 2. Use Cached Tree Structure to calculate hierarchy
        # Instead of fetching full tree every time, use the cached parent map
        tree = get_cached_category_tree()
        node_map = tree['node_map'] # id -> parent_id

        # 3. Propagate counts
        # We also need to fetch details (name, icon) ONLY for relevant categories, not all
        
        # First, calculate recursive counts and find all relevant ancestors
        recursive_counts = {} # id -> count
        relevant_categories = set()
        
        for cat_id, count in category_product_map.items():
            current_id = cat_id
            # Traverse up using cached map
            visited = set()
            while current_id in node_map:
                if current_id in visited:
                    logger.warning(f"Cycle detected in category tree at id {current_id}")
                    break
                visited.add(current_id)
                
                recursive_counts[current_id] = recursive_counts.get(current_id, 0) + count
                relevant_categories.add(current_id)
                current_id = node_map[current_id] # Get parent
                if current_id is None:
                    break
        
        # 4. Filter for logic
        target_ids = []
        
        # We only care about categories that match `requested_parent_id`
        for cat_id in relevant_categories:
            parent_id = node_map.get(cat_id)
            if parent_id == requested_parent_id:
                target_ids.append(cat_id)

        # 5. Fetch ONLY the target category objects (much smaller query)
        target_categories = ProductCategory.objects.filter(id__in=target_ids).order_by('name')
        serializer = ProductCategorySerializer(target_categories, many=True, context={'request': request})
        
        data = serializer.data
        # Inject recursive counts
        for item in data:
            item['product_count'] = recursive_counts.get(item['id'], 0)
        
        return Response(data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting retailer categories: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_retailer_product_groups_by_category(request, retailer_id, category_id):
    """
    Get all unique product groups for a specific retailer and category (public endpoint).
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        category_ids = get_all_category_ids(category_id)
        
        groups = Product.objects.filter(
            retailer=retailer,
            category_id__in=category_ids,
            is_active=True,
            is_available=True,
            product_group__isnull=False
        ).exclude(product_group='').values_list('product_group', flat=True).distinct()
        
        all_groups = sorted(list(groups))
        return Response(all_groups, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting retailer product groups by category: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_retailer_featured_products(request, retailer_id):
    """
    Get featured products for a specific retailer (public endpoint).
    Returns at most 10 featured products, optimized for home page display.
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)

        products = Product.objects.select_related(
            'retailer', 'category', 'brand', 'master_product'
        ).annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).filter(
            retailer=retailer,
            is_active=True,
            is_available=True,
            is_featured=True
        ).order_by('-created_at')[:10]

        # Pre-fetch active offers for N+1 optimization in serializer
        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        # Pre-fetch wishlist product IDs for the authenticated user
        wishlisted_product_ids = []
        if request.user.is_authenticated:
            from customers.models import CustomerWishlist
            wishlisted_product_ids = list(CustomerWishlist.objects.filter(
                customer=request.user
            ).values_list('product_id', flat=True))

        serializer = ProductListSerializer(
            products, 
            many=True, 
            context={
                'request': request, 
                'active_offers': active_offers,
                'wishlisted_product_ids': wishlisted_product_ids
            }
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting retailer featured products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_product_detail_public(request, retailer_id, product_id):
    """
    Get product detail (public endpoint)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        
        # Optimize query with select_related and prefetch_related
        queryset = Product.objects.select_related(
            'retailer', 'category', 'brand'
        ).prefetch_related(
            'additional_images', 'reviews', 'reviews__customer'
        )
        
        product = get_object_or_404(
            queryset,
            id=product_id,
            retailer=retailer,
            is_active=True,
            is_available=True
        )

        # Pre-fetch active offers for optimization
        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        # Pre-fetch wishlist product IDs for the authenticated user
        wishlisted_product_ids = []
        if request.user.is_authenticated:
            from customers.models import CustomerWishlist
            wishlisted_product_ids = list(CustomerWishlist.objects.filter(
                customer=request.user
            ).values_list('product_id', flat=True))

        serializer = ProductDetailSerializer(
            product, 
            context={
                'request': request, 
                'active_offers': active_offers,
                'wishlisted_product_ids': wishlisted_product_ids
            }
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting product detail: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def upload_products_excel(request):
    """
    Upload products via Excel file for authenticated retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can upload products'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ProductBulkUploadSerializer(data=request.data)
        if serializer.is_valid():
            file = serializer.validated_data['file']

            # Create upload record
            upload = ProductUpload.objects.create(
                retailer=retailer,
                file=file,
                status='processing'
            )

            try:
                # Process Excel file
                result = process_excel_upload(file, retailer, request.user)

                # Update upload record
                upload.status = 'completed'
                upload.total_rows = result['total_rows']
                upload.processed_rows = result['processed_rows']
                upload.successful_rows = result['successful_rows']
                upload.failed_rows = result['failed_rows']
                upload.error_log = result['error_log']
                upload.completed_at = timezone.now()
                upload.save()

                logger.info(f"Products uploaded: {result['successful_rows']} success, {result['failed_rows']} failed")

                return Response({
                    'message': 'Products uploaded successfully',
                    'upload_id': upload.id,
                    'total_rows': result['total_rows'],
                    'successful_rows': result['successful_rows'],
                    'failed_rows': result['failed_rows'],
                    'error_log': result['error_log']
                }, status=status.HTTP_200_OK)

            except Exception as e:
                # Update upload record with error
                upload.status = 'failed'
                upload.error_log = [{'error': str(e)}]
                upload.completed_at = timezone.now()
                upload.save()

                logger.error(f"Error processing Excel upload: {str(e)}")
                return Response(
                    {'error': f'Failed to process Excel file: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error uploading products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_product_categories(request):
    """
    Get all product categories
    """
    try:
        categories = ProductCategory.objects.filter(is_active=True, parent=None)
        serializer = ProductCategorySerializer(categories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting product categories: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_all_categories(request):
    """
    Get all product categories (flat list for autocomplete)
    """
    try:
        categories = ProductCategory.objects.filter(is_active=True).order_by('name')
        
        search = request.query_params.get('search')
        if search:
            categories = categories.filter(name__icontains=search)
            
        data = []
        for cat in categories:
            name = cat.name
            if cat.parent:
                name = f"{cat.parent.name} > {cat.name}"
            data.append({
                'id': cat.id,
                'name': name,
                'raw_name': cat.name
            })
            
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting all categories: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_product_groups(request):
    """
    Get all unique product groups
    """
    try:
        # Get from both MasterProduct and Product
        groups_master = MasterProduct.objects.filter(product_group__isnull=False).values_list('product_group', flat=True).distinct()
        groups_retail = Product.objects.filter(product_group__isnull=False).values_list('product_group', flat=True).distinct()
        
        all_groups = sorted(list(set(list(groups_master) + list(groups_retail))))
        
        search = request.query_params.get('search')
        if search:
            all_groups = [g for g in all_groups if search.lower() in g.lower()]
            
        return Response(all_groups, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting product groups: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_product_brands(request):
    """
    Get all product brands
    """
    try:
        brands = ProductBrand.objects.filter(is_active=True)
        
        search = request.query_params.get('search')
        if search:
            brands = brands.filter(name__icontains=search)
            # Limit results when searching to avoid huge payload
            brands = brands[:20]
        else:
            # If no search, maybe limit to top 50 or popular ones?
            # Or just return all (but cached)?
            # For now, let's limit to 100 on default to prevent lag, expecting user to search
            brands = brands[:100]
            
        serializer = ProductBrandSerializer(brands, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting product brands: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_product_stats(request):
    """
    Get product statistics for authenticated retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access product stats'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        products = Product.objects.filter(retailer=retailer)

        # Calculate statistics
        total_products = products.count()
        active_products = products.filter(is_active=True).count()
        out_of_stock_products = products.filter(quantity=0).count()
        low_stock_products = products.filter(quantity__lte=10, quantity__gt=0).count()
        featured_products = products.filter(is_featured=True).count()

        # Get categories and brands count
        total_categories = products.values('category').distinct().count()
        total_brands = products.values('brand').distinct().count()

        # Calculate average price
        avg_price = products.aggregate(avg_price=Avg('price'))['avg_price'] or 0

        # Get top categories
        top_categories = products.values('category__name').annotate(
            count=Count('id')
        ).order_by('-count')[:5]

        # Get recent products
        recent_products = products.order_by('-created_at')[:5]
        recent_products_data = []
        for product in recent_products:
            recent_products_data.append({
                'id': product.id,
                'name': product.name,
                'price': product.price,
                'quantity': product.quantity,
                'created_at': product.created_at
            })

        stats_data = {
            'total_products': total_products,
            'active_products': active_products,
            'out_of_stock_products': out_of_stock_products,
            'low_stock_products': low_stock_products,
            'featured_products': featured_products,
            'total_categories': total_categories,
            'total_brands': total_brands,
            'average_price': avg_price,
            'top_categories': list(top_categories),
            'recent_products': recent_products_data
        }

        serializer = ProductStatsSerializer(stats_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting product stats: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def process_excel_upload(file, retailer, user):
    """
    Process Excel file upload for products
    """
    try:
        # Read Excel file
        # Read Excel file
        if file.name.endswith('.csv'):
            # Ensure we start from the beginning
            file.seek(0)
            # Try reading with default settings first
            try:
                df = pd.read_csv(file)
            except Exception:
                # If that fails, try with python engine and fallback delimiters
                file.seek(0)
                try:
                    df = pd.read_csv(file, sep=None, engine='python')
                except Exception:
                    # Try tab separator explicitly if common csv fails
                    file.seek(0)
                    df = pd.read_csv(file, sep='\t')
        else:
            df = pd.read_excel(file)

        total_rows = len(df)
        processed_rows = 0
        successful_rows = 0
        failed_rows = 0
        error_log = []

        # Expected columns
        required_columns = ['name', 'price', 'quantity']
        optional_columns = ['description', 'category', 'brand', 'unit', 'image']

        # Check required columns
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

        # Process each row
        for index, row in df.iterrows():
            processed_rows += 1

            try:
                # Get or create category
                category = None
                if 'category' in row and pd.notna(row['category']):
                    category, _ = ProductCategory.objects.get_or_create(
                        name=row['category'],
                        defaults={'is_active': True}
                    )

                # Get or create brand
                brand = None
                if 'brand' in row and pd.notna(row['brand']):
                    brand, _ = ProductBrand.objects.get_or_create(
                        name=row['brand'],
                        defaults={'is_active': True}
                    )

                # Create product
                product_data = {
                    'retailer': retailer,
                    'name': row['name'],
                    'price': float(row['price']),
                    'quantity': int(row['quantity']),
                    'description': row.get('description', ''),
                    'category': category,
                    'brand': brand,
                    'unit': row.get('unit', 'piece'),
                }

                # Check if product already exists
                existing_product = Product.objects.filter(
                    retailer=retailer,
                    name=row['name']
                ).first()

                if existing_product:
                    # Update existing product
                    old_quantity = existing_product.quantity
                    for key, value in product_data.items():
                        if key != 'retailer':
                            setattr(existing_product, key, value)
                    existing_product.save()

                    # Log inventory change
                    if old_quantity != existing_product.quantity:
                        quantity_change = existing_product.quantity - old_quantity
                        log_type = 'added' if quantity_change > 0 else 'removed'

                        ProductInventoryLog.objects.create(
                            product=existing_product,
                            log_type=log_type,
                            quantity_change=abs(quantity_change),
                            previous_quantity=old_quantity,
                            new_quantity=existing_product.quantity,
                            reason='Excel upload update',
                            created_by=user
                        )
                else:
                    # Create new product
                    product = Product.objects.create(**product_data)

                    # Log inventory addition
                    ProductInventoryLog.objects.create(
                        product=product,
                        log_type='added',
                        quantity_change=product.quantity,
                        previous_quantity=0,
                        new_quantity=product.quantity,
                        reason='Excel upload creation',
                        created_by=user
                    )

                successful_rows += 1

            except Exception as e:
                failed_rows += 1
                error_log.append({
                    'row': index + 1,
                    'error': str(e),
                    'data': row.to_dict()
                })

        return {
            'total_rows': total_rows,
            'processed_rows': processed_rows,
            'successful_rows': successful_rows,
            'failed_rows': failed_rows,
            'error_log': error_log
        }

    except Exception as e:
        raise ValueError(f"Failed to process Excel file: {str(e)}")

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_product_brand(request):
    """
    Create a new product brand - Only for retailers/admins
    """
    try:
        # Permission check: Only Retailers or Admins can create brands
        if request.user.user_type != 'retailer' and not request.user.is_staff:
            return Response(
                {'error': 'Only retailers can create brands'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = ProductBrandSerializer(data=request.data)
        if serializer.is_valid():
            brand = serializer.save()
            logger.info(f"Brand created: {brand.name} by {request.user.username}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error creating brand: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_product_category(request):
    """
    Create a new product category - Only for retailers/admins
    """
    try:
        # Permission check: Only Retailers or Admins can create categories
        if request.user.user_type != 'retailer' and not request.user.is_staff:
            return Response(
                {'error': 'Only retailers can create categories'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = ProductCategorySerializer(data=request.data)
        if serializer.is_valid():
            category = serializer.save()
            logger.info(f"Category created: {category.name} by {request.user.username}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error creating category: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_master_product(request):
    """
    Search for a product in the Master Product Catalog by barcode
    """
    try:
        # Permission check: Only Retailers
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can search master products'},
                status=status.HTTP_403_FORBIDDEN
            )
            
        barcode = request.query_params.get('barcode')
        if not barcode:
            return Response(
                {'error': 'Barcode parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            # Case insensitive exact match for barcode
            master_product = MasterProduct.objects.get(barcode__iexact=barcode.strip())
            serializer = MasterProductSerializer(master_product)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except MasterProduct.DoesNotExist:
             return Response(
                {'message': 'Product not found in master catalog'},
                status=status.HTTP_404_NOT_FOUND
            )
            
    except Exception as e:
        logger.error(f"Error searching master product: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def check_bulk_upload(request):
    """
    Check bulk upload file for existing master products
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can upload products'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate file
        if 'file' not in request.FILES:
            return Response(
                {'error': 'No file uploaded'},
                status=status.HTTP_400_BAD_REQUEST
            )

        file = request.FILES['file']
        
        try:
            if file.name.endswith('.csv'):
                # Ensure we start from the beginning
                file.seek(0)
                # Try reading with default settings first
                try:
                    df = pd.read_csv(file)
                except Exception:
                    # If that fails, try with python engine and fallback delimiters
                    file.seek(0)
                    try:
                        df = pd.read_csv(file, sep=None, engine='python')
                    except Exception:
                        # Try tab separator explicitly if common csv fails
                        file.seek(0)
                        df = pd.read_csv(file, sep='\t')
            else:
                df = pd.read_excel(file)
        except Exception as e:
            return Response(
                {'error': f'Failed to process file: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Normalize column names
        df.columns = df.columns.astype(str).str.lower().str.strip()
        
        # Check required columns
        required_columns = ['barcode', 'mrp', 'rate', 'stock qty']
        # Handle potential tab-separated issues where columns might be merged
        if len(df.columns) == 1 and len(required_columns) > 1:
             # Retrying read assuming tab separator if only 1 column found
             file.seek(0)
             try:
                df = pd.read_csv(file, sep='\t')
                df.columns = df.columns.astype(str).str.lower().str.strip()
             except:
                pass

        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return Response(
                {'error': f"Missing required columns: {', '.join(missing_columns)}. Found: {', '.join(df.columns)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Extract barcodes and clean them
        df['barcode'] = df['barcode'].astype(str).str.strip()
        df = df[df['barcode'].notna() & (df['barcode'] != 'nan')]
        
        barcodes = df['barcode'].unique().tolist()
        
        # 1. Fetch matching MasterProducts in one query
        master_products = MasterProduct.objects.filter(barcode__in=barcodes)
        master_product_map = {mp.barcode: mp for mp in master_products}
        
        # 2. Fetch existing Retailer Products for these barcodes in one query
        existing_products = Product.objects.filter(retailer=retailer, barcode__in=barcodes)
        existing_product_map = {p.barcode: p for p in existing_products}
        
        matched_products_report = []
        unmatched_products_report = []
        
        # 3. Fetch existing Retailer Products by NAME for the matched master products
        #    This is to prevent unique_together(retailer, name) constraint violations and to merge products
        matched_mp_names = [mp.name for mp in master_products]
        existing_products_by_name = Product.objects.filter(retailer=retailer, name__in=matched_mp_names)
        existing_product_name_map = {p.name: p for p in existing_products_by_name}

        products_to_create = []
        products_to_update = []
        inventory_logs = []
        
        # Track names processed in this batch to prevent duplicates within the file itself
        processed_names_batch = set()

        for index, row in df.iterrows():
            barcode = row['barcode']
            mrp = row.get('mrp')
            rate = row.get('rate')
            qty = row.get('stock qty')
            
            # Use the maps instead of DB queries
            master_product = master_product_map.get(barcode)
            
            if master_product:
                matched_products_report.append({
                    'barcode': barcode,
                    'name': master_product.name,
                    'mrp': mrp,
                    'rate': rate,
                    'stock qty': qty,
                    'status': 'Matched'
                })
                
                price = float(rate) if pd.notna(rate) else 0
                original_price = float(mrp) if pd.notna(mrp) else 0
                quantity = int(qty) if pd.notna(qty) else 0
                
                # Check priority: 1. By Barcode, 2. By Name
                existing_product = existing_product_map.get(barcode)
                if not existing_product:
                    existing_product = existing_product_name_map.get(master_product.name)

                if existing_product:
                    # Prepare for update
                    needs_update = False
                    
                    # Update metadata linkage if finding by name
                    if existing_product.barcode != barcode:
                        existing_product.barcode = barcode
                        needs_update = True
                    if existing_product.master_product != master_product:
                        existing_product.master_product = master_product
                        needs_update = True
                        # Also update details from master if linking for first time
                        if existing_product.image_url != master_product.image_url:
                            existing_product.image_url = master_product.image_url
                            needs_update = True

                    if pd.notna(rate) and existing_product.price != price:
                        existing_product.price = price
                        needs_update = True
                    if pd.notna(mrp) and existing_product.original_price != original_price:
                        existing_product.original_price = original_price
                        needs_update = True
                        
                    # Handle quantity logic
                    if pd.notna(qty):
                        old_qty = existing_product.quantity
                        if old_qty != quantity:
                            existing_product.quantity = quantity
                            needs_update = True
                            
                            # Log inventory change
                            inventory_logs.append(ProductInventoryLog(
                                product=existing_product, # Note: This works because object exists
                                log_type='added' if quantity > old_qty else 'removed',
                                quantity_change=abs(quantity - old_qty),
                                previous_quantity=old_qty,
                                new_quantity=quantity,
                                reason='Bulk upload update',
                                created_by=request.user
                            ))
                    
                    if needs_update:
                        products_to_update.append(existing_product)
                        
                else:
                    # Prepare for creation
                    # Ensure we don't duplicate names within this batch
                    if master_product.name in processed_names_batch:
                         # Skip duplicate in same batch, or log warning?
                         # For now, let's skip to avoid error, maybe add to error report theoretically but here matched report is already done
                         continue
                         
                    processed_names_batch.add(master_product.name)

                    new_product = Product(
                        retailer=retailer,
                        name=master_product.name,
                        barcode=barcode,
                        price=price,
                        original_price=original_price,
                        quantity=quantity,
                        description=master_product.description,
                        category=master_product.category,
                        brand=master_product.brand,
                        image_url=master_product.image_url,
                        master_product=master_product,
                        is_active=True
                    )
                    products_to_create.append(new_product)
                    
            else:
                 unmatched_products_report.append({
                    'barcode': barcode,
                    'mrp': mrp,
                    'rate': rate,
                    'stock qty': qty,
                    'product name': '',
                    'category': '',
                    'brand': '',
                    'description': '',
                    'unit': 'piece'
                })

        # Bulk Operations
        try:
            if products_to_create:
                created_products = Product.objects.bulk_create(products_to_create)
                # Create logs for new products
                new_logs = []
                for p in created_products:
                    new_logs.append(ProductInventoryLog(
                        product=p,
                        log_type='added',
                        quantity_change=p.quantity,
                        previous_quantity=0,
                        new_quantity=p.quantity,
                        reason='Bulk upload creation',
                        created_by=request.user
                    ))
                inventory_logs.extend(new_logs)

            if products_to_update:
                Product.objects.bulk_update(products_to_update, ['price', 'original_price', 'quantity'])

            if inventory_logs:
                ProductInventoryLog.objects.bulk_create(inventory_logs)
                
        except Exception as e:
            logger.error(f"Bulk operation failed: {str(e)}")
            # In case of DB error, the response will still show reports but might miss DB updates
            # Ideally we should rollback, but for now we just log it. 
            # With transaction.atomic() we could be safer.

        # Generate reports (same as before)
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', 'reports')
        os.makedirs(upload_dir, exist_ok=True)
        
        matched_filename = f"matched_products_{retailer.id}_{timestamp}.xlsx"
        unmatched_filename = f"unmatched_products_{retailer.id}_{timestamp}.xlsx"
        
        matched_path = os.path.join(upload_dir, matched_filename)
        unmatched_path = os.path.join(upload_dir, unmatched_filename)
        
        # Save matched
        if matched_products_report:
            pd.DataFrame(matched_products_report).to_excel(matched_path, index=False)
        else:
            pd.DataFrame(columns=['barcode', 'name', 'mrp', 'rate', 'stock qty', 'status']).to_excel(matched_path, index=False)
            
        # Save unmatched
        if unmatched_products_report:
             pd.DataFrame(unmatched_products_report).to_excel(unmatched_path, index=False)
        else:
             pd.DataFrame(columns=['barcode', 'mrp', 'rate', 'stock qty', 'product name', 'category', 'brand', 'description', 'unit']).to_excel(unmatched_path, index=False)

        # Construct URLs
        media_url = settings.MEDIA_URL
        if not media_url.endswith('/'):
            media_url += '/'
            
        matched_url = f"{request.scheme}://{request.get_host()}{media_url}uploads/reports/{matched_filename}"
        unmatched_url = f"{request.scheme}://{request.get_host()}{media_url}uploads/reports/{unmatched_filename}"

        return Response({
            'message': 'File processed successfully',
            'matched_count': len(matched_products_report),
            'unmatched_count': len(unmatched_products_report),
            'matched_file_url': matched_url,
            'unmatched_file_url': unmatched_url
        })
        
    except Exception as e:
        logger.error(f"Error check bulk upload: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def complete_bulk_upload(request):
    """
    Complete bulk upload for unmatched products
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can upload products'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate file
        if 'file' not in request.FILES:
            return Response(
                {'error': 'No file uploaded'},
                status=status.HTTP_400_BAD_REQUEST
            )

        file = request.FILES['file']
        
        try:
            if file.name.endswith('.csv'):
                # Ensure we start from the beginning
                file.seek(0)
                # Try reading with default settings first
                try:
                    df = pd.read_csv(file)
                except Exception:
                    # If that fails, try with python engine and fallback delimiters
                    file.seek(0)
                    try:
                        df = pd.read_csv(file, sep=None, engine='python')
                    except Exception:
                        # Try tab separator explicitly if common csv fails
                        file.seek(0)
                        df = pd.read_csv(file, sep='\t')
            else:
                df = pd.read_excel(file)
        except Exception as e:
            return Response(
                {'error': f'Failed to process file: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Normalize column names
        df.columns = df.columns.astype(str).str.lower().str.strip()
        
        # Check required columns from the template
        required_columns = ['barcode', 'rate', 'stock qty', 'product name']
        # Handle potential tab-separated issues where columns might be merged
        if len(df.columns) == 1 and len(required_columns) > 1:
             # Retrying read assuming tab separator if only 1 column found
             file.seek(0)
             try:
                df = pd.read_csv(file, sep='\t')
                df.columns = df.columns.astype(str).str.lower().str.strip()
             except:
                pass

        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return Response(
                {'error': f"Missing required columns: {', '.join(missing_columns)}. Found: {', '.join(df.columns)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Pre-fetch existing data to minimize DB hits
        # Fetched existing Categories
        cat_names = df['category'].dropna().astype(str).unique().tolist()
        existing_categories = ProductCategory.objects.filter(name__in=cat_names)
        category_map = {c.name.lower(): c for c in existing_categories}
        
        # Fetched existing Brands
        brand_names = df['brand'].dropna().astype(str).unique().tolist()
        existing_brands = ProductBrand.objects.filter(name__in=brand_names)
        brand_map = {b.name.lower(): b for b in existing_brands}
        
        # Existing Products (by name, as unmatched products rely on manual name entry)
        product_names = df['product name'].dropna().astype(str).str.strip().unique().tolist()
        existing_products = Product.objects.filter(retailer=retailer, name__in=product_names)
        existing_product_map = {p.name.lower(): p for p in existing_products}

        success_count = 0
        failed_count = 0
        errors = []
        
        products_to_create = []
        products_to_update = []
        inventory_logs = []
        
        # Need to handle creating new categories/brands on the fly if they don't exist
        # To avoid complex bulk logic for new foreign keys, we'll create them sequentially if missing
        # but cache them in the map.
        
        for index, row in df.iterrows():
            try:
                name = str(row['product name']).strip()
                if not name or name.lower() == 'nan':
                    continue
                    
                barcode = str(row['barcode']).strip() if pd.notna(row.get('barcode')) else None
                rate = float(row['rate']) if pd.notna(row.get('rate')) else 0
                mrp = float(row['mrp']) if pd.notna(row.get('mrp')) else 0
                qty = int(row['stock qty']) if pd.notna(row.get('stock qty')) else 0
                
                # Category
                category = None
                cat_name = row.get('category')
                if pd.notna(cat_name):
                    cat_name_str = str(cat_name).strip()
                    cat_key = cat_name_str.lower()
                    if cat_key in category_map:
                        category = category_map[cat_key]
                    else:
                        category = ProductCategory.objects.create(name=cat_name_str, is_active=True)
                        category_map[cat_key] = category # Cache it
                
                # Brand
                brand = None
                brand_name = row.get('brand')
                if pd.notna(brand_name):
                    brand_name_str = str(brand_name).strip()
                    brand_key = brand_name_str.lower()
                    if brand_key in brand_map:
                        brand = brand_map[brand_key]
                    else:
                        brand = ProductBrand.objects.create(name=brand_name_str, is_active=True)
                        brand_map[brand_key] = brand # Cache it

                # Check existing product by name
                existing_product = existing_product_map.get(name.lower())
                
                if existing_product:
                    # Update
                    needs_update = False
                    if existing_product.price != rate:
                        existing_product.price = rate
                        needs_update = True
                    if existing_product.original_price != mrp:
                        existing_product.original_price = mrp
                        needs_update = True
                    
                    # Update metadata if provided
                    if barcode and existing_product.barcode != barcode:
                         existing_product.barcode = barcode
                         needs_update = True
                    if category and existing_product.category != category:
                         existing_product.category = category
                         needs_update = True
                    if brand and existing_product.brand != brand:
                         existing_product.brand = brand
                         needs_update = True
                        
                    old_qty = existing_product.quantity
                    if old_qty != qty:
                        existing_product.quantity = qty
                        needs_update = True
                        
                        inventory_logs.append(ProductInventoryLog(
                            product=existing_product,
                            log_type='added' if qty > old_qty else 'removed',
                            quantity_change=abs(qty - old_qty),
                            previous_quantity=old_qty,
                            new_quantity=qty,
                            reason='Bulk upload update (unmatched)',
                            created_by=request.user
                        ))
                    
                    if needs_update:
                        products_to_update.append(existing_product)

                else:
                    # Create
                    new_product = Product(
                        retailer=retailer,
                        name=name,
                        barcode=barcode,
                        price=rate,
                        original_price=mrp,
                        quantity=qty,
                        description=str(row.get('description', '')) if pd.notna(row.get('description')) else '',
                        category=category,
                        brand=brand,
                        unit=str(row.get('unit', 'piece')) if pd.notna(row.get('unit')) else 'piece',
                        is_active=True
                    )
                    products_to_create.append(new_product)
                    
                success_count += 1
                
            except Exception as e:
                failed_count += 1
                errors.append(f"Row {index + 2}: {str(e)}")

        # Bulk Write
        try:
            if products_to_create:
                created_products = Product.objects.bulk_create(products_to_create)
                # Create logs for new products
                new_logs = []
                for p in created_products:
                    new_logs.append(ProductInventoryLog(
                        product=p,
                        log_type='added',
                        quantity_change=p.quantity,
                        previous_quantity=0,
                        new_quantity=p.quantity,
                        reason='Bulk upload creation (unmatched)',
                        created_by=request.user
                    ))
                inventory_logs.extend(new_logs)

            if products_to_update:
                Product.objects.bulk_update(products_to_update, ['price', 'original_price', 'quantity', 'barcode', 'category', 'brand'])

            if inventory_logs:
                ProductInventoryLog.objects.bulk_create(inventory_logs)
                
        except Exception as e:
            logger.error(f"Bulk complete upload failed: {str(e)}")
            return Response(
                 {'error': f"Database error during bulk save: {str(e)}"},
                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'message': 'Upload processed',
            'success_count': success_count,
            'failed_count': failed_count,
            'errors': errors
        })
 
    except Exception as e:
        logger.error(f"Error complete bulk upload: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# --- Visual Bulk Upload Views ---

class CreateUploadSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
            # Check for existing active session? Or allow multiple?
            # Let's create a new one.
            name = request.data.get('name', 'Untitled Session')
            session = ProductUploadSession.objects.create(retailer=retailer, name=name)
            serializer = ProductUploadSessionSerializer(session)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except RetailerProfile.DoesNotExist:
            return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class GetActiveSessionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
             # Find sessions that are not completed
             sessions = ProductUploadSession.objects.filter(
                 retailer__user=request.user, 
                 status='active'
             ).order_by('-created_at')
             serializer = ProductUploadSessionSerializer(sessions, many=True)
             return Response(serializer.data)
        except Exception as e:
             return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AddSessionItemView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        session_id = request.data.get('session_id')
        barcode = request.data.get('barcode', '').strip()
        image = request.FILES.get('image')

        if not session_id or not barcode:
            return Response({'error': 'session_id and barcode are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = ProductUploadSession.objects.get(id=session_id, retailer__user=request.user)
            
            # Extract optional product details
            details = {}
            
            # Check for JSON data field (preserves types)
            data_str = request.data.get('data')
            if data_str:
                try:
                    data_json = json.loads(data_str)
                    if 'name' in data_json: details['name'] = data_json['name']
                    if 'price' in data_json: details['price'] = data_json['price']
                    if 'mrp' in data_json: details['original_price'] = data_json['mrp']
                    if 'qty' in data_json: details['quantity'] = data_json['qty']
                except json.JSONDecodeError:
                    pass

            # Fallback to individual fields
            if 'name' not in details and 'name' in request.data: details['name'] = request.data['name']
            if 'price' not in details and 'price' in request.data: details['price'] = request.data['price']
            if 'original_price' not in details and 'mrp' in request.data: details['original_price'] = request.data['mrp']
            if 'quantity' not in details and 'qty' in request.data: details['quantity'] = request.data['qty']
            
            item = UploadSessionItem.objects.create(
                session=session,
                barcode=barcode,
                image=image,
                product_details=details
            )
            serializer = UploadSessionItemSerializer(item)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except ProductUploadSession.DoesNotExist:
            return Response({'error': 'Session not found or access denied'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class GetSessionDetailsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, session_id):
        try:
            session = ProductUploadSession.objects.get(id=session_id, retailer__user=request.user)
            items = session.items.all().order_by('-created_at')
            
            # Smart Lookup Logic
            # Optimization: Fetch all barcodes at once and map to MasterProducts
            barcodes = [item.barcode for item in items]
            
            # 1. Master Product Match
            master_products = MasterProduct.objects.filter(barcode__in=barcodes)
            master_map = {mp.barcode: mp for mp in master_products}
            
            # 2. Existing Local Product Match (by Barcode)
            retailer = session.retailer
            local_products = Product.objects.filter(retailer=retailer, barcode__in=barcodes)
            local_map = {p.barcode: p for p in local_products}

            # 3. Existing Local Product Match (by Name if MP found) - To prevent duplicate name error
            matched_mp_names = [mp.name for mp in master_products]
            local_products_by_name = Product.objects.filter(retailer=retailer, name__in=matched_mp_names)
            local_name_map = {p.name: p for p in local_products_by_name}

            response_data = {
                'session': ProductUploadSessionSerializer(session).data,
                'matched_items': [],
                'unmatched_items': []
            }

            for item in items:
                item_data = UploadSessionItemSerializer(item).data
                details = item.product_details # Draft data if any

                matched_mp = master_map.get(item.barcode)
                existing_local = local_map.get(item.barcode)
                
                # If no existing local by barcode, check by name (if MP exists)
                if not existing_local and matched_mp:
                     existing_local = local_name_map.get(matched_mp.name)

                if matched_mp:
                    # Matched Logic
                    mp_data = MasterProductSerializer(matched_mp).data
                    
                    # Merge data for UI: Draft > Existing Local > Master
                    final_name = details.get('name') or (existing_local.name if existing_local else matched_mp.name)
                    final_price = details.get('price') or (existing_local.price if existing_local else 0)
                    final_stock = details.get('quantity') or (existing_local.quantity if existing_local else 0)
                    final_mrp = details.get('original_price') or (existing_local.original_price if existing_local else matched_mp.mrp or 0)
                    
                    # Fix: Add Brand and Category
                    final_brand = details.get('brand') or (existing_local.brand.name if existing_local and existing_local.brand else (matched_mp.brand.name if matched_mp.brand else ""))
                    final_category = details.get('category') or (existing_local.category.name if existing_local and existing_local.category else (matched_mp.category.name if matched_mp.category else ""))
                    final_product_group = details.get('product_group') or (existing_local.product_group if existing_local else matched_mp.product_group) or ""

                    item_data['master_product'] = mp_data
                    item_data['existing_product_id'] = existing_local.id if existing_local else None
                    
                    # Pre-fill UI fields
                    item_data['ui_data'] = {
                        'name': final_name,
                        'price': final_price,
                        'original_price': final_mrp,
                        'quantity': final_stock,
                        'brand': final_brand,
                        'category': final_category,
                        'product_group': final_product_group,
                        'image_url': matched_mp.image_url if matched_mp.image_url else "",
                        'images': mp_data.get('images', []) 
                    }
                    response_data['matched_items'].append(item_data)
                else:
                    # Unmatched Logic
                    # Merge data for UI: Draft > Existing Local (only if barcode matched locally but not in MP DB? Rare) > Default
                    
                    final_name = details.get('name') or (existing_local.name if existing_local else "")
                    final_price = details.get('price') or (existing_local.price if existing_local else 0)
                    final_stock = details.get('quantity') or (existing_local.quantity if existing_local else 0)
                    final_mrp = details.get('original_price') or (existing_local.original_price if existing_local else 0)
                    final_brand = details.get('brand') or (existing_local.brand.name if existing_local and existing_local.brand else "")
                    final_category = details.get('category') or (existing_local.category.name if existing_local and existing_local.category else "")
                    final_product_group = details.get('product_group') or (existing_local.product_group if existing_local else "")

                    item_data['existing_product_id'] = existing_local.id if existing_local else None
                    item_data['ui_data'] = {
                        'name': final_name,
                        'price': final_price,
                        'original_price': final_mrp,
                        'quantity': final_stock,
                        'brand': final_brand,
                        'category': final_category,
                        'product_group': final_product_group,
                    }
                    response_data['unmatched_items'].append(item_data)

            return Response(response_data)

        except ProductUploadSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)


class UpdateSessionItemsView(APIView):
    # ... (No changes needed here for logic, keeping it compact in diff)
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        session_id = request.data.get('session_id')
        items_data = request.data.get('items', []) 

        if not session_id:
            return Response({'error': 'session_id required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = ProductUploadSession.objects.get(id=session_id, retailer__user=request.user)
            
            updated_count = 0
            for item in items_data:
                item_id = item.get('id')
                details = item.get('product_details') 
                barcode = item.get('barcode')

                if item_id and details:
                    try:
                        session_item = UploadSessionItem.objects.get(id=item_id, session=session)
                        session_item.product_details = details
                        if barcode:
                            session_item.barcode = barcode
                        session_item.save()
                        updated_count += 1
                    except UploadSessionItem.DoesNotExist:
                        continue
            
            return Response({'message': f'Updated {updated_count} items'}, status=status.HTTP_200_OK)

        except ProductUploadSession.DoesNotExist:
             return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)


class CommitUploadSessionView(APIView):
    """
    Finalize Session: Create/Update actual products
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        session_id = request.data.get('session_id')
        
        if not session_id:
            return Response({'error': 'session_id required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = ProductUploadSession.objects.get(id=session_id, retailer__user=request.user)
            retailer = session.retailer
            
            if session.status == 'completed':
                 return Response({'error': 'Session already completed'}, status=status.HTTP_400_BAD_REQUEST)

            items = session.items.all()
            
            created_count = 0
            updated_count = 0
            
            with transaction.atomic():
                print(f"DEBUG: Processing {len(items)} items for Session {session.id}")
                for item in items:
                    details = item.product_details
                    print(f"DEBUG: Item {item.id} details: {details}")
                    # Change: Do not skip if details are empty. Create Draft instead.
                    
                    barcode = item.barcode
                    name = details.get('name')
                    
                    # Safe conversion to numeric types
                    try:
                        price = Decimal(str(details.get('price', 0)))
                    except (ValueError, TypeError, InvalidOperation):
                        price = Decimal('0.00')
                        
                    try:
                        mrp = Decimal(str(details.get('original_price', 0)))
                    except (ValueError, TypeError, InvalidOperation):
                        mrp = Decimal('0.00')
                        
                    try:
                        qty = int(float(str(details.get('quantity', 0))))
                    except (ValueError, TypeError):
                        qty = 0
                    
                    is_draft_item = False
                    if not name:
                        print(f"DEBUG: Creating Draft for Item {item.id} - No name found")
                        name = f"Draft Item {barcode}"
                        is_draft_item = True

                    # Identify Targets
                    # 1. Master Product
                    try:
                        master_product = MasterProduct.objects.get(barcode=barcode)
                        if is_draft_item and master_product:
                             # If we have master product, auto-fill name even if user didn't provide it
                             name = master_product.name
                             is_draft_item = False # Not a draft if we have a valid name
                    except MasterProduct.DoesNotExist:
                        master_product = None
                    
                    # 2. Existing Local Product
                    existing_product = None
                    try:
                        existing_product = Product.objects.get(retailer=retailer, barcode=barcode)
                    except Product.DoesNotExist:
                        existing_product = Product.objects.filter(retailer=retailer, name__iexact=name).first()

                    # Handle Category/Brand creation if unmatched
                    category = None
                    brand = None
                    
                    if not master_product:
                        # Try to get category from category_id or category field (which might be the ID)
                        cat_id = details.get('category_id') or details.get('category')
                        if cat_id:
                             try:
                                # Check if it's an integer ID
                                if isinstance(cat_id, (int, str)) and str(cat_id).isdigit():
                                    category = ProductCategory.objects.get(id=int(cat_id))
                             except (ProductCategory.DoesNotExist, ValueError):
                                pass
                        
                        brand_id = details.get('brand_id') or details.get('brand')
                        if brand_id:
                             try:
                                if isinstance(brand_id, (int, str)) and str(brand_id).isdigit():
                                    brand = ProductBrand.objects.get(id=int(brand_id))
                             except (ProductBrand.DoesNotExist, ValueError):
                                pass

                    product_group = details.get('product_group')


                    if existing_product:
                        # UPDATE (including reactivating soft-deleted products)
                        print(f"DEBUG: Updating existing product {existing_product.id}")
                        existing_product.price = price
                        existing_product.original_price = mrp
                        existing_product.quantity = qty 
                        
                        # Reactivate if it was soft-deleted
                        if not existing_product.is_active:
                            existing_product.is_active = True
                            print(f"DEBUG: Reactivating soft-deleted product {existing_product.id}")
                        
                        if master_product and not existing_product.master_product:
                            existing_product.master_product = master_product
                        
                        if barcode and existing_product.barcode != barcode:
                             existing_product.barcode = barcode
                             
                        if item.image and not existing_product.image:
                             existing_product.image = item.image
                             
                        if product_group:
                            existing_product.product_group = product_group

                        existing_product.save()
                        updated_count += 1
                    else:
                        # CREATE
                        print(f"DEBUG: Creating new product '{name}'")
                        new_prod = Product(
                            retailer=retailer,
                            name=name,
                            barcode=barcode,
                            price=price,
                            original_price=mrp,
                            quantity=qty,
                            master_product=master_product,
                            image=item.image,
                            is_draft=is_draft_item,
                            is_active=not is_draft_item,
                            product_group=product_group
                        )
                        if category: new_prod.category = category
                        if brand: new_prod.brand = brand
                        
                        if master_product:
                            if not category and master_product.category: new_prod.category = master_product.category
                            if not brand and master_product.brand: new_prod.brand = master_product.brand
                        
                        new_prod.save()
                        created_count += 1
                    
                    item.is_processed = True
                    item.save()
            
            print(f"DEBUG: Session {session.id} completed. Created: {created_count}, Updated: {updated_count}")
            session.status = 'completed'
            session.save()
            
            return Response({
                'created_count': created_count,
                'updated_count': updated_count
            }, status=status.HTTP_200_OK)
            
            return Response({'message': 'Session committed', 'count': success_count})

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_best_selling_products(request, retailer_id):
    """
    Get top selling products for a specific retailer (public endpoint)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)

        # Get top products by sales volume
        # We need to import OrderItem locally to avoid circular import if not already imported
        from orders.models import OrderItem
        
        # Get products with high sales count
        # Note: This is an approximation. Ideally we aggregate OrderItems directly.
        # But we want to return Product objects.
        products = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True
        ).select_related('master_product', 'category', 'brand', 'retailer').annotate(
            total_sold=Coalesce(Sum('orderitem__quantity'), 0),
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).filter(
            total_sold__gt=0
        ).order_by('-total_sold')[:10]

        # Pre-fetch active offers for N+1 optimization in serializer
        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting best selling products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_buy_again_products(request, retailer_id):
    """
    Get products previously bought by the authenticated user from this retailer
    """
    try:
        if request.user.user_type != 'customer':
             # If not customer (e.g. retailer browsing), return empty or error?
             # Let's return empty list for now to avoid UI breakage
            return Response([], status=status.HTTP_200_OK)

        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        
        # Find products in user's past delivered orders
        from orders.models import Order
        
        # improved query: distinct products from user's orders
        products = Product.objects.filter(
            orderitem__order__customer=request.user,
            orderitem__order__retailer=retailer,
            orderitem__order__status='delivered',
            is_active=True, 
            is_available=True
        ).select_related('master_product', 'category', 'brand', 'retailer').annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews'),
            # We can also order by most recently bought
            last_bought=Max('orderitem__order__created_at')
        ).order_by('-last_bought').distinct()[:10]

        # Pre-fetch active offers for N+1 optimization in serializer
        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting buy again products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_recommended_products(request, retailer_id):
    """
    Get recommended products for the user (based on past purchases or popular items)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        
        # Simple recommendation strategy:
        # 1. Look at categories user has bought from
        # 2. Recommend other top-rated products from those categories
        # 3. If no history, Fallback to 'Best Selling' logic but exclude what user already bought if possible.
        
        # For MVP, let's just return high rated products in random order or similar
        # Or let's try category based if possible.
        
        user_categories = []
        if request.user.user_type == 'customer':
            from orders.models import OrderItem
            # Get IDs of categories user bought from
            user_categories = Product.objects.filter(
                orderitem__order__customer=request.user,
                orderitem__order__retailer=retailer,
                category__isnull=False
            ).values_list('category', flat=True).distinct()
            
        products = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True
        ).select_related('master_product', 'category', 'brand', 'retailer').annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        )
        
        if user_categories:
            # boost products in these categories
            # Actually, standard filter
            products = products.filter(category__in=user_categories)
        
        # Order by rating and random
        products = products.order_by('-average_rating_annotated', '?')[:10]
        
        # If not enough products, we could fill with others, but let's keep it simple.
        
        # Pre-fetch active offers for N+1 optimization in serializer
        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting recommended products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class DeleteSessionItemView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, item_id):
        try:
            # ensure item belongs to a session owned by the retailer
            item = UploadSessionItem.objects.get(
                id=item_id, 
                session__retailer__user=request.user
            )
            item.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except UploadSessionItem.DoesNotExist:
            return Response({'error': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_deals_of_the_day(request, retailer_id):
    """
    Get Deals of the Day (highest discount percentage > 0)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        products = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True,
            discount_percentage__gt=0
        ).select_related('master_product', 'category', 'brand', 'retailer').annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).order_by('-discount_percentage')[:10]

        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting deals of the day: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_budget_buys(request, retailer_id):
    """
    Get Budget Buys (price <= 99)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        limit_price = float(request.query_params.get('max_price', 99))
        products = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True,
            price__lte=limit_price
        ).select_related('master_product', 'category', 'brand', 'retailer').annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).order_by('price')[:10]

        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting budget buys: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_trending_products(request, retailer_id):
    """
    Get Trending Products (velocity based on last 72 hours)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        
        from django.utils import timezone
        from datetime import timedelta
        time_threshold = timezone.now() - timedelta(hours=72)
        
        # We rely on orderitem counts in the last 72h, or fallback to review counts + recent creation
        products = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True
        ).select_related('master_product', 'category', 'brand', 'retailer').annotate(
            recent_sales=Count('orderitem', filter=Q(orderitem__order__created_at__gte=time_threshold)),
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).order_by('-recent_sales', '-review_count_annotated')[:10]

        from offers.models import Offer
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting trending products: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_new_arrivals(request, retailer_id):
    """
    Get New Arrivals (order by -created_at)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        products = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True
        ).select_related('master_product', 'category', 'brand', 'retailer').annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).order_by('-created_at')[:10]

        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting new arrivals: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_seasonal_picks(request, retailer_id):
    """
    Get Seasonal Picks (filter by is_seasonal flag)
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        products = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True,
            is_seasonal=True
        ).select_related('master_product', 'category', 'brand', 'retailer').annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).order_by('-created_at')[:10]

        from offers.models import Offer
        from django.utils import timezone
        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(products, many=True, context={'request': request, 'active_offers': active_offers})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting seasonal picks: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
