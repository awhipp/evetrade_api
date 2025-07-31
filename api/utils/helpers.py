'''
Helper functions for the project
'''

def round_value(value: float, amount: int) -> str:
    '''
    Round a float to a specified amount of decimal places with comma grouping
    '''
    # Round the value to the specified decimal places
    rounded_value = float(round(value, amount))
    
    # Format with commas using Python's built-in formatting
    if amount == 0:
        return f"{rounded_value:,.0f}"
    else:
        return f"{rounded_value:,.{amount}f}"


def remove_mismatch_type_ids(list_one: list, list_two: list) -> dict:
    '''
    Remove all type IDs that are not in both lists.
    '''
    from_orders = {}
    to_orders = {}
    
    for order in list_one:
        if order['type_id'] not in from_orders:
            from_orders[order['type_id']] = []
        from_orders[order['type_id']].append(order)
        
    for order in list_two:
        if order['type_id'] not in to_orders:
            to_orders[order['type_id']] = []
        to_orders[order['type_id']].append(order)
    
    from_ids = list(from_orders.keys())
    to_ids = list(to_orders.keys())
    
    for item_id in from_ids:
        if item_id not in to_orders:
            del from_orders[item_id]
            
    for item_id in to_ids:
        if item_id not in from_orders:
            del to_orders[item_id]
    
    print(f"After: Buy ID Count = {len(from_orders)} and Sell ID Count = {len(to_orders)}") # pylint: disable=logging-fstring-interpolation
    
    return {
        'from': from_orders,
        'to': to_orders
    }