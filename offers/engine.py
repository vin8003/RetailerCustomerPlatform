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
        
        # Channel/Source Filtering
        channel = context.get('channel', 'mobile') if context else 'mobile'
        if channel == 'pos':
            active_offers = active_offers.filter(applicable_on__in=['pos', 'both'])
        else:
            active_offers = active_offers.filter(applicable_on__in=['mobile', 'both'])
        
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
                'applied_offer': ", ".join(x['applied_offers']) if x['applied_offers'] else None,
                'purchased_quantity': x.get('purchased_quantity', x['quantity']),
                'free_quantity': x.get('free_quantity', 0),
                'total_display_quantity': x.get('total_display_quantity', x['quantity'])
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
        Apply Buy X Get Y Free logic (Mixed Strategy)
        Optimized to be mathematically O(N) where N is distinct cart items.
        """
        # Check strategy
        # 'mixed' = Pool all items (default legacy behavior).
        # 'same_product' = Apply logic per product group.
        bxgy_strategy = getattr(offer, 'bxgy_strategy', 'mixed')

        if bxgy_strategy == 'same_product':
             return self._apply_bxgy_same_product(offer, item_context, eligible_indices)

        # 1. Sum up all eligible quantities
        total_units = sum(item_context[idx]['quantity'] for idx in eligible_indices)
        if total_units <= 0:
            return Decimal(0)

        # Calculate how many free items we are allowed
        x = offer.buy_quantity
        y = offer.get_quantity
        group_size = x + y
        num_free = int((total_units // group_size) * y)

        if num_free <= 0:
            return Decimal(0)

        # 2. Sort eligible indices by their current unit price
        # Cheapest items are discounted first
        sorted_indices = sorted(eligible_indices, key=lambda idx: item_context[idx]['current_price'])

        total_savings = Decimal(0)
        remaining_free = num_free

        for idx in sorted_indices:
            if remaining_free <= 0:
                break

            item_data = item_context[idx]
            qty = item_data['quantity']
            if qty <= 0:
                continue

            # We can discount at most the quantity of this item
            take = min(remaining_free, qty)
            price = item_data['current_price']
            
            # savings from this item
            savings_increment = take * price
            total_savings += savings_increment

            # Distribute savings back to the line item's unit price
            discount_per_unit = savings_increment / qty
            item_data['current_price'] -= discount_per_unit
            item_data['savings'] += discount_per_unit
            item_data['applied_offers'].append(offer.name)
            if not offer.is_stackable:
                item_data['is_exclusive'] = True

            remaining_free -= take

        return total_savings

    def _apply_bxgy_same_product(self, offer, item_context, eligible_indices):
        """
        Apply Buy X Get Y Free logic per product (Same Product Strategy).
        No database mutation; dynamically calculates purchased, free, and total display quantities.
        Aggregates quantities across identical products in cart before calculating free quantities.
        The quantity in the cart/POS represents the total quantity, and free items are calculated within it.
        """
        total_savings = Decimal(0)
        
        # Group indices by product_id
        product_groups = {}
        for idx in eligible_indices:
            item_data = item_context[idx]
            pid = item_data['item'].product.id
            if pid not in product_groups:
                product_groups[pid] = []
            product_groups[pid].append(idx)
            
        x = offer.buy_quantity
        y = offer.get_quantity
        group_size = x + y

        for pid, indices in product_groups.items():
            # Calculate total scanned quantity for this product group
            total_scanned_qty = sum(item_context[idx]['quantity'] for idx in indices)
            if total_scanned_qty <= 0:
                continue

            # Calculate total free quantity for this product group (within scanned quantity)
            full_groups = total_scanned_qty // group_size
            remainder = total_scanned_qty % group_size
            total_free_qty = (full_groups * y) + max(0, remainder - x)
            if total_free_qty <= 0:
                continue

            remaining_free = total_free_qty
            for i, idx in enumerate(indices):
                item_data = item_context[idx]
                scanned_qty = item_data['quantity']

                # Proportional distribution of free qty across items
                if i == len(indices) - 1:
                    line_free_qty = remaining_free
                else:
                    line_free_qty = int(total_free_qty * scanned_qty // total_scanned_qty) if total_scanned_qty > 0 else 0
                    remaining_free -= line_free_qty

                purchased_qty = scanned_qty - line_free_qty
                total_qty = scanned_qty
                price = item_data['current_price']
                
                # Savings is the value of the free items
                savings_increment = line_free_qty * price
                total_savings += savings_increment

                # Store dynamic quantities for order creation and frontend display
                item_data['purchased_quantity'] = purchased_qty
                item_data['free_quantity'] = line_free_qty
                item_data['total_display_quantity'] = total_qty

                # Effective average unit price for the entire total quantity
                effective_price = (purchased_qty * price) / total_qty if total_qty > 0 else price
                
                item_data['quantity'] = total_qty
                item_data['current_price'] = effective_price
                
                # Average saving per unit in total quantity
                item_data['savings'] += savings_increment / total_qty if total_qty > 0 else 0
                
                if offer.name not in item_data['applied_offers']:
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
