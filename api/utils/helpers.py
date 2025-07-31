'''
Helper functions for the project
'''
import locale

# Set locale with fallback for environments with limited locale support (like AWS Lambda)
try:
    locale.setlocale(locale.LC_ALL, '')  # set the user's default locale
except locale.Error:
    # Fallback to en_US.UTF-8 or POSIX, which support number formatting
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_ALL, 'POSIX')
        except locale.Error:
            # Last resort: use C locale but this won't have comma grouping
            locale.setlocale(locale.LC_ALL, 'C')

def round_value(value: float, amount: int) -> str:
    '''
    Round a float to a specified amount of decimal places
    '''
    format_str = f'%.{amount}f'
    formatted_num = locale.format_string(format_str, value, grouping=True)
    return formatted_num


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