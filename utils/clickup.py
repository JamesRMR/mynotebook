import pandas as pd
from dateutil.relativedelta import relativedelta


def fix_clickup_date(date_object):
    if pd.isna(date_object):
        return None
    if date_object.hour < 12:
        return date_object.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        return (date_object.replace(hour=0, minute=0, second=0, microsecond=0) + relativedelta(days=1))


def add_client_id_to_plan_df(plan_df):

    df = plan_df.copy()

    # collect relationship fields
    relation_columns = [c for c in df.columns if "client_" in c]

    # fill na values with empty lists    
    for col in relation_columns:
        df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

    # consolidate client id lists into one column
    df['client_ids']  = df[relation_columns].apply(
        lambda row: sum([x for x in row if isinstance(x, list)], []), 
        axis=1
    )

    # check if there are plan cards that have more than one client linked
    too_many = df[df['client_ids'].apply(lambda x: len(x) > 1)]
    if not too_many.empty:
        for index, row in too_many.iterrows():
            print(f"{row.get("name")} ({row.get("task_id")}) has too many clients linked!")
        raise ValueError("Too many clients linked to plan card!")

    # create column with just one client id (if one is linked)
    # by extracting the first item from the consolidated client ids column
    df['client_id'] = df['client_ids'].apply(lambda x: x[0] if len(x) > 0 else None)

    # drop the relationship columns
    df.drop(columns=relation_columns + ["client_ids"], inplace=True)

    return df
