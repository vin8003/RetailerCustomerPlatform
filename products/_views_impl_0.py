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
        cache.set(cache_key, tree, None)
    return tree
