
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
        ).annotate(
            total_sold=Coalesce(Sum('orderitem__quantity'), 0),
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        ).filter(
            total_sold__gt=0
        ).order_by('-total_sold')[:10]

        serializer = ProductListSerializer(products, many=True)
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
        ).annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews'),
            # We can also order by most recently bought
            last_bought=Max('orderitem__order__created_at')
        ).order_by('-last_bought').distinct()[:10]

        serializer = ProductListSerializer(products, many=True)
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
        ).annotate(
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
        
        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting recommended products: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
