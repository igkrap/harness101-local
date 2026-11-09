def stable_candidate_order(catalog, faulty_ids, target_ids):
    faulty_set = set(faulty_ids)
    target_set = set(target_ids)
    
    group_faulty = []
    group_target = []
    group_other = []
    group_insert = []
    
    for item in catalog:
        item_id = item['id']
        item_kind = item['kind']
        
        if item_id in faulty_set:
            group_faulty.append(item)
        elif item_id in target_set:
            group_target.append(item)
        elif item_kind != 'insert':
            group_other.append(item)
        else:
            group_insert.append(item)
            
    return group_faulty + group_target + group_other + group_insert
