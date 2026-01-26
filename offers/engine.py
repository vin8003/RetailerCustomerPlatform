from decimal import Decimal
from django.utils import timezone
from .models import Offer

class OfferEngine:
    """
    Core engine to calculate applicable offers for a cart
    """
    
    def calculate_offers(self, cart_items, retailer, context=None):
        """
        Main entry point.
        Input: 
            cart_items: List of objects (must have product, quantity, unit_price, total_price attributes)
            retailer: The retailer instance
        Output:
            {
                'subtotal': Decimal,
                'discounted_total': Decimal,
                'total_savings': Decimal,
                'applied_offers': [
                    {
                        'offer_id': int,
                        'name': str,
                        'description': str,
                        'savings': Decimal,
                        'type': str
                    }
                ],
                'item_discounts': {
                    item_id: {
                        'original_price': Decimal,
                        'final_price': Decimal,
                        'applied_offer': str
                    }
                }
            }
        """
        if not cart_items:
            return self._empty_result()
            
        # 1. Fetch valid offers for this retailer
        active_offers = Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).exclude(
            end_date__lt=timezone.now()
        ).order_by('-priority')
        
        # 2. Prepare calculation context
        # We need a mutable structure to track price changes and applied rules
        item_context = []
        for item in cart_items:
            item_context.append({
                'item': item,
                'original_price': getattr(item, 'unit_price', item.product.price),
                'quantity': item.quantity,
                'current_price': getattr(item, 'unit_price', item.product.price),
                'total_price': getattr(item, 'unit_price', item.product.price) * item.quantity,
                'applied_offers': [],
                'is_exclusive': False,
                'savings': Decimal(0)
            })
            
        applied_offers_summary = []
        
        # 3. Apply Offers (Priority based)
        total_points_earned = Decimal(0)
        
        for offer in active_offers:
            # Check offer usage limits
            if offer.usage_limit_total and offer.current_redemptions >= offer.usage_limit_total:
                continue
                
            # Filter eligible items for this offer
            eligible_indices = self._get_eligible_items(offer, item_context)
            
            if not eligible_indices:
                continue
            
            # Use getattr for benefit_type in case field doesn't exist yet (migration safety during deploy, but we migrated)
            benefit_type = getattr(offer, 'benefit_type', 'discount')
            
            if benefit_type == 'credit_points':
                # Points Logic
                points = Decimal(0)
                
                if offer.offer_type == 'percentage':
                    percentage = offer.value / Decimal(100)
                    for idx in eligible_indices:
                        item = item_context[idx]
                        # Points on current price
                        p = item['current_price'] * item['quantity'] * percentage
                        points += p
                        item['savings'] += Decimal(0) # Points don't reduce price
                        item['applied_offers'].append(offer.name)
                        if not offer.is_stackable:
                             item['is_exclusive'] = True

                elif offer.offer_type == 'flat_amount':
                    # Flat points per item
                    for idx in eligible_indices:
                        item = item_context[idx]
                        points += (offer.value * item['quantity'])
                        item['applied_offers'].append(offer.name)
                        if not offer.is_stackable:
                             item['is_exclusive'] = True

                elif offer.offer_type == 'cart_value':
                     current_cart_total = sum(x['current_price'] * x['quantity'] for x in item_context)
                     if current_cart_total >= offer.min_order_value:
                         if offer.value_type == 'percent':
                             points = current_cart_total * (offer.value / Decimal(100))
                             if offer.max_discount_amount and points > offer.max_discount_amount:
                                 points = offer.max_discount_amount
                         else:
                             points = offer.value
                             
                         # Mark all as applied if not stackable
                         if not offer.is_stackable:
                             for idx in eligible_indices:
                                 item_context[idx]['is_exclusive'] = True
                                 item_context[idx]['applied_offers'].append(offer.name)
                         else:
                             for idx in eligible_indices:
                                 item_context[idx]['applied_offers'].append(offer.name)
                
                if points > 0:
                     total_points_earned += points
                     applied_offers_summary.append({
                        'offer_id': offer.id,
                        'name': offer.name,
                        'description': offer.description,
                        'savings': points, # reuse field or new? frontend expects savings for display usually.
                        'benefit_type': 'credit_points',
                        'type': offer.get_offer_type_display()
                     })
                
                continue 

            # Discount Logic (Existing)
            savings_from_this_offer = Decimal(0)
            
            if offer.offer_type == 'bxgy':
                savings_from_this_offer = self._apply_bxgy(offer, item_context, eligible_indices)
            elif offer.offer_type == 'percentage':
                savings_from_this_offer = self._apply_percentage(offer, item_context, eligible_indices)
            elif offer.offer_type == 'flat_amount':
                savings_from_this_offer = self._apply_flat_amount(offer, item_context, eligible_indices)
            elif offer.offer_type == 'cart_value':
                savings_from_this_offer = self._apply_cart_value(offer, item_context)
            
            if savings_from_this_offer > 0:
                applied_offers_summary.append({
                    'offer_id': offer.id,
                    'name': offer.name,
                    'description': offer.description,
                    'savings': savings_from_this_offer,
                    'benefit_type': 'discount',
                    'type': offer.get_offer_type_display()
                })
                
        # 4. Final Aggregation
        original_subtotal = sum(x['original_price'] * x['quantity'] for x in item_context)
        final_total = sum(x['current_price'] * x['quantity'] for x in item_context)
        
        total_savings = original_subtotal - final_total
        
        # Map back item discounts
        item_discounts = {}
        for x in item_context:
            pk = x['item'].id if hasattr(x['item'], 'id') else str(x['item'])
            item_discounts[pk] = {
                'original_price': x['original_price'],
                'final_price': x['current_price'],
                'applied_offer': ", ".join(x['applied_offers']) if x['applied_offers'] else None
            }

        return {
            'subtotal': original_subtotal.quantize(Decimal("0.01")),
            'discounted_total': final_total.quantize(Decimal("0.01")),
            'total_savings': total_savings.quantize(Decimal("0.01")),
            'total_points': total_points_earned.quantize(Decimal("0.01")),
            'applied_offers': applied_offers_summary,
            'item_discounts': item_discounts
        }

    def _get_eligible_items(self, offer, item_context):
        """
        Identify which items match the offer targets
        """
        eligible = []
        targets = list(offer.targets.all())
        
        # If no targets defined, is it strictly all products? 
        # Usually defaults to 'All' only if explicit. Here let's assume if targets exist we match, else return empty unless specific type.
        if not targets:
            # Dangerous assumption. Let's require at least one target for safety, or implicit ALL?
            # Let's say if no targets, it applies to nothing.
            return []

        for index, item_data in enumerate(item_context):
            # Check if item allows stacking
            if item_data['is_exclusive']:
                continue
            if item_data['applied_offers'] and not offer.is_stackable:
                continue
                
            product = item_data['item'].product
            
            is_match = False
            is_excluded = False
            
            for target in targets:
                if target.is_excluded:
                    # Check exclusions
                    if target.target_type == 'product' and target.product_id == product.id:
                        is_excluded = True
                    elif target.target_type == 'category' and target.category_id == product.category_id:
                        is_excluded = True
                    elif target.target_type == 'brand' and target.brand_id == product.brand_id:
                        is_excluded = True
                else:
                    # Check inclusions
                    if target.target_type == 'all_products':
                        is_match = True
                    elif target.target_type == 'product' and target.product_id == product.id:
                        is_match = True
                    elif target.target_type == 'category' and target.category_id == product.category_id:
                        is_match = True
                    elif target.target_type == 'brand' and target.brand_id == product.brand_id:
                        is_match = True
            
            if is_match and not is_excluded:
                eligible.append(index)
                
        return eligible

    def _apply_percentage(self, offer, item_context, eligible_indices):
        """
        Apply percentage discount to eligible items
        """
        total_savings = Decimal(0)
        percentage = offer.value / Decimal(100)
        
        for idx in eligible_indices:
            item_data = item_context[idx]
            
            discount = item_data['current_price'] * percentage
            # Check per-item max cap if logic required (Offer model has global cap, might need per item logic or global split)
            # Implementation simple: Just reduce price.
            
            new_price = item_data['current_price'] - discount
            if new_price < 0: new_price = Decimal(0)
            
            savings = item_data['current_price'] - new_price
            
            item_data['current_price'] = new_price
            item_data['savings'] += savings
            item_data['applied_offers'].append(offer.name)
            if not offer.is_stackable:
                item_data['is_exclusive'] = True
            
            total_savings += (savings * item_data['quantity'])
            
        return total_savings

    def _apply_bxgy(self, offer, item_context, eligible_indices):
        """
        Apply Buy X Get Y Free logic
        """
        # 1. Collect all eligible units
        # We might have multiple cart items matching (e.g. 2 different soaps)
        # BXGY usually works on pool of items. "Buy 2 soaps get 1 free" (cheapest free)
        
        all_units = []
        for idx in eligible_indices:
            item_data = item_context[idx]
            # Deconstruct quantity into individual 'units' for sorting
            # (In high volume scenarios, this is slow. Optimization: Group math. 
            # For grocery cart with < 100 items, list expansion is fine)
            for _ in range(item_data['quantity']):
                all_units.append({
                    'price': item_data['current_price'],
                    'parent_idx': idx
                })
        
        if not all_units:
            return Decimal(0)
            
        # Sort by price (Cheapest first if cheapest is free)
        # If is_cheapest_free=True, we sort ascending. 
        # If we discounted the most expensive (rare), desc.
        if offer.is_cheapest_free:
            all_units.sort(key=lambda x: x['price'])
        else:
             all_units.sort(key=lambda x: x['price']) # Default standard: usually cheapest is free.
        
        # Calculate how many sets
        # Rule: Buy X, Get Y. Total group size = X + Y.
        # Example: Buy 2 Get 1. Group = 3. 
        # If I have 3 items, 1 is free.
        # If I have 4 items, 1 is free (1 leftover)
        # If I have 6 items, 2 are free.
        
        x = offer.buy_quantity
        y = offer.get_quantity
        group_size = x + y
        
        total_units = len(all_units)
        num_free = (total_units // group_size) * y
        
        # If specific logic says "Buy X and Get Y Free" means I pay for X and Y is added?
        # Usually e-comm cart logic: "Add 3 items to cart, 1 becomes free".
        
        if num_free == 0:
            return Decimal(0)
            
        # Mark the first 'num_free' items as free (since we sorted by price ascending)
        total_savings = Decimal(0)
        
        for i in range(num_free):
            unit_to_discount = all_units[i]
            # Reduce price of this unit to 0 effectively
            # But we can't split a cart item line easily if qty > 1.
            # We must apply discount to the line item proportionally or split line.
            # Simplified: we apply total discount amount to the line item.
            
            idx = unit_to_discount['parent_idx']
            price = unit_to_discount['price']
            
            # Add to savings
            total_savings += price
            
            # Distribute this saving to the item context (reduce current price average?)
            # No, that modifies unit price. 
            # Better: Keep track of "Discount Amount" on the line item specifically.
            
            # Update specific item context
            item_data = item_context[idx]
            # We are discounting 'price' amount from the TOTAL of that line.
            # So unit_price reduces by (price / quantity).
            
            discount_per_unit = price / item_data['quantity']
            item_data['current_price'] -= discount_per_unit
            item_data['savings'] += discount_per_unit
            item_data['applied_offers'].append(offer.name)
            if not offer.is_stackable:
                item_data['is_exclusive'] = True

        return total_savings

    def _apply_flat_amount(self, offer, item_context, eligible_indices):
        # Flat amount off each item? Or total?
        # Usually "Flat ₹50 off on Product X". Applies per unit.
        
        total_savings = Decimal(0)
        amount = offer.value
        
        for idx in eligible_indices:
            item_data = item_context[idx]
            
            if item_data['current_price'] < amount:
                 amount = item_data['current_price'] # Cap at free
                 
            item_data['current_price'] -= amount
            item_data['savings'] += amount
            item_data['applied_offers'].append(offer.name)
            if not offer.is_stackable:
                item_data['is_exclusive'] = True
            
            total_savings += (amount * item_data['quantity'])
            
        return total_savings
        
    def _apply_cart_value(self, offer, item_context):
        # Check min order value
        current_cart_total = sum(x['current_price'] * x['quantity'] for x in item_context)
        
        if current_cart_total < offer.min_order_value:
            return Decimal(0)
            
        # Calc discount
        discount = Decimal(0)
        if offer.value_type == 'percent':
            discount = current_cart_total * (offer.value / Decimal(100))
            if offer.max_discount_amount and discount > offer.max_discount_amount:
                discount = offer.max_discount_amount
        else:
            discount = offer.value
            
        # Distribute discount across all items weighted by their contribution to total
        # This prevents negative prices and handles returns better
        
        if current_cart_total == 0: return 0
        
        total_savings = Decimal(0)
        
        for item_data in item_context:
            # Item's share of total
            item_total = item_data['current_price'] * item_data['quantity']
            share = item_total / current_cart_total
            
            item_discount = discount * share
            
            # Apply to unit price
            if item_data['quantity'] > 0:
                if item_data['is_exclusive']:
                    continue
                if item_data['applied_offers'] and not offer.is_stackable:
                    continue

                unit_discount = item_discount / item_data['quantity']
                item_data['current_price'] -= unit_discount
                item_data['savings'] += unit_discount
                item_data['applied_offers'].append(offer.name)
                if not offer.is_stackable:
                    item_data['is_exclusive'] = True
            
            total_savings += item_discount
            
        return total_savings

    def _empty_result(self):
        return {
            'subtotal': Decimal(0),
            'discounted_total': Decimal(0),
            'total_savings': Decimal(0),
            'applied_offers': [],
            'item_discounts': {}
        }
