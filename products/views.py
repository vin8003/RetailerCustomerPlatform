from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Avg, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
import pandas as pd
import io
import logging

from .models import (
    Product, ProductCategory, ProductBrand, ProductReview, 
    ProductUpload, ProductInventoryLog
)
from .serializers import (
    ProductListSerializer, ProductDetailSerializer, ProductCreateSerializer,
    ProductUpdateSerializer, ProductCategorySerializer, ProductBrandSerializer,
    ProductReviewSerializer, ProductUploadSerializer, ProductBulkUploadSerializer,
    ProductStatsSerializer
)
from retailers.models import RetailerProfile
from common.permissions import IsRetailerOwner

logger = logging.getLogger(__name__)


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
        
        products = Product.objects.filter(retailer=retailer).order_by('-created_at')
        
        # Apply filters
        category = request.query_params.get('category')
        brand = request.query_params.get('brand')
        is_active = request.query_params.get('is_active')
        is_featured = request.query_params.get('is_featured')
        is_available = request.query_params.get('is_available')
        in_stock = request.query_params.get('in_stock')
        
        if category:
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
            products = products.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search) |
                Q(tags__icontains=search)
            )
        
        # Pagination
        paginator = ProductPagination()
        page = paginator.paginate_queryset(products, request)
        
        if page is not None:
            serializer = ProductListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting retailer products: {str(e)}")
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
            
            response_serializer = ProductDetailSerializer(product)
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
        
        product = get_object_or_404(Product, id=product_id, retailer=retailer)
        serializer = ProductDetailSerializer(product)
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
            
            response_serializer = ProductDetailSerializer(product)
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
        
        products = Product.objects.filter(
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
        
        if category:
            products = products.filter(category__name__icontains=category)
        
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
            products = products.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search) |
                Q(tags__icontains=search)
            )
        
        # Ordering
        ordering = request.query_params.get('ordering', '-created_at')
        if ordering in ['name', '-name', 'price', '-price', 'created_at', '-created_at']:
            products = products.order_by(ordering)
        
        # Pagination
        paginator = ProductPagination()
        page = paginator.paginate_queryset(products, request)
        
        if page is not None:
            serializer = ProductListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting retailer products: {str(e)}")
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
        product = get_object_or_404(
            Product, 
            id=product_id, 
            retailer=retailer,
            is_active=True,
            is_available=True
        )
        
        serializer = ProductDetailSerializer(product)
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
def get_product_brands(request):
    """
    Get all product brands
    """
    try:
        brands = ProductBrand.objects.filter(is_active=True)
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
        if file.name.endswith('.csv'):
            df = pd.read_csv(file)
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
