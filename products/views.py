from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Avg, Count, Sum, Max
from django.db.models import Q, Avg, Count, Sum, Max, F, Value, Case, When, FloatField, TextField, IntegerField, DecimalField
from django.db.models.functions import Coalesce, Greatest, Cast
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from django.shortcuts import get_object_or_404
from django.utils import timezone
import logging
import json
from common.error_utils import format_exception
import pandas as pd
import os
from django.conf import settings
from datetime import datetime

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


def log_search_telemetry(query, result_count, retailer=None, user=None):
    """Asynchronously log search queries to the database"""
    if not query:
        return
        
    try:
        from .models import SearchTelemetry
        SearchTelemetry.objects.create(
            query=query[:255],
            result_count=result_count,
            retailer=retailer,
            user=user if user and user.is_authenticated else None
        )
    except Exception as e:
        logger.error(f"Failed to log search telemetry: {str(e)}")


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
