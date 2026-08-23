from decimal import Decimal
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Sum, Count, Avg, F
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.utils import timezone
from datetime import timedelta
import logging
import re
from common.error_utils import format_exception

from .models import Order, OrderItem, OrderStatusLog, OrderFeedback, OrderReturn, OrderChatMessage, RetailerRating
from .status_filters import apply_order_status_filter
from .serializers import (
    OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer,
    OrderStatusUpdateSerializer, OrderFeedbackSerializer, OrderReturnSerializer,
    OrderStatsSerializer, OrderModificationSerializer, OrderChatMessageSerializer,
    RetailerRatingSerializer
)
from retailers.models import RetailerProfile, RetailerReview, RetailerRewardConfig
from retailers.serializers import RetailerReviewSerializer
from customers.models import CustomerAddress, CustomerLoyalty
from django.db.models import Exists, OuterRef, Prefetch
from common.notifications import send_push_notification

logger = logging.getLogger(__name__)


class OrderPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
