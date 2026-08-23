from rest_framework import serializers
from decimal import Decimal
from django.db import transaction
from django.db.models import Avg, F, Sum
from returns.models import PurchaseReturnItem
from .models import (
    Product, ProductCategory, ProductBrand, ProductImage, 
    ProductReview, ProductUpload, MasterProduct, ProductBatch,
    ProductUploadSession, UploadSessionItem,
    PurchaseInvoice, PurchaseItem, SupplierLedger
)
from .customer_stock import filter_in_stock_for_customer
import logging

logger = logging.getLogger(__name__)
