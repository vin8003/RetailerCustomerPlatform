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

from pathlib import Path as _Path
_impl_dir = _Path(__file__).resolve().parent
for _i in range(6):
    exec((_impl_dir / f'_views_impl_{_i}.py').read_text(), globals())
