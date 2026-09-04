import pandas as pd

from rockyclickup.database_interface import get_all_custom_fields


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:

    all_fields = get_all_custom_fields()
    column_names = list(df.columns)

    field_map = {
        
    }





